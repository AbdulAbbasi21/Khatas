"""
Database tables. Rules worth knowing:
- Balances are never stored; they are summed from ledger_entries.delta.
- Ledger entries are never edited or deleted; corrections are reversal entries.
- Money columns are Numeric (Decimal), never float. Times are UTC.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.sql.expression import false as sa_false, true as sa_true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutil import utcnow

Money = Numeric(18, 2)
TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    khataz_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # public handle
    name: Mapped[str] = mapped_column(String(120))
    avatar_path: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    default_currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    country: Mapped[str | None] = mapped_column(String(2))
    paypal_email: Mapped[str | None] = mapped_column(String(255))
    can_receive_paypal: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    # set by "Log in with PayPal": PayPal itself vouches for these
    paypal_user_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    paypal_payer_id: Mapped[str | None] = mapped_column(String(32))
    paypal_verified_email: Mapped[str | None] = mapped_column(String(255))
    paypal_verified_name: Mapped[str | None] = mapped_column(String(160))
    paypal_account_verified: Mapped[bool | None] = mapped_column(Boolean)
    paypal_connected_at: Mapped[datetime | None] = mapped_column(TS)
    # automatic payment check: the receiver's own PayPal REST app (secret stored encrypted)
    paypal_api_client_id: Mapped[str | None] = mapped_column(String(255))
    paypal_api_secret_enc: Mapped[str | None] = mapped_column(Text)
    paypal_api_checked_at: Mapped[datetime | None] = mapped_column(TS)
    paypal_api_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    @property
    def has_avatar(self) -> bool:
        return bool(self.avatar_path)

    @property
    def avatar_version(self) -> str | None:
        """Changes whenever the picture changes, so browsers don't show a cached old one."""
        return self.avatar_path.rsplit("-", 1)[-1].split(".")[0] if self.avatar_path else None


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(80))
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    owner: Mapped[User] = relationship()


class Contact(Base):
    """A person or business in someone's records. May or may not have a Khataz account.
    local_id = the owner's own ID for this person (e.g. CUST-001), unique within the business,
    so a person can be identified before their Khataz ID is known. Only the owner sees it."""
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("business_id", "local_key", name="uq_contact_local_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    local_id: Mapped[str | None] = mapped_column(String(30))
    local_key: Mapped[str | None] = mapped_column(String(30))  # lowercase, for uniqueness
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    company: Mapped[str | None] = mapped_column(String(160))
    paypal_email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    linked_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    business: Mapped[Business] = relationship()
    linked_user: Mapped[User | None] = relationship()


class Relationship(Base):
    """One ledger between a business and a contact.
    side='receivable': the contact owes the business. side='payable': the business owes the contact.
    A linked contact sees the same record from the other side."""
    __tablename__ = "relationships"
    __table_args__ = (UniqueConstraint("contact_id", "side", name="uq_relationship_contact_side"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    side: Mapped[str] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    # removed from lists (only allowed at zero balance); entries are kept for the record
    archived_at: Mapped[datetime | None] = mapped_column(TS)

    business: Mapped[Business] = relationship()
    contact: Mapped[Contact] = relationship()


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int] = mapped_column(ForeignKey("relationships.id"), index=True)
    type: Mapped[str] = mapped_column(String(12))          # credit | payment | adjustment | reversal
    amount: Mapped[Decimal] = mapped_column(Money)          # always positive
    delta: Mapped[Decimal] = mapped_column(Money)           # + increases the debt, - reduces it
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | disputed | voided
    confirmation: Mapped[str] = mapped_column(String(14), default="not_required")

    @property
    def cancel_until(self):
        """Until when the other side can cancel this entry (None when it can't)."""
        if self.confirmation != "unconfirmed" or self.status != "active" or not self.created_at:
            return None
        from app.core.config import settings
        from app.core.timeutil import as_utc
        return as_utc(self.created_at) + timedelta(hours=settings.entry_cancel_hours)
    # not_required | unconfirmed | accepted | upheld
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | claim
    claim_id: Mapped[int | None] = mapped_column(Integer)
    reverses_entry_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"))
    reversed_by_entry_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class PaymentClaim(Base):
    """'I paid you' - a claim backed by a screenshot. Only the recipient's confirmation
    (plus matching amount and payer) turns it into a payment entry."""
    __tablename__ = "payment_claims"
    __table_args__ = (
        UniqueConstraint("recipient_user_id", "sender_txn_id", name="uq_claim_txn"),
        UniqueConstraint("recipient_user_id", "image_hash", name="uq_claim_image"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int] = mapped_column(ForeignKey("relationships.id"), index=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    image_hash: Mapped[str | None] = mapped_column(String(64))
    image_path: Mapped[str | None] = mapped_column(String(255))
    sender_txn_id: Mapped[str | None] = mapped_column(String(32))
    recipient_txn_id: Mapped[str | None] = mapped_column(String(32))
    claimed_amount: Mapped[Decimal] = mapped_column(Money)
    claimed_currency: Mapped[str] = mapped_column(String(3))
    received_amount: Mapped[Decimal | None] = mapped_column(Money)
    received_currency: Mapped[str | None] = mapped_column(String(3))
    converted_amount: Mapped[Decimal | None] = mapped_column(Money)  # in the ledger's currency
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    fx_source: Mapped[str | None] = mapped_column(String(80))
    payer_name: Mapped[str | None] = mapped_column(String(160))
    payer_email: Mapped[str | None] = mapped_column(String(255))
    payee_name: Mapped[str | None] = mapped_column(String(160))   # recipient as shown on screenshot
    paypal_status: Mapped[str | None] = mapped_column(String(40))
    # the payer's PayPal account as verified by "Log in with PayPal" when the claim was made
    payer_paypal_email: Mapped[str | None] = mapped_column(String(255))
    payer_paypal_id: Mapped[str | None] = mapped_column(String(32))
    auto_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    paid_at: Mapped[datetime | None] = mapped_column(TS)
    state: Mapped[str] = mapped_column(String(24), default="pending_confirmation")
    # pending_confirmation | needs_review | held | allocated | rejected | disputed | reversed
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    allocated_entry_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id"))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    recipient: Mapped[User] = relationship(foreign_keys=[recipient_user_id])


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("ledger_entries.id"), index=True)
    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | resolved
    resolution: Mapped[str | None] = mapped_column(String(10))       # kept | voided
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)


class LinkInvite(Base):
    """Owner asks a registered user to confirm they are this contact. Never auto-linked."""
    __tablename__ = "link_invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    invited_email: Mapped[str] = mapped_column(String(255), index=True)
    invited_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|accepted|declined
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(TS)

    contact: Mapped[Contact] = relationship()


class Conversation(Base):
    """A private chat between two Khataz users (user_a_id < user_b_id)."""
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_a_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_b_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    def other(self, user_id: int) -> int:
        return self.user_b_id if user_id == self.user_a_id else self.user_a_id


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    relationship_id: Mapped[int | None] = mapped_column(ForeignKey("relationships.id"))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    relationship_id: Mapped[int | None] = mapped_column(ForeignKey("relationships.id"), index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    actor: Mapped[User | None] = relationship()


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("date", "base", "quote", name="uq_fx_rate"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    source: Mapped[str] = mapped_column(String(80))
