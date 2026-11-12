"""One relationship's ledger: entries, disputes, invites, payment claims, audit."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.timeutil import as_utc, utcnow
from app.models import AuditLog, Dispute, LedgerEntry, LinkInvite, PaymentClaim, User
from app.routers.auth import current_user
from app.schemas import (
    AuditOut, ClaimIn, ClaimOut, ClaimResolveIn, ClaimRespondIn, ContactOut, DisputeOut,
    DisputeResolveIn, EntryIn, EntryOut, InviteIn, ReasonIn,
)
from app.services import autocheck, claims as claim_svc
from app.services import ledger, links
from app.services.common import (
    audit, creditor_name, debtor_name, notify, relationship_for,
)
from app.services.views import claim_out, summary

router = APIRouter(prefix="/api", tags=["ledger"])


def _owner_only(role: str):
    if role != "owner":
        raise HTTPException(403, "Only the business owner can do this")


# ---------------------------------------------------------------- relationship
@router.get("/relationships/{rel_id}")
def relationship_detail(rel_id: int, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    ledger.auto_accept_expired(db)
    rel, role = relationship_for(db, user, rel_id)
    entries = db.scalars(select(LedgerEntry).where(LedgerEntry.relationship_id == rel.id)
                         .order_by(LedgerEntry.id.desc())).all()
    claims = db.scalars(select(PaymentClaim).where(PaymentClaim.relationship_id == rel.id)
                        .order_by(PaymentClaim.created_at.desc())).all()
    disputes = db.scalars(select(Dispute).join(LedgerEntry, Dispute.entry_id == LedgerEntry.id)
                          .where(LedgerEntry.relationship_id == rel.id)
                          .order_by(Dispute.created_at.desc())).all()
    invite = db.scalar(select(LinkInvite).where(LinkInvite.contact_id == rel.contact_id,
                                                LinkInvite.status == "pending"))
    totals = ledger.balance(db, rel)
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(
        {e.created_by for e in entries} | {c.submitted_by for c in claims}
        | {d.opened_by for d in disputes} | {user.id})))}
    return {
        "summary": summary(db, rel, user),
        "totals": {k: f"{v:.2f}" for k, v in totals.items()},
        "creditor": creditor_name(rel),
        "debtor": debtor_name(rel),
        "contact": ContactOut.model_validate(rel.contact) if role == "owner" else None,
        "pending_invite_email": links.invite_label(invite, db) if role == "owner" else None,
        "pending_invite_id": invite.id if invite and role == "owner" else None,
        "my_user_id": user.id,
        "names": names,
        "entries": [EntryOut.model_validate(e) for e in entries],
        "claims": [claim_out(c) for c in claims],
        "disputes": [DisputeOut.model_validate(d) for d in disputes],
    }


@router.post("/relationships/{rel_id}/entries", response_model=EntryOut, status_code=201)
def add_entry(rel_id: int, data: EntryIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Owner: counts at once. The other side: a proposal that counts after the owner confirms."""
    rel, role = relationship_for(db, user, rel_id)
    entry = ledger.add_entry(db, rel, user, data.type, data.amount, data.description,
                             as_utc(data.occurred_at), data.increase)
    db.commit()
    return entry


@router.get("/relationships/{rel_id}/audit", response_model=list[AuditOut])
def relationship_audit(rel_id: int, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    rel, _ = relationship_for(db, user, rel_id)
    logs = db.scalars(select(AuditLog).where(AuditLog.relationship_id == rel.id)
                      .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())).all()
    return [AuditOut(id=a.id, actor=a.actor.name if a.actor else None, action=a.action,
                     entity=a.entity, entity_id=a.entity_id, before=a.before, after=a.after,
                     reason=a.reason, created_at=a.created_at) for a in logs]


@router.post("/relationships/{rel_id}/archive")
def archive(rel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Remove a settled record from the lists. Its entries are kept (nothing is deleted)."""
    rel, role = relationship_for(db, user, rel_id)
    _owner_only(role)
    b = ledger.balance(db, rel)
    if b["balance"] != 0 or b["pending"] != 0 or b["disputed"] != 0:
        raise HTTPException(409, f"Settle the balance first ({b['balance']} {rel.currency}). "
                                 "Only records at zero can be removed.")
    if db.scalar(select(func.count(PaymentClaim.id)).where(
            PaymentClaim.relationship_id == rel.id,
            PaymentClaim.state.in_(("pending_confirmation", "needs_review")))):
        raise HTTPException(409, "A PayPal payment on this record is still waiting")
    rel.archived_at = utcnow()
    audit(db, user, "relationship.archived", "relationship", rel.id, rel.id)
    db.commit()
    return {"archived": True}


@router.post("/relationships/{rel_id}/invite", status_code=201)
def invite(rel_id: int, data: InviteIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """Ask the contact to confirm, from their own Khataz account, that this record is theirs."""
    rel, role = relationship_for(db, user, rel_id)
    _owner_only(role)
    inv, target = links.invite(db, rel.contact, user, rel.id, email=data.email,
                               khataz_id=data.khataz_id)
    if data.email and not rel.contact.email:  # remember the email on the contact
        rel.contact.email = data.email.lower()
    db.commit()
    mail = {}
    if data.email and data.send_email:
        mail = links.send_invite_email(inv, rel.contact, user, has_account=bool(target))
    return {"id": inv.id, "status": inv.status, "account_exists": bool(target), **mail}


# ---------------------------------------------------------------- entries
def _entry(db: Session, user: User, entry_id: int):
    entry = db.get(LedgerEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    rel, role = relationship_for(db, user, entry.relationship_id)
    return entry, rel, role


@router.post("/entries/{entry_id}/reverse", response_model=EntryOut, status_code=201)
def reverse_entry(entry_id: int, data: ReasonIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    entry, rel, role = _entry(db, user, entry_id)
    _owner_only(role)
    if entry.source == "claim":
        raise HTTPException(400, "Reverse a PayPal payment from its claim (refund or chargeback)")
    rev = ledger.reverse_entry(db, entry, rel, user, data.reason)
    db.commit()
    return rev


@router.post("/entries/{entry_id}/confirm", response_model=EntryOut)
def confirm_entry(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Owner confirms an entry the other side recorded; only now it changes the balance."""
    entry, rel, _ = _entry(db, user, entry_id)
    ledger.confirm_proposed(db, entry, rel, user)
    db.commit()
    return entry


@router.post("/entries/{entry_id}/reject", response_model=EntryOut)
def reject_entry(entry_id: int, data: ReasonIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    entry, rel, _ = _entry(db, user, entry_id)
    ledger.reject_proposed(db, entry, rel, user, data.reason)
    db.commit()
    return entry


@router.post("/entries/{entry_id}/accept", response_model=EntryOut)
def accept_entry(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry, rel, _ = _entry(db, user, entry_id)
    ledger.accept_entry(db, entry, rel, user)
    db.commit()
    return entry


@router.post("/entries/{entry_id}/cancel", response_model=EntryOut)
def cancel_entry(entry_id: int, data: ReasonIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """The other side cancels a wrong entry within the cancel window (24 hours by default)."""
    entry, rel, _ = _entry(db, user, entry_id)
    ledger.cancel_entry(db, entry, rel, user, data.reason)
    db.commit()
    return entry


@router.post("/entries/{entry_id}/dispute", response_model=DisputeOut, status_code=201)
def dispute_entry(entry_id: int, data: ReasonIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    entry, rel, _ = _entry(db, user, entry_id)
    d = ledger.dispute_entry(db, entry, rel, user, data.reason)
    db.commit()
    return d


@router.post("/disputes/{dispute_id}/resolve", response_model=DisputeOut)
def resolve_dispute(dispute_id: int, data: DisputeResolveIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    d = db.get(Dispute, dispute_id)
    if not d:
        raise HTTPException(404, "Dispute not found")
    entry, rel, _ = _entry(db, user, d.entry_id)
    ledger.resolve_dispute(db, d, entry, rel, user, data.resolution, data.note)
    db.commit()
    return d


# ---------------------------------------------------------------- payment claims
@router.post("/relationships/{rel_id}/claims/scan")
async def scan_screenshot(rel_id: int, file: UploadFile = File(...),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Step 1: read the screenshot and pre-fill the form. Nothing is recorded yet."""
    rel, _ = relationship_for(db, user, rel_id)
    limit = int(settings.max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb:g} MB")
    if not data:
        raise HTTPException(400, "Empty file")
    if file.content_type and not (file.content_type.startswith("image/")
                                  or file.content_type == "application/octet-stream"):
        raise HTTPException(415, "Upload an image (JPG, PNG, WEBP or HEIC)")
    result = await run_in_threadpool(claim_svc.scan_screenshot, db, rel, user, data, file.filename)
    db.commit()
    return result


@router.post("/relationships/{rel_id}/claims", response_model=ClaimOut, status_code=201)
def create_claim(rel_id: int, data: ClaimIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Step 2: submit the checked details. The recipient is asked to confirm."""
    rel, _ = relationship_for(db, user, rel_id)
    claim = claim_svc.create_claim(
        db, rel, user, amount=data.amount, currency_code=data.currency,
        sender_txn_id=data.sender_txn_id, paid_at_local=data.paid_at_local,
        payer_name=data.payer_name, payer_email=data.payer_email, payee_name=data.payee_name,
        paypal_status=data.paypal_status, image_hash=data.image_hash, note=data.note,
        extracted=data.extracted)
    db.commit()
    return claim_out(claim)


def _claim(db: Session, user: User, claim_id: int):
    claim = db.get(PaymentClaim, claim_id)
    if not claim:
        raise HTTPException(404, "Claim not found")
    rel, role = relationship_for(db, user, claim.relationship_id)
    return claim, rel


@router.get("/claims/{claim_id}/paypal")
def claim_paypal(claim_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Receiver only: what their PayPal account shows for this payment (read-only lookup)."""
    claim, _rel = _claim(db, user, claim_id)
    if claim.recipient_user_id != user.id:
        raise HTTPException(403, "Only the person receiving the money can look in their PayPal")
    out = autocheck.inspect_claim(db, user, claim)
    db.commit()
    return out


@router.post("/claims/{claim_id}/respond", response_model=ClaimOut)
def respond(claim_id: int, data: ClaimRespondIn, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    claim, rel = _claim(db, user, claim_id)
    verified_payer = claim.payer_paypal_email or claim.payer_paypal_id
    if (data.response != "not_received" and verified_payer and not data.confirm_without_paypal
            and claim.state == "pending_confirmation" and user.id == claim.recipient_user_id
            and autocheck.enabled_for(user)):
        # never take the payer's word for the amount when we can read the receiver's PayPal
        res = autocheck.check_receiver(db, user, only_claim_id=claim.id)
        db.commit()
        if res["confirmed"]:
            db.refresh(claim)
            return claim_out(claim)
        if res["error"]:
            raise HTTPException(409, f"PAYPAL_CHECK: Couldn't check PayPal: {res['error']}")
        raise HTTPException(409, "PAYPAL_CHECK: Your PayPal account doesn't show this payment from "
                                 f"{verified_payer} yet. PayPal can take a few minutes to list it. "
                                 "Try again shortly, or confirm without PayPal.")
    claim_svc.respond(db, claim, rel, user, response=data.response,
                      received_amount=data.received_amount,
                      received_currency=data.received_currency,
                      recipient_txn_id=data.recipient_txn_id,
                      payer_name_seen=data.payer_name_seen, manual_rate=data.manual_rate)
    db.commit()
    return claim_out(claim)


@router.post("/claims/{claim_id}/resolve", response_model=ClaimOut)
def resolve(claim_id: int, data: ClaimResolveIn, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    claim, rel = _claim(db, user, claim_id)
    claim_svc.resolve(db, claim, rel, user, action=data.action, amount=data.amount, note=data.note)
    db.commit()
    return claim_out(claim)


@router.post("/claims/{claim_id}/reverse", response_model=ClaimOut)
def reverse_claim(claim_id: int, data: ReasonIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    claim, rel = _claim(db, user, claim_id)
    claim_svc.reverse(db, claim, rel, user, data.reason)
    db.commit()
    return claim_out(claim)


@router.get("/claims/{claim_id}/image")
def claim_image(claim_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Screenshots are private: only the two parties of the record can see them."""
    claim, _ = _claim(db, user, claim_id)
    if not claim.image_path or not Path(claim.image_path).exists():
        raise HTTPException(404, "No screenshot for this claim")
    return FileResponse(claim.image_path)
