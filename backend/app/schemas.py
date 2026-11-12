"""Request and response shapes. Money is sent as strings ("125.50") to keep it exact."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, field_validator, model_validator,
)

from app.core import khataz_id as kid

from app.core.money import currency as check_currency
from app.core.timeutil import iso, valid_timezone

UTC = Annotated[datetime, PlainSerializer(iso, return_type=str)]
Amount = Annotated[Decimal, PlainSerializer(lambda d: f"{Decimal(d):.2f}", return_type=str)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth / users
class RegisterIn(BaseModel):
    email: EmailStr
    khataz_id: str = Field(description="Public unique handle, e.g. abdul.hadi")
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    timezone: str = "UTC"
    default_currency: str = Field("USD", description="Currency for your books")
    country: str | None = Field(None, min_length=2, max_length=2)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if not valid_timezone(v):
            raise ValueError("Unknown time zone")
        return v

    @field_validator("default_currency")
    @classmethod
    def _cur(cls, v):
        return check_currency(v)

    @field_validator("khataz_id")
    @classmethod
    def _kid(cls, v):
        why = kid.problem(v)
        if why:
            raise ValueError(f"Khataz ID: {why}")
        return kid.normalize(v)


class PublicUserOut(ORM):
    """What anyone on Khataz may see about a user."""
    khataz_id: str
    name: str
    has_avatar: bool
    avatar_version: str | None


class UserOut(ORM):
    id: int
    email: str
    khataz_id: str
    name: str
    has_avatar: bool
    avatar_version: str | None
    timezone: str
    default_currency: str
    country: str | None
    paypal_email: str | None
    can_receive_paypal: bool
    paypal_verified_email: str | None = None
    email_notifications: bool = True
    created_at: UTC


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    timezone: str | None = None
    default_currency: str | None = None
    country: str | None = Field(None, min_length=2, max_length=2)
    paypal_email: EmailStr | None = None
    can_receive_paypal: bool | None = None
    email_notifications: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v is not None and not valid_timezone(v):
            raise ValueError("Unknown time zone")
        return v

    @field_validator("default_currency")
    @classmethod
    def _cur(cls, v):
        return check_currency(v) if v is not None else None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------------------------------------------------------------- businesses / contacts
class BusinessIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(None, max_length=80)
    default_currency: str | None = None  # empty = the owner's currency from sign-up

    @field_validator("default_currency")
    @classmethod
    def _cur(cls, v):
        return check_currency(v) if v else None


class BusinessOut(ORM):
    id: int
    name: str
    category: str | None
    default_currency: str
    created_at: UTC


LOCAL_ID_HINT = "Your ID: 1-30 letters, numbers, - _ or . (start with a letter or number)"


def clean_local_id(v: str | None) -> str | None:
    import re
    v = (v or "").strip().lstrip("#")
    if not v:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,29}", v):
        raise ValueError(LOCAL_ID_HINT)
    return v


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    side: Literal["receivable", "payable"]
    khataz_id: str | None = Field(None, description="If they're on Khataz: invite them to link")
    local_id: str | None = Field(None, description="Your own ID for them, unique in this business")
    currency: str | None = None
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=40)
    company: str | None = Field(None, max_length=160)
    paypal_email: EmailStr | None = None
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        return check_currency(v) if v else None

    @field_validator("local_id")
    @classmethod
    def _lid(cls, v):
        return clean_local_id(v)

    @model_validator(mode="after")
    def _identified(self):
        if not self.local_id and not (self.khataz_id or "").strip():
            raise ValueError("Give their Khataz ID, or your own ID for them")
        return self


class LocalIdIn(BaseModel):
    local_id: str

    @field_validator("local_id")
    @classmethod
    def _lid(cls, v):
        v = clean_local_id(v)
        if not v:
            raise ValueError(LOCAL_ID_HINT)
        return v


class ContactOut(ORM):
    id: int
    local_id: str | None
    name: str
    email: str | None
    phone: str | None
    company: str | None
    paypal_email: str | None
    notes: str | None
    linked_user_id: int | None


class RelationshipSummary(BaseModel):
    id: int
    business_id: int
    business_name: str
    contact_name: str
    other_party: str
    side: str
    perspective: Literal["owed_to_me", "i_owe"]  # the record's usual side for this viewer
    # where the money stands now: a customer who has paid in more than they owed is "i_owe"
    direction: Literal["owed_to_me", "i_owe"] = "owed_to_me"
    amount: Amount = Decimal("0")  # the balance as a positive number, read with `direction`
    role: Literal["owner", "counterparty"]
    currency: str
    balance: Amount
    disputed: Amount
    linked: bool
    local_id: str | None = None  # the owner's own ID for the contact (owner only)
    other_khataz_id: str | None = None
    other_has_avatar: bool = False
    other_avatar_version: str | None = None
    pending_actions: int = 0


# ---------------------------------------------------------------- ledger
class EntryIn(BaseModel):
    type: Literal["credit", "payment", "goods", "adjustment"]
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    description: str | None = Field(None, max_length=500)
    occurred_at: datetime | None = None
    increase: bool | None = None  # adjustments only


class EntryOut(ORM):
    id: int
    type: str
    amount: Amount
    delta: Amount
    currency: str
    description: str | None
    occurred_at: UTC
    status: str
    confirmation: str
    source: str
    claim_id: int | None
    reverses_entry_id: int | None
    reversed_by_entry_id: int | None
    created_by: int
    created_at: UTC
    cancel_until: UTC | None = None  # the other side can cancel until then


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class DisputeOut(ORM):
    id: int
    entry_id: int
    opened_by: int
    reason: str
    status: str
    resolution: str | None
    resolution_note: str | None
    created_at: UTC
    resolved_at: UTC | None


class DisputeResolveIn(BaseModel):
    resolution: Literal["kept", "voided"]
    note: str | None = Field(None, max_length=500)


# ---------------------------------------------------------------- claims
class ClaimIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    currency: str
    sender_txn_id: str | None = None
    paid_at_local: datetime | None = Field(
        None, description="Time shown on the screenshot, in the submitter's own time zone")
    payer_name: str | None = Field(None, max_length=160)
    payer_email: str | None = Field(None, max_length=255)
    payee_name: str | None = Field(None, max_length=160)
    paypal_status: str | None = Field(None, max_length=40)
    image_hash: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=500)
    extracted: dict | None = None


class ClaimRespondIn(BaseModel):
    response: Literal["received", "different_amount", "not_received"]
    received_amount: Decimal | None = Field(None, gt=0, max_digits=16, decimal_places=2)
    received_currency: str | None = None
    recipient_txn_id: str | None = None
    payer_name_seen: str | None = Field(None, max_length=160)
    manual_rate: Decimal | None = Field(None, gt=0)
    confirm_without_paypal: bool = False  # receiver's choice when PayPal doesn't show it yet


class ClaimResolveIn(BaseModel):
    action: Literal["allocate", "hold", "reject"]
    amount: Decimal | None = Field(None, gt=0, max_digits=16, decimal_places=2)
    note: str | None = Field(None, max_length=500)


class ClaimOut(ORM):
    id: int
    relationship_id: int
    submitted_by: int
    recipient_user_id: int
    has_image: bool = False
    sender_txn_id: str | None
    recipient_txn_id: str | None
    claimed_amount: Amount
    claimed_currency: str
    received_amount: Amount | None
    received_currency: str | None
    converted_amount: Amount | None
    fx_rate: Decimal | None
    fx_source: str | None
    payer_name: str | None
    payer_email: str | None
    payee_name: str | None
    paypal_status: str | None
    payer_paypal_email: str | None = None
    auto_confirmed: bool = False
    auto_check: bool = False  # the receiver has the automatic PayPal check on
    paid_at: UTC | None
    state: str
    review_reasons: list[str]
    review_reason_text: list[str] = []
    note: str | None
    resolution_note: str | None
    allocated_entry_id: int | None
    created_at: UTC
    resolved_at: UTC | None


# ---------------------------------------------------------------- misc
class InviteIn(BaseModel):
    email: EmailStr | None = None
    khataz_id: str | None = None
    send_email: bool = True  # email invites: also send an email

    @model_validator(mode="after")
    def _one(self):
        if not self.email and not self.khataz_id:
            raise ValueError("Give their email or Khataz ID")
        return self


class InviteOut(BaseModel):
    id: int
    contact_name: str
    business_name: str
    invited_by: str
    invited_email: str | None
    side: str | None
    status: str
    created_at: UTC


class NotificationOut(ORM):
    id: int
    kind: str
    message: str
    relationship_id: int | None
    read: bool
    created_at: UTC


class AuditOut(BaseModel):
    id: int
    actor: str | None
    action: str
    entity: str
    entity_id: int | None
    before: dict | None
    after: dict | None
    reason: str | None
    created_at: UTC
