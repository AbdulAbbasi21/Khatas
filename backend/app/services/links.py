"""Inviting a contact to link their Khataz account (by email or by Khataz ID)."""

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from html import escape

from app.core import khataz_id as kid
from app.core.config import settings
from app.core.email import email_enabled, send_email
from app.models import Contact, LinkInvite, User
from app.services.common import audit, notify


def find_by_khataz_id(db: Session, value: str) -> User | None:
    return db.scalar(select(User).where(User.khataz_id == kid.normalize(value)))


def invite(db: Session, contact: Contact, actor: User, rel_id: int | None, *,
           email: str | None = None, khataz_id: str | None = None) -> tuple[LinkInvite, User | None]:
    """The invited person must still accept from their own account; nothing links automatically."""
    if contact.linked_user_id:
        raise HTTPException(409, "This contact is already linked to an account")
    target = None
    if khataz_id:
        target = find_by_khataz_id(db, khataz_id)
        if not target:
            raise HTTPException(404, f"Nobody on Khataz has the ID @{kid.normalize(khataz_id)}")
        email = target.email
    else:
        email = email.lower()
        target = db.scalar(select(User).where(func.lower(User.email) == email))
    if target and target.id == actor.id or email == actor.email.lower():
        raise HTTPException(400, "You can't invite yourself")
    if db.scalar(select(LinkInvite).where(LinkInvite.contact_id == contact.id,
                                          LinkInvite.status == "pending")):
        raise HTTPException(409, "An invite is already waiting for an answer")

    inv = LinkInvite(contact_id=contact.id, invited_email=email, created_by=actor.id,
                     invited_user_id=target.id if khataz_id else None)
    db.add(inv)
    db.flush()
    if target:
        notify(db, target.id, "link_invite",
               f"{actor.name} ({contact.business.name}) asked you to confirm a shared record as "
               f"“{contact.name}”.")
    audit(db, actor, "contact.invited", "contact", contact.id, rel_id,
          after={"khataz_id": target.khataz_id} if khataz_id else {"email": email})
    return inv, target


def invites_for(user: User):
    """Invites addressed to this user, by Khataz ID or by email."""
    return or_(LinkInvite.invited_user_id == user.id,
               func.lower(LinkInvite.invited_email) == user.email.lower())


def invite_label(inv: LinkInvite | None, db: Session) -> str | None:
    """How the owner sees who was invited: '@khataz_id' (email stays private) or the email."""
    if not inv:
        return None
    if inv.invited_user_id:
        u = db.get(User, inv.invited_user_id)
        return f"@{u.khataz_id}" if u else None
    return inv.invited_email


def send_invite_email(inv: LinkInvite, contact: Contact, actor: User, has_account: bool) -> dict:
    """Email the invite. People without an account get a sign-up link with their email filled in."""
    biz = contact.business.name
    if has_account:
        link = f"{settings.app_url}/notifications"
        action = "Log in to Khataz and accept the invite under Notifications."
    else:
        from urllib.parse import quote
        link = f"{settings.app_url}/register?email={quote(inv.invited_email)}"
        action = "Create your free Khataz account with this email address, then accept the invite."
    subject = f"{actor.name} invited you to share your record on Khataz"
    text = (f"Hi {contact.name},\n\n{actor.name} (@{actor.khataz_id}) keeps a record with you for "
            f"{biz} on Khataz, a shared credit ledger. Once you join, you both see the same balance, "
            f"can confirm or dispute entries, and send payment receipts.\n\n{action}\n{link}\n\n"
            "If you don't know this person, ignore this email. Nothing is shared until you accept.\n\n"
            "Khataz records payments. It never moves money.")
    html = f"""<div style="font-family:Helvetica,Arial,sans-serif;max-width:520px;margin:auto;color:#111">
  <div style="background:#003087;color:#fff;padding:20px 24px;border-radius:12px 12px 0 0;font-size:22px;font-weight:800">Khata<span style="color:#009cde">z</span></div>
  <div style="border:1px solid #e3e7ee;border-top:0;padding:24px;border-radius:0 0 12px 12px">
    <p>Hi {escape(contact.name)},</p>
    <p><b>{escape(actor.name)}</b> (@{escape(actor.khataz_id)}) keeps a record with you for <b>{escape(biz)}</b> on Khataz, a shared credit ledger.
       Once you join, you both see the same balance, can confirm or dispute entries, and send payment receipts.</p>
    <p>{escape(action)}</p>
    <p style="margin:28px 0"><a href="{escape(link)}" style="background:#0070e0;color:#fff;padding:12px 24px;border-radius:999px;text-decoration:none;font-weight:700">{"Open Khataz" if has_account else "Join Khataz"}</a></p>
    <p style="color:#5c6470;font-size:13px">If you don't know this person, ignore this email. Nothing is shared until you accept.<br>Khataz records payments. It never moves money.</p>
  </div></div>"""
    sent = send_email(inv.invited_email, subject, text, html)
    return {"email_sent": sent, "email_configured": email_enabled(), "link": link}
