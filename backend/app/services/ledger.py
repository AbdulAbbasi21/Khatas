"""Ledger rules. The only code that creates ledger entries."""

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.money import money
from app.core.timeutil import utcnow
from app.models import Dispute, LedgerEntry, Relationship, User
from app.services.common import audit, notify, other_party_id, role_in, snapshot

ENTRY_FIELDS = ["type", "amount", "delta", "currency", "description", "occurred_at", "status",
                "confirmation", "source"]
COUNTED = ("active",)  # pending, rejected, disputed and voided entries don't change the balance
INCREASES = {"credit"}                 # raise the debt
DECREASES = {"payment", "goods"}       # lower it: money paid, or goods/services given instead


def balance(db: Session, rel: Relationship) -> dict:
    def total(*conds):
        q = select(func.coalesce(func.sum(LedgerEntry.delta), 0)).where(
            LedgerEntry.relationship_id == rel.id, *conds)
        return money(db.scalar(q) or 0)

    return {
        "balance": total(LedgerEntry.status.in_(COUNTED)),
        "disputed": total(LedgerEntry.status == "disputed"),
        "pending": total(LedgerEntry.status == "pending"),
        "unconfirmed": total(LedgerEntry.status == "active",
                             LedgerEntry.confirmation == "unconfirmed"),
        "credited": total(LedgerEntry.status.in_(COUNTED), LedgerEntry.delta > 0),
        "paid": -total(LedgerEntry.status.in_(COUNTED), LedgerEntry.delta < 0),
    }


def add_entry(db: Session, rel: Relationship, actor: User, type_: str, amount,
              description: str | None = None, occurred_at: datetime | None = None,
              increase: bool | None = None, source: str = "manual",
              claim_id: int | None = None) -> LedgerEntry:
    """credit raises the debt; payment and goods lower it; adjustment goes either way.

    The business owner's entries count at once (the other side can accept or dispute them).
    Entries the OTHER side records are only proposals: status 'pending' until the owner
    confirms them, so nobody can change someone else's book on their own."""
    if type_ not in INCREASES | DECREASES | {"adjustment"}:
        raise HTTPException(400, "Entry type must be credit, payment, goods or adjustment")
    amt = money(amount)
    if amt <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    if type_ == "adjustment" and increase is None:
        raise HTTPException(400, "An adjustment must say whether it increases or decreases the debt")
    sign = 1 if type_ in INCREASES or (type_ == "adjustment" and increase) else -1
    proposed = source == "manual" and role_in(rel, actor) == "counterparty"

    status = "active"
    if source == "claim":
        confirmation = "accepted"  # the recipient already confirmed it
    elif proposed:
        status, confirmation = "pending", "unconfirmed"  # waits for the owner
    elif rel.contact.linked_user_id:
        confirmation = "unconfirmed"  # the other side should accept or dispute it
    else:
        confirmation = "not_required"

    entry = LedgerEntry(relationship_id=rel.id, type=type_, amount=amt, delta=amt * sign,
                        currency=rel.currency, description=(description or "").strip() or None,
                        occurred_at=occurred_at or utcnow(), status=status,
                        confirmation=confirmation, source=source, claim_id=claim_id,
                        created_by=actor.id)
    db.add(entry)
    db.flush()
    audit(db, actor, f"entry.{type_}" + (".proposed" if proposed else ""), "ledger_entry",
          entry.id, rel.id, after=snapshot(entry, ENTRY_FIELDS))
    what = {"credit": "a credit", "payment": "a payment", "goods": "goods/services given",
            "adjustment": "a correction"}[type_]
    detail = f" ({entry.description})" if entry.description else ""
    if proposed:
        notify(db, rel.business.owner_id, "entry_to_confirm",
               f"{actor.name} recorded {what} of {amt} {rel.currency}{detail}. "
               "It changes the balance only after you confirm it.", rel.id)
    elif source == "manual":
        hint = (f" If it's wrong, you can cancel it within {settings.entry_cancel_hours} hours."
                if confirmation == "unconfirmed" else "")
        notify(db, other_party_id(rel, actor), "entry_added",
               f"{actor.name} recorded {what} of {amt} {rel.currency}{detail}.{hint}", rel.id)
    return entry


def confirm_proposed(db: Session, entry: LedgerEntry, rel: Relationship, actor: User):
    """The owner agrees that what the other side recorded really happened."""
    if role_in(rel, actor) != "owner":
        raise HTTPException(403, "Only the business owner can confirm this")
    if entry.status != "pending":
        raise HTTPException(409, "This entry isn't waiting for confirmation")
    entry.status, entry.confirmation = "active", "accepted"
    audit(db, actor, "entry.confirmed", "ledger_entry", entry.id, rel.id,
          before={"status": "pending"}, after={"status": "active"})
    notify(db, entry.created_by, "entry_confirmed",
           f"{actor.name} confirmed your entry of {entry.amount} {entry.currency}. "
           "The balance has been updated.", rel.id)


def reject_proposed(db: Session, entry: LedgerEntry, rel: Relationship, actor: User,
                    reason: str):
    if role_in(rel, actor) != "owner":
        raise HTTPException(403, "Only the business owner can reject this")
    if entry.status != "pending":
        raise HTTPException(409, "This entry isn't waiting for confirmation")
    if not (reason or "").strip():
        raise HTTPException(400, "Say why you reject it")
    entry.status = "rejected"
    audit(db, actor, "entry.rejected", "ledger_entry", entry.id, rel.id,
          before={"status": "pending"}, after={"status": "rejected"}, reason=reason)
    notify(db, entry.created_by, "entry_rejected",
           f"{actor.name} rejected your entry of {entry.amount} {entry.currency}: {reason}",
           rel.id)


def reverse_entry(db: Session, entry: LedgerEntry, rel: Relationship, actor: User,
                  reason: str) -> LedgerEntry:
    if entry.type == "reversal":
        raise HTTPException(400, "A reversal can't be reversed")
    if entry.reversed_by_entry_id:
        raise HTTPException(409, "This entry was already reversed")
    if entry.status != "active":
        raise HTTPException(409, "Only active entries can be reversed; resolve the dispute first")
    if not (reason or "").strip():
        raise HTTPException(400, "Give a reason for the reversal")

    rev = LedgerEntry(relationship_id=rel.id, type="reversal", amount=entry.amount,
                      delta=-entry.delta, currency=entry.currency,
                      description=f"Reversal of entry #{entry.id}: {reason.strip()}",
                      occurred_at=utcnow(), confirmation="not_required", source=entry.source,
                      claim_id=entry.claim_id, reverses_entry_id=entry.id, created_by=actor.id)
    db.add(rev)
    db.flush()
    before = snapshot(entry, ENTRY_FIELDS)
    entry.reversed_by_entry_id = rev.id
    audit(db, actor, "entry.reversed", "ledger_entry", entry.id, rel.id, before=before,
          after={"reversed_by_entry_id": rev.id}, reason=reason)
    notify(db, other_party_id(rel, actor), "entry_reversed",
           f"{actor.name} reversed entry #{entry.id} ({entry.amount} {entry.currency}): {reason}",
           rel.id)
    return rev


def _counterparty_check(entry: LedgerEntry, rel: Relationship, actor: User):
    if role_in(rel, actor) != "counterparty":
        raise HTTPException(403, "Only the other party can accept or dispute an entry")
    if entry.created_by == actor.id:
        raise HTTPException(400, "You can't accept or dispute your own entry")
    if entry.type == "reversal" or entry.status != "active":
        raise HTTPException(409, "This entry can't be changed")


def auto_accept_expired(db: Session) -> int:
    """Entries the other side didn't cancel in time become final ("auto_accepted")."""
    cutoff = utcnow() - timedelta(hours=settings.entry_cancel_hours)
    r = db.execute(update(LedgerEntry).where(
        LedgerEntry.confirmation == "unconfirmed", LedgerEntry.status == "active",
        LedgerEntry.created_at < cutoff).values(confirmation="auto_accepted"))
    if r.rowcount:
        db.commit()
    return r.rowcount or 0


def _within_window(entry: LedgerEntry):
    if entry.confirmation != "unconfirmed" or not entry.cancel_until or utcnow() > entry.cancel_until:
        raise HTTPException(409, f"The {settings.entry_cancel_hours}-hour window to answer this entry "
                                 "has passed; it's final now.")


def cancel_entry(db: Session, entry: LedgerEntry, rel: Relationship, actor: User, reason: str):
    """The other side says an entry is wrong: within the window it is cancelled at once."""
    _counterparty_check(entry, rel, actor)
    _within_window(entry)
    if not (reason or "").strip():
        raise HTTPException(400, "Say why the entry is wrong")
    entry.status, entry.confirmation = "cancelled", "cancelled"
    audit(db, actor, "entry.cancelled", "ledger_entry", entry.id, rel.id,
          before={"status": "active"}, after={"status": "cancelled"}, reason=reason.strip())
    what = {"credit": "Add money", "payment": "Subtract money", "goods": "Goods", "adjustment": "Update money"}
    detail = f" ({entry.description})" if entry.description else ""
    notify(db, rel.business.owner_id, "entry_cancelled",
           f"{actor.name} cancelled your entry: {what.get(entry.type, entry.type)} {entry.amount} "
           f"{entry.currency}{detail}. Reason: {reason.strip()}", rel.id)


def accept_entry(db: Session, entry: LedgerEntry, rel: Relationship, actor: User):
    _counterparty_check(entry, rel, actor)
    _within_window(entry)
    entry.confirmation = "accepted"
    audit(db, actor, "entry.accepted", "ledger_entry", entry.id, rel.id)
    notify(db, rel.business.owner_id, "entry_accepted",
           f"{actor.name} accepted entry #{entry.id} ({entry.amount} {entry.currency})", rel.id)


def dispute_entry(db: Session, entry: LedgerEntry, rel: Relationship, actor: User,
                  reason: str) -> Dispute:
    _counterparty_check(entry, rel, actor)
    _within_window(entry)
    if not (reason or "").strip():
        raise HTTPException(400, "Say why you dispute this entry")
    d = Dispute(entry_id=entry.id, opened_by=actor.id, reason=reason.strip())
    db.add(d)
    entry.status = "disputed"
    db.flush()
    audit(db, actor, "entry.disputed", "ledger_entry", entry.id, rel.id,
          before={"status": "active"}, after={"status": "disputed", "dispute_id": d.id},
          reason=reason)
    notify(db, rel.business.owner_id, "entry_disputed",
           f"{actor.name} disputed entry #{entry.id} ({entry.amount} {entry.currency}): {reason}",
           rel.id)
    return d


def resolve_dispute(db: Session, dispute: Dispute, entry: LedgerEntry, rel: Relationship,
                    actor: User, resolution: str, note: str | None):
    if role_in(rel, actor) != "owner":
        raise HTTPException(403, "Only the business owner can resolve a dispute")
    if dispute.status != "open":
        raise HTTPException(409, "Dispute already resolved")
    if resolution not in {"kept", "voided"}:
        raise HTTPException(400, "Resolution must be 'kept' or 'voided'")
    dispute.status, dispute.resolution = "resolved", resolution
    dispute.resolution_note, dispute.resolved_by, dispute.resolved_at = note, actor.id, utcnow()
    if resolution == "kept":
        entry.status, entry.confirmation = "active", "upheld"
    else:
        entry.status = "voided"
    audit(db, actor, f"dispute.{resolution}", "dispute", dispute.id, rel.id,
          after={"entry_id": entry.id, "entry_status": entry.status}, reason=note)
    notify(db, dispute.opened_by, "dispute_resolved",
           f"{actor.name} {'kept' if resolution == 'kept' else 'cancelled'} entry #{entry.id}"
           + (f": {note}" if note else ""), rel.id)


def summary_amount(value: Decimal) -> str:
    return str(money(value))
