"""Type an entry in plain words; get a draft back to check and save."""

import re
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models import Business, Contact, LedgerEntry, PaymentClaim, Relationship, User
from app.routers.auth import current_user
from app.routers.businesses import _check_local_id_free
from app.routers.home import _my_relationships
from app.services import ai_entry, assistant, ledger
from app.services.common import audit, owned_business, relationship_for
from app.services.views import summary

router = APIRouter(prefix="/api/ai", tags=["ai"])


class EntryTextIn(BaseModel):
    text: str = Field(min_length=2, max_length=500)
    business_id: int | None = None  # the business open on screen, used when the text names none


class NewRecordIn(BaseModel):
    business_id: int
    name: str = Field(min_length=1, max_length=160)
    side: Literal["receivable", "payable"]
    local_id: str | None = Field(None, max_length=30)


class SaveIn(BaseModel):
    relationship_id: int | None = None
    new_record: NewRecordIn | None = None
    action: Literal["add", "subtract"]
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    description: str | None = Field(None, max_length=500)


def next_local_id(db: Session, business_id: int, side: str) -> str:
    """CUST-004 / SUP-002: one more than the highest ID of that kind in the business."""
    prefix = "CUST" if side == "receivable" else "SUP"
    taken = {k for (k,) in db.execute(select(Contact.local_key).where(Contact.business_id == business_id)) if k}
    nums = [int(m.group(1)) for k in taken if (m := re.fullmatch(rf"{prefix.lower()}-(\d+)", k))]
    n = max(nums, default=0) + 1
    while f"{prefix}-{n:03d}".lower() in taken:
        n += 1
    return f"{prefix}-{n:03d}"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    draft: dict | None = None  # the last draft, so "20" can answer "How much was it?"
    business_id: int | None = None  # the business open on screen


@router.post("/chat")
async def chat(data: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The Khataz assistant: help with the app, and entries built from a conversation."""
    records, businesses = _context(db, user)
    out = await run_in_threadpool(assistant.chat, [m.model_dump() for m in data.messages], records,
                                  businesses, user.default_currency, data.draft,
                                  lambda rel_id: _lookup(db, rel_id), data.business_id)
    if out.get("draft"):
        out["draft"] |= {"records": records, "businesses": businesses}
    return out


LABELS = {"credit": "Add money", "payment": "Subtract money", "adjustment": "Update money"}


def _lookup(db: Session, rel_id: int) -> dict:
    """Balance and the last entry that can be undone, for the assistant's tasks."""
    rel = db.get(Relationship, rel_id)
    b = ledger.balance(db, rel)
    last = db.scalar(select(LedgerEntry).where(
        LedgerEntry.relationship_id == rel.id, LedgerEntry.status == "active",
        LedgerEntry.type != "reversal", LedgerEntry.reversed_by_entry_id.is_(None),
        LedgerEntry.source != "claim").order_by(LedgerEntry.id.desc()).limit(1))
    waiting = bool(b["pending"] or b["disputed"]) or bool(db.scalar(select(func.count(PaymentClaim.id)).where(
        PaymentClaim.relationship_id == rel.id,
        PaymentClaim.state.in_(("pending_confirmation", "needs_review")))))
    recent = db.scalars(select(LedgerEntry).where(LedgerEntry.relationship_id == rel.id)
                        .order_by(LedgerEntry.id.desc()).limit(5)).all()
    return {"balance": f"{b['balance']:.2f}", "waiting": waiting,
            "recent": [{"id": e.id, "label": LABELS.get(e.type, e.type.title()), "amount": f"{e.amount:.2f}",
                        "sign": "+" if e.delta > 0 else "−", "description": e.description,
                        "status": e.status, "reversed": e.reversed_by_entry_id is not None,
                        "occurred_at": e.occurred_at} for e in recent],
            "last_entry": None if not last else {
                "id": last.id, "label": LABELS.get(last.type, last.type), "amount": f"{last.amount:.2f}",
                "description": last.description, "occurred_at": last.occurred_at}}


@router.get("/status")
def status(user: User = Depends(current_user)):
    return {"ai": bool(ai_entry.providers()), "voice_server": bool(settings.groq_api_key)}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user: User = Depends(current_user)):
    """Speech to text with Groq Whisper (free). The app falls back to the browser's own
    speech recognition when this isn't set up."""
    if not settings.groq_api_key:
        raise HTTPException(503, "Voice needs GROQ_API_KEY on the server")
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "No audio recorded")
    if len(audio) > 15 * 1024 * 1024:
        raise HTTPException(413, "Recording is too long")
    try:
        text = await run_in_threadpool(ai_entry.transcribe, audio, file.filename or "voice.webm",
                                       file.content_type or "audio/webm")
    except Exception as e:
        raise HTTPException(502, f"Couldn't understand the recording ({e})")
    return {"text": text}


def _context(db: Session, user: User) -> tuple[list[dict], list[dict]]:
    records = []
    for rel in _my_relationships(db, user):
        s = summary(db, rel, user)
        records.append({"relationship_id": s.id, "business_id": s.business_id,
                        "name": s.other_party, "local_id": s.local_id,
                        "khataz_id": s.other_khataz_id, "business_name": s.business_name,
                        "currency": s.currency, "perspective": s.perspective, "role": s.role,
                        "balance": f"{s.balance:.2f}", "direction": s.direction, "amount": f"{s.amount:.2f}"})
    mine = db.scalars(select(Business).where(Business.owner_id == user.id).order_by(Business.name)).all()
    businesses = [{"business_id": b.id, "name": b.name, "currency": b.default_currency,
                   "next_ids": {side: next_local_id(db, b.id, side) for side in ("receivable", "payable")}}
                  for b in mine]
    return records, businesses


@router.post("/entry")
async def read_entry(data: EntryTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    records, businesses = _context(db, user)
    draft = await run_in_threadpool(ai_entry.parse, data.text.strip(), records, user.default_currency, businesses,
                                  data.business_id)
    draft["records"] = records
    draft["businesses"] = businesses
    return draft


@router.post("/save", status_code=201)
def save_entry(data: SaveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Save the checked draft: into an existing record, or a new record created in the same step."""
    if bool(data.relationship_id) == bool(data.new_record):
        raise HTTPException(400, "Choose an existing record or a new one")
    if data.new_record:
        n = data.new_record
        b = owned_business(db, user, n.business_id)
        local_id = (n.local_id or "").strip() or next_local_id(db, b.id, n.side)
        _check_local_id_free(db, b.id, local_id)
        contact = Contact(business_id=b.id, name=n.name.strip(), local_id=local_id, local_key=local_id.lower())
        db.add(contact)
        db.flush()
        rel = Relationship(business_id=b.id, contact_id=contact.id, side=n.side, currency=b.default_currency)
        db.add(rel)
        db.flush()
        audit(db, user, "contact.created", "contact", contact.id, rel.id,
              after={"name": contact.name, "local_id": local_id, "side": n.side, "currency": rel.currency,
                     "via": "typed entry"})
    else:
        rel, _ = relationship_for(db, user, data.relationship_id)
    entry = ledger.add_entry(db, rel, user, "credit" if data.action == "add" else "payment", data.amount,
                             (data.description or "").strip() or None)
    db.commit()
    return {"relationship_id": rel.id, "entry_id": entry.id, "created_record": bool(data.new_record)}
