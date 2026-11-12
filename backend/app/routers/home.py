"""Dashboard, review centre, invites and notifications for the logged-in user."""

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.timeutil import utcnow
from app.models import (
    Business, Contact, Dispute, LedgerEntry, LinkInvite, Notification, PaymentClaim, Relationship,
    User,
)
from app.routers.auth import current_user
from app.schemas import InviteOut, NotificationOut
from app.core import khataz_id as kid
from app.schemas import PublicUserOut
from app.services import elastic
from app.services import ledger, links
from app.services.common import audit, notify
from app.services.views import claim_out, summary

router = APIRouter(prefix="/api", tags=["home"])


def _my_relationships(db: Session, user: User) -> list[Relationship]:
    owned = db.scalars(select(Relationship).join(Business).where(
        Business.owner_id == user.id, Relationship.archived_at.is_(None))).all()
    shared = db.scalars(select(Relationship).join(Contact).where(
        Contact.linked_user_id == user.id, Relationship.archived_at.is_(None))).all()
    return list(owned) + [r for r in shared if r not in owned]


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Money Owed to Me / Money I Owe, grouped by business, with totals per currency."""
    ledger.auto_accept_expired(db)
    businesses = db.scalars(select(Business).where(Business.owner_id == user.id)
                            .order_by(Business.name)).all()
    sections = {"owed_to_me": defaultdict(list), "i_owe": defaultdict(list)}
    totals = {"owed_to_me": defaultdict(Decimal), "i_owe": defaultdict(Decimal)}
    for rel in _my_relationships(db, user):
        s = summary(db, rel, user)
        # a record sits where its money stands now (a customer I now owe is under "Money I owe")
        sections[s.direction][(s.business_id, s.business_name, s.role)].append(s)
        totals[s.direction][s.currency] += s.amount

    def section(key):
        groups = []
        for b in businesses:  # own businesses always listed, even if empty
            items = sections[key].pop((b.id, b.name, "owner"), [])
            groups.append({"business_id": b.id, "business_name": b.name, "shared": False,
                           "items": items})
        for (bid, bname, _), items in sorted(sections[key].items(), key=lambda kv: kv[0][1]):
            groups.append({"business_id": bid, "business_name": bname, "shared": True,
                           "items": items})
        return {"groups": groups,
                "totals": {c: f"{v:.2f}" for c, v in sorted(totals[key].items())}}

    counts = review_counts(db, user)
    return {"user": {"id": user.id, "name": user.name}, "owed_to_me": section("owed_to_me"),
            "i_owe": section("i_owe"), "counts": counts}


def review_counts(db: Session, user: User) -> dict:
    def count(q):
        return db.scalar(select(func.count()).select_from(q.subquery())) or 0

    return {
        "to_confirm": count(select(PaymentClaim.id).where(
            PaymentClaim.recipient_user_id == user.id,
            PaymentClaim.state == "pending_confirmation")),
        "to_review": count(select(PaymentClaim.id).where(
            PaymentClaim.recipient_user_id == user.id,
            PaymentClaim.state.in_(["needs_review", "held"]))),
        "open_disputes": count(select(Dispute.id).join(LedgerEntry, Dispute.entry_id == LedgerEntry.id)
                               .join(Relationship).join(Business)
                               .where(Business.owner_id == user.id, Dispute.status == "open")),
        "entries_to_confirm": count(select(LedgerEntry.id).join(Relationship).join(Business).where(
            Business.owner_id == user.id, LedgerEntry.status == "pending")),
        "entries_to_accept": count(select(LedgerEntry.id).join(Relationship).join(Contact).where(
            Contact.linked_user_id == user.id, LedgerEntry.status == "active",
            LedgerEntry.confirmation == "unconfirmed")),
        "invites": count(select(LinkInvite.id).where(
            links.invites_for(user), LinkInvite.status == "pending")),
        "unread": count(select(Notification.id).where(Notification.user_id == user.id,
                                                      Notification.read.is_(False))),
    }


@router.get("/review")
def review(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everything waiting for this user's decision."""
    ledger.auto_accept_expired(db)
    def claims(states):
        rows = db.scalars(select(PaymentClaim).where(PaymentClaim.recipient_user_id == user.id,
                                                     PaymentClaim.state.in_(states))
                          .order_by(PaymentClaim.created_at)).all()
        return [{"claim": claim_out(c), "relationship": summary(db, db.get(Relationship, c.relationship_id), user)}
                for c in rows]

    disputes = db.scalars(select(Dispute).join(LedgerEntry, Dispute.entry_id == LedgerEntry.id)
                          .join(Relationship).join(Business)
                          .where(Business.owner_id == user.id, Dispute.status == "open")).all()
    to_accept = db.scalars(select(LedgerEntry).join(Relationship).join(Contact).where(
        Contact.linked_user_id == user.id, LedgerEntry.status == "active",
        LedgerEntry.confirmation == "unconfirmed")).all()
    to_confirm = db.scalars(select(LedgerEntry).join(Relationship).join(Business).where(
        Business.owner_id == user.id, LedgerEntry.status == "pending")
        .order_by(LedgerEntry.created_at)).all()
    mine = db.scalars(select(PaymentClaim).where(
        PaymentClaim.submitted_by == user.id, PaymentClaim.recipient_user_id != user.id,
        PaymentClaim.state.in_(["pending_confirmation", "needs_review", "held"]))).all()

    def rel_of(rel_id):
        return summary(db, db.get(Relationship, rel_id), user)

    return {
        "to_confirm": claims(["pending_confirmation"]),
        "to_review": claims(["needs_review", "held"]),
        "disputes": [{"id": d.id, "reason": d.reason, "entry_id": d.entry_id,
                      "created_at": d.created_at, "relationship": rel_of(
                          db.get(LedgerEntry, d.entry_id).relationship_id)} for d in disputes],
        "entries_to_accept": [{"id": e.id, "type": e.type, "amount": f"{e.amount:.2f}",
                               "currency": e.currency, "description": e.description,
                               "cancel_until": e.cancel_until,
                               "relationship": rel_of(e.relationship_id)} for e in to_accept],
        "entries_to_confirm": [{"id": e.id, "type": e.type, "amount": f"{e.amount:.2f}",
                                "currency": e.currency, "description": e.description,
                                "relationship": rel_of(e.relationship_id)} for e in to_confirm],
        "my_pending_claims": [{"claim": claim_out(c), "relationship": rel_of(c.relationship_id)}
                              for c in mine],
    }


# ---------------------------------------------------------------- invites
@router.get("/invites", response_model=list[InviteOut])
def my_invites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(LinkInvite).where(
        links.invites_for(user), LinkInvite.status == "pending")).all()
    out = []
    for inv in rows:
        c = inv.contact
        rel = db.scalar(select(Relationship).where(Relationship.contact_id == c.id))
        inviter = db.get(User, inv.created_by)
        out.append(InviteOut(id=inv.id, contact_name=c.name, business_name=c.business.name,
                             invited_by=f"{inviter.name} (@{inviter.khataz_id})",
                             invited_email=None if inv.invited_user_id else inv.invited_email,
                             side=rel.side if rel else None, status=inv.status,
                             created_at=inv.created_at))
    return out


def _invite_for(db: Session, user: User, invite_id: int) -> LinkInvite:
    inv = db.get(LinkInvite, invite_id)
    mine = inv and (inv.invited_user_id == user.id or inv.invited_email.lower() == user.email.lower())
    if not mine or inv.status != "pending":
        raise HTTPException(404, "Invite not found")
    return inv


@router.post("/invites/{invite_id}/accept")
def accept_invite(invite_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = _invite_for(db, user, invite_id)
    c = inv.contact
    if c.linked_user_id:
        raise HTTPException(409, "This record is already linked to an account")
    if c.business.owner_id == user.id:
        raise HTTPException(400, "You can't link to your own business")
    c.linked_user_id = user.id
    inv.status, inv.responded_at = "accepted", utcnow()
    rel_ids = db.scalars(select(Relationship.id).where(Relationship.contact_id == c.id)).all()
    for rid in rel_ids:
        audit(db, user, "contact.linked", "contact", c.id, rid, after={"linked_user_id": user.id})
    notify(db, inv.created_by, "invite_accepted",
           f"{user.name} confirmed they are “{c.name}”. You now share this record.",
           rel_ids[0] if rel_ids else None)
    db.commit()
    return {"status": "accepted", "relationship_ids": rel_ids}


@router.post("/invites/{invite_id}/decline")
def decline_invite(invite_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = _invite_for(db, user, invite_id)
    inv.status, inv.responded_at = "declined", utcnow()
    notify(db, inv.created_by, "invite_declined",
           f"{user.name} declined to link the record “{inv.contact.name}”.")
    db.commit()
    return {"status": "declined"}


@router.post("/invites/{invite_id}/cancel")
def cancel_invite(invite_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Undo: the owner withdraws an invite that hasn't been answered yet."""
    inv = db.get(LinkInvite, invite_id)
    if not inv or inv.contact.business.owner_id != user.id:
        raise HTTPException(404, "Invite not found")
    if inv.status != "pending":
        raise HTTPException(409, f"This invite was already {inv.status}, so it can't be undone")
    inv.status, inv.responded_at = "cancelled", utcnow()
    for rid in db.scalars(select(Relationship.id).where(Relationship.contact_id == inv.contact_id)):
        audit(db, user, "contact.invite_cancelled", "contact", inv.contact_id, rid,
              before={"invite": "pending"}, after={"invite": "cancelled"})
    target_id = inv.invited_user_id or db.scalar(
        select(User.id).where(func.lower(User.email) == inv.invited_email.lower()))
    notify(db, target_id, "invite_cancelled",
           f"{user.name} withdrew the invite to share the record “{inv.contact.name}”.")
    db.commit()
    return {"status": "cancelled"}


# ---------------------------------------------------------------- notifications
@router.get("/notifications", response_model=list[NotificationOut])
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.created_at.desc(), Notification.id.desc())
                      .limit(100)).all()


@router.post("/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- search
@router.get("/search")
def search(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Your own records by name, business or Khataz ID; other Khataz users ONLY by Khataz ID.
    (Searching everyone by name would let anyone list who uses Khataz.)"""
    text = q.strip()
    if len(text) < 2:
        return {"query": text, "engine": "basic", "records": [], "people": []}
    needle = text.lstrip("@#").lower()

    rels = _my_relationships(db, user)
    sums = {rel.id: summary(db, rel, user) for rel in rels}
    ranked = elastic.search(db, user, text, rels, sums)  # None = Elasticsearch off or down
    if ranked is not None:
        engine = "elastic"
        records = [sums[rid].model_dump() | {"match": snippet} for rid, snippet in ranked if rid in sums]
    else:
        engine = "basic"
        records = []
        for rel in rels:
            s = sums[rel.id]
            hay = [rel.contact.name, rel.contact.company, rel.business.name, s.other_khataz_id, s.local_id]
            if any(h and needle in h.lower() for h in hay):
                records.append(s)
        records.sort(key=lambda r: (not r.other_party.lower().startswith(needle), r.other_party.lower()))
        records = [r.model_dump() | {"match": None} for r in records]

    people = []
    if len(needle) >= 3:
        found = db.scalars(select(User).where(User.khataz_id.startswith(needle), User.id != user.id)
                           .order_by(func.length(User.khataz_id), User.khataz_id).limit(8)).all()
        for u in found:
            in_records = [r["id"] for r in records if r["other_khataz_id"] == u.khataz_id]
            people.append({**PublicUserOut.model_validate(u).model_dump(), "record_ids": in_records})
    return {"query": text, "engine": engine, "records": records[:30], "people": people}
