"""Audit log, notifications and access checks shared by every service."""

from datetime import date, datetime
from decimal import Decimal

import threading

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.timeutil import iso
from app.models import AuditLog, Business, Notification, Relationship, User


# ---------------------------------------------------------------- audit
def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def snapshot(obj, fields: list[str]) -> dict:
    return {f: _plain(getattr(obj, f)) for f in fields}


def audit(db: Session, actor: User | None, action: str, entity: str, entity_id: int | None,
          relationship_id: int | None = None, before: dict | None = None,
          after: dict | None = None, reason: str | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity=entity,
                    entity_id=entity_id, relationship_id=relationship_id,
                    before=_plain(before), after=_plain(after), reason=reason))


# ---------------------------------------------------------------- notifications
NO_EMAIL = {"link_invite"}  # invites send their own email


def notify(db: Session, user_id: int | None, kind: str, message: str,
           relationship_id: int | None = None) -> None:
    if not user_id:
        return
    db.add(Notification(user_id=user_id, kind=kind, message=message,
                        relationship_id=relationship_id))
    from app.core.email import email_enabled
    if kind in NO_EMAIL or not email_enabled():
        return
    user = db.get(User, user_id)
    if user and user.email_notifications:
        # sent only if the change is saved (see _send_queued_emails)
        db.info.setdefault("emails", []).append((user.email, user.name, message, relationship_id))


def _email_body(name: str, message: str, relationship_id: int | None) -> tuple[str, str]:
    from app.core.config import settings
    link = f"{settings.app_url}/records/{relationship_id}" if relationship_id else f"{settings.app_url}/notifications"
    text = (f"Hi {name},\n\n{message}\n\nOpen Khataz: {link}\n\n"
            f"Turn these emails off in Khataz under Settings.\nKhataz records payments. It never moves money.")
    html = (f"<div style=\"font-family:Arial,sans-serif;max-width:520px\">"
            f"<p style=\"font-size:20px;font-weight:800;color:#003087\">Khataz</p>"
            f"<p>Hi {name},</p><p style=\"font-size:16px\">{message}</p>"
            f"<p><a href=\"{link}\" style=\"background:#0070e0;color:#fff;padding:10px 18px;"
            f"border-radius:20px;text-decoration:none;font-weight:700\">Open Khataz</a></p>"
            f"<p style=\"color:#6c7378;font-size:12px\">Turn these emails off in Khataz under Settings.</p></div>")
    return text, html


@event.listens_for(Session, "after_commit")
def _send_queued_emails(session):
    queued = session.info.pop("emails", None)
    if not queued:
        return
    from app.core.email import send_email

    def run():
        for to, name, message, rel_id in queued:
            text, html = _email_body(name, message, rel_id)
            subject = message if len(message) <= 70 else message[:67].rsplit(" ", 1)[0] + "…"
            send_email(to, f"Khataz: {subject}", text, html)
    threading.Thread(target=run, daemon=True).start()


@event.listens_for(Session, "after_rollback")
def _drop_queued_emails(session):
    session.info.pop("emails", None)


# ---------------------------------------------------------------- access
def owned_business(db: Session, user: User, business_id: int) -> Business:
    b = db.get(Business, business_id)
    if not b or b.owner_id != user.id:
        raise HTTPException(404, "Business not found")
    return b


def creditor_id(rel: Relationship) -> int | None:
    """The user who is owed money in this relationship (None if they have no account)."""
    return rel.business.owner_id if rel.side == "receivable" else rel.contact.linked_user_id


def debtor_id(rel: Relationship) -> int | None:
    return rel.contact.linked_user_id if rel.side == "receivable" else rel.business.owner_id


def role_in(rel: Relationship, user: User) -> str | None:
    if rel.business.owner_id == user.id:
        return "owner"
    if rel.contact.linked_user_id == user.id:
        return "counterparty"
    return None


def other_party_id(rel: Relationship, user: User) -> int | None:
    return rel.contact.linked_user_id if role_in(rel, user) == "owner" else rel.business.owner_id


def relationship_for(db: Session, user: User, rel_id: int) -> tuple[Relationship, str]:
    rel = db.get(Relationship, rel_id)
    role = role_in(rel, user) if rel else None
    if not role:
        raise HTTPException(404, "Record not found")
    return rel, role


def creditor_name(rel: Relationship) -> str:
    return rel.business.name if rel.side == "receivable" else rel.contact.name


def debtor_name(rel: Relationship) -> str:
    return rel.contact.name if rel.side == "receivable" else rel.business.name
