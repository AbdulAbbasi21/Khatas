"""Build API responses that need joins or the viewer's perspective."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Dispute, LedgerEntry, PaymentClaim, Relationship, User
from app.schemas import ClaimOut, RelationshipSummary
from app.services import ledger
from app.services.claims import REASON_TEXT
from app.services.common import role_in


def perspective(rel: Relationship, role: str) -> str:
    owner_view = "owed_to_me" if rel.side == "receivable" else "i_owe"
    if role == "owner":
        return owner_view
    return "i_owe" if owner_view == "owed_to_me" else "owed_to_me"


def direction(persp: str, balance) -> str:
    """Where the money stands now. A balance below zero means it runs the other way:
    a customer who owes -10 is someone I owe 10."""
    if balance < 0:
        return "i_owe" if persp == "owed_to_me" else "owed_to_me"
    return persp


def pending_actions(db: Session, rel: Relationship, user: User, role: str) -> int:
    n = db.scalar(select(func.count()).select_from(PaymentClaim).where(
        PaymentClaim.relationship_id == rel.id, PaymentClaim.recipient_user_id == user.id,
        PaymentClaim.state.in_(["pending_confirmation", "needs_review", "held"]))) or 0
    if role == "owner":
        n += db.scalar(select(func.count()).select_from(Dispute).join(
            LedgerEntry, Dispute.entry_id == LedgerEntry.id).where(
            LedgerEntry.relationship_id == rel.id, Dispute.status == "open")) or 0
        n += db.scalar(select(func.count()).select_from(LedgerEntry).where(
            LedgerEntry.relationship_id == rel.id, LedgerEntry.status == "pending")) or 0
    else:
        n += db.scalar(select(func.count()).select_from(LedgerEntry).where(
            LedgerEntry.relationship_id == rel.id, LedgerEntry.status == "active",
            LedgerEntry.confirmation == "unconfirmed", LedgerEntry.created_by != user.id)) or 0
    return n


def summary(db: Session, rel: Relationship, user: User) -> RelationshipSummary:
    role = role_in(rel, user)
    b = ledger.balance(db, rel)
    other = rel.contact.linked_user if role == "owner" else rel.business.owner
    return RelationshipSummary(
        id=rel.id, business_id=rel.business_id, business_name=rel.business.name,
        contact_name=rel.contact.name,
        other_party=rel.contact.name if role == "owner" else rel.business.name,
        side=rel.side, perspective=perspective(rel, role), role=role, currency=rel.currency,
        direction=direction(perspective(rel, role), b["balance"]), amount=abs(b["balance"]),
        balance=b["balance"], disputed=b["disputed"], linked=bool(rel.contact.linked_user_id),
        local_id=rel.contact.local_id if role == "owner" else None,
        other_khataz_id=other.khataz_id if other else None,
        other_has_avatar=bool(other and other.avatar_path),
        other_avatar_version=other.avatar_version if other else None,
        pending_actions=pending_actions(db, rel, user, role),
    )


def claim_out(c: PaymentClaim) -> ClaimOut:
    out = ClaimOut.model_validate(c)
    out.has_image = bool(c.image_path)
    out.review_reasons = list(c.review_reasons or [])
    out.review_reason_text = [REASON_TEXT.get(r, r) for r in out.review_reasons]
    r = c.recipient
    from app.services.autocheck import enabled_for
    out.auto_check = bool(r and enabled_for(r) and (c.payer_paypal_email or c.payer_paypal_id))
    return out
