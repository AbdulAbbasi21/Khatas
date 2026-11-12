"""
Payment claims: "I paid you, here is the PayPal screenshot".

Flow: scan receipt (must be PayPal) -> create claim -> recipient responds -> allocated | needs_review | disputed
A claim only reduces a debt after the RECIPIENT confirms it, and only automatically when the
amount is within tolerance and the payer/payee match. Everything else waits for the recipient.
"""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.money import currency, money
from app.core.timeutil import local_to_utc, utcnow
from app.models import PaymentClaim, Relationship, User
from app.services import fx, ledger
from app.services.common import (
    audit, creditor_id, creditor_name, debtor_id, debtor_name, notify, role_in, snapshot,
)

CLAIM_FIELDS = ["state", "claimed_amount", "claimed_currency", "received_amount",
                "received_currency", "converted_amount", "fx_rate", "fx_source",
                "sender_txn_id", "payer_name", "payer_email", "paid_at", "review_reasons"]

REASON_TEXT = {
    "different_amount": "The recipient says a different amount arrived",
    "amount_below_tolerance": "Received amount is more than the allowed fee/conversion difference below the claim",
    "amount_above_claim": "Received amount is higher than the claimed amount",
    "fx_unavailable": "No exchange rate was available; enter the amount to apply",
    "payer_mismatch": "The payer doesn't match the person who owes the money",
    "payee_mismatch": "The screenshot shows a payment to someone else",
    "paypal_status_not_completed": "The screenshot's PayPal status isn't Completed",
    "overpayment": "The payment is larger than the outstanding balance",
}

TXN_RE = re.compile(r"^[0-9A-Z]{17}$")
DATE_FORMATS = ["%b %d, %Y at %I:%M %p", "%B %d, %Y at %I:%M %p", "%b %d, %Y %I:%M %p",
                "%b %d, %Y", "%B %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%d.%m.%Y",
                "%Y-%m-%d"]


# ---------------------------------------------------------------- helpers
def _norm_txn(txn: str | None) -> str | None:
    if not txn:
        return None
    t = re.sub(r"\s", "", txn).upper()
    if not TXN_RE.match(t):
        raise HTTPException(400, "A PayPal transaction ID has 17 letters and digits")
    return t


def parse_local_datetime(text: str | None) -> str | None:
    """'Nov 3, 2026 at 10:15 AM' -> '2026-11-03T10:15' (wall-clock time, no zone)."""
    if not text:
        return None
    clean = re.sub(r"\s+", " ", text.replace(",", ", ")).replace(" ,", ",").strip()
    clean = re.sub(r",\s+", ", ", clean)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return None


def _tokens(s: str | None) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9@._-]+", (s or "").casefold()) if t}


def same_party(claimed: str | None, *known: str | None) -> bool:
    """Loose match: one name's words contained in the other's, or the same email."""
    a = _tokens(claimed)
    if not a:
        return True  # nothing to compare
    for k in known:
        b = _tokens(k)
        if b and (a <= b or b <= a):
            return True
    return False


def _user_names(user: User | None) -> list[str | None]:
    return [user.name, user.email, user.paypal_email] if user else []


def _debtor_identities(db: Session, rel: Relationship) -> list[str | None]:
    if rel.side == "receivable":
        c = rel.contact
        return [c.name, c.email, c.paypal_email, c.company, *_user_names(c.linked_user)]
    return [rel.business.name, *_user_names(rel.business.owner)]


def _creditor_identities(db: Session, rel: Relationship) -> list[str | None]:
    if rel.side == "receivable":
        return [rel.business.name, *_user_names(rel.business.owner)]
    c = rel.contact
    return [c.name, c.email, c.paypal_email, c.company, *_user_names(c.linked_user)]


def _receipts_dir() -> Path:
    p = Path(settings.storage_dir) / "receipts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _verdict_path(image_hash: str) -> Path:
    p = _receipts_dir() / "verdicts"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{image_hash}.json"


def _save_verdict(image_hash: str, is_paypal: bool, reason: str | None) -> None:
    _verdict_path(image_hash).write_text(json.dumps({"is_paypal": is_paypal, "reason": reason}))


def _load_verdict(image_hash: str) -> dict | None:
    p = _verdict_path(image_hash)
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, ValueError):
        return None


def _recipient_for(rel: Relationship, actor: User) -> int:
    rid = creditor_id(rel)
    if rid is None:
        raise HTTPException(400, f"{creditor_name(rel)} isn't on Khataz yet, so nobody can confirm "
                                 "this payment. Invite them first, or record the payment manually.")
    return rid


def find_duplicate(db: Session, recipient_id: int, txn: str | None,
                   image_hash: str | None) -> PaymentClaim | None:
    if txn:
        c = db.scalar(select(PaymentClaim).where(PaymentClaim.recipient_user_id == recipient_id,
                                                 PaymentClaim.sender_txn_id == txn))
        if c:
            return c
    if image_hash:
        return db.scalar(select(PaymentClaim).where(PaymentClaim.recipient_user_id == recipient_id,
                                                    PaymentClaim.image_hash == image_hash))
    return None


# ---------------------------------------------------------------- 1. scan
def scan_screenshot(db: Session, rel: Relationship, actor: User, data: bytes,
                    filename: str | None) -> dict:
    recipient_id = _recipient_for(rel, actor)
    image_hash = hashlib.sha256(data).hexdigest()
    ext = (Path(filename or "").suffix.lower() or ".img")[:6]
    path = _receipts_dir() / f"{image_hash}{ext}"
    if not path.exists():
        path.write_bytes(data)

    result = {"image_hash": image_hash, "scanner_available": False, "scan": None,
              "is_paypal_receipt": None, "reason": None,
              "prefill": {}, "warnings": [], "duplicate_claim_id": None}

    dup = find_duplicate(db, recipient_id, None, image_hash)
    if dup:
        result["duplicate_claim_id"] = dup.id
        result["warnings"].append(f"This screenshot was already submitted (claim #{dup.id}).")

    if not settings.scanner_enabled:
        result["warnings"].append("The scanner is turned off. Enter the details yourself.")
        return result
    try:
        from app.scanner import get_engines
        from app.scanner.service import InvalidImageError, scan

        scan_result = scan(data, get_engines())
    except InvalidImageError as e:
        raise HTTPException(400, str(e))
    except ImportError:
        result["warnings"].append("The scanner isn't installed on this server. "
                                  "Enter the details yourself.")
        return result

    result["scanner_available"] = True
    result["scan"] = scan_result.model_dump(mode="json")
    result["is_paypal_receipt"] = bool(scan_result.is_paypal_receipt)
    _save_verdict(image_hash, result["is_paypal_receipt"], scan_result.reason)
    if not scan_result.is_paypal_receipt:
        result["reason"] = scan_result.reason or "This isn't a PayPal receipt."
        return result

    r = scan_result.receipt
    payee = r.counterparty if r.direction == "sent" else None
    payer = r.counterparty if r.direction == "received" else None
    result["prefill"] = {
        "sender_txn_id": r.transaction_id,
        "amount": str(r.amount) if r.amount is not None else None,
        "currency": r.currency,
        "paid_at_local": parse_local_datetime(r.date),
        "payee_name": payee,
        "payer_name": payer,
        "paypal_status": r.status,
    }
    if r.transaction_id:
        dup = find_duplicate(db, recipient_id, r.transaction_id, None)
        if dup:
            result["duplicate_claim_id"] = dup.id
            result["warnings"].append(f"Transaction {r.transaction_id} was already claimed "
                                      f"(claim #{dup.id}).")
    if payee and not same_party(payee, *_creditor_identities(db, rel)):
        result["warnings"].append(f"The screenshot shows a payment to “{payee}”, "
                                  f"not {creditor_name(rel)}.")
    if r.status and r.status.lower() != "completed":
        result["warnings"].append(f"PayPal status is “{r.status}”. Only completed payments count.")
    if not scan_result.complete:
        result["warnings"].append("Some details couldn't be read. Check them before submitting.")
    return result


# ---------------------------------------------------------------- 2. create
def create_claim(db: Session, rel: Relationship, actor: User, *, amount, currency_code: str,
                 sender_txn_id: str | None, paid_at_local: datetime | None,
                 payer_name: str | None, payer_email: str | None, payee_name: str | None,
                 paypal_status: str | None, image_hash: str | None, note: str | None,
                 extracted: dict | None) -> PaymentClaim:
    recipient_id = _recipient_for(rel, actor)
    if actor.id not in {recipient_id, debtor_id(rel)}:
        raise HTTPException(403, "Only the payer or the recipient can record this payment")
    amt = money(amount)
    if amt <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    cur = currency(currency_code)
    txn = _norm_txn(sender_txn_id)
    if not image_hash:
        raise HTTPException(400, "Upload the PayPal receipt")
    verdict = _load_verdict(image_hash)
    if verdict and not verdict.get("is_paypal"):
        raise HTTPException(400, verdict.get("reason") or "This isn't a PayPal receipt")

    dup = find_duplicate(db, recipient_id, txn, image_hash)
    if dup:
        raise HTTPException(409, f"This payment was already submitted (claim #{dup.id}). "
                                 "One payment can only be counted once.")

    image_path = None
    if image_hash:
        matches = list(_receipts_dir().glob(f"{image_hash}.*"))
        if not matches:
            raise HTTPException(400, "Upload the screenshot again; it wasn't found on the server")
        image_path = str(matches[0])

    from app.services import paypal  # local: keeps the scanner-only imports light

    debtor_uid = debtor_id(rel)
    if actor.id == debtor_uid and paypal.login_enabled() and not actor.paypal_user_id:
        raise HTTPException(400, "Connect your PayPal account first (Profile → PayPal), "
                                 "so the receiver can see the payment came from you.")
    if payer_name is None and payer_email is None:  # default: the debtor paid
        ids = _debtor_identities(db, rel)
        payer_name = ids[0]
    # the verified sender: the debtor's PayPal account, unless someone else paid for them
    payer_user = db.get(User, debtor_uid) if debtor_uid else None
    verified_email = verified_id = None
    if payer_user and payer_user.paypal_user_id and (
            not payer_name or same_party(payer_name, *_debtor_identities(db, rel),
                                         payer_user.paypal_verified_name)):
        verified_email, verified_id = payer_user.paypal_verified_email, payer_user.paypal_payer_id

    claim = PaymentClaim(
        relationship_id=rel.id, submitted_by=actor.id, recipient_user_id=recipient_id,
        image_hash=image_hash, image_path=image_path, sender_txn_id=txn,
        claimed_amount=amt, claimed_currency=cur,
        paid_at=local_to_utc(paid_at_local, actor.timezone) if paid_at_local else None,
        payer_name=(payer_name or "").strip() or None, payer_email=(payer_email or "").strip() or None,
        payee_name=(payee_name or "").strip() or None,
        paypal_status=(paypal_status or "").strip() or None,
        payer_paypal_email=verified_email, payer_paypal_id=verified_id,
        note=(note or "").strip() or None, extracted=extracted, review_reasons=[],
    )
    db.add(claim)
    db.flush()
    audit(db, actor, "claim.created", "payment_claim", claim.id, rel.id,
          after=snapshot(claim, CLAIM_FIELDS))
    if recipient_id != actor.id:
        notify(db, recipient_id, "claim_to_confirm",
               f"{actor.name} sent you {amt} {cur} by PayPal"
               + (f" from {verified_email}" if verified_email else "")
               + (f" (transaction {txn})" if txn else "") + " and shared the receipt. Check and confirm.",
               rel.id)
    return claim


# ---------------------------------------------------------------- 3. respond
def _to_usd(db, amount: Decimal, cur: str, on) -> Decimal:
    return fx.convert(db, amount, cur, "USD", on)[0]


def respond(db: Session, claim: PaymentClaim, rel: Relationship, actor: User, *, response: str,
            received_amount=None, received_currency: str | None = None,
            recipient_txn_id: str | None = None, payer_name_seen: str | None = None,
            manual_rate=None, paypal_amount: bool = False) -> PaymentClaim:
    """paypal_amount=True: the received amount was read from the receiver's own PayPal account,
    so it is the truth about what arrived and isn't flagged for differing from the claim."""
    if actor.id != claim.recipient_user_id:
        raise HTTPException(403, "Only the person who received the money can confirm it")
    if claim.state != "pending_confirmation":
        raise HTTPException(409, "This claim was already answered")
    before = snapshot(claim, CLAIM_FIELDS)

    if response == "not_received":
        claim.state, claim.resolved_by, claim.resolved_at = "disputed", actor.id, utcnow()
        audit(db, actor, "claim.not_received", "payment_claim", claim.id, rel.id, before,
              snapshot(claim, CLAIM_FIELDS))
        notify(db, claim.submitted_by, "claim_disputed",
               f"{actor.name} says they did NOT receive your {claim.claimed_amount} "
               f"{claim.claimed_currency} payment. The balance didn't change.", rel.id)
        return claim
    if response not in {"received", "different_amount"}:
        raise HTTPException(400, "Response must be received, different_amount or not_received")
    if response == "different_amount" and received_amount is None:
        raise HTTPException(400, "Enter the amount you actually received")

    rec_amt = money(received_amount if received_amount is not None else claim.claimed_amount)
    if rec_amt <= 0:
        raise HTTPException(400, "Received amount must be greater than zero")
    rec_cur = currency(received_currency or claim.claimed_currency)
    on = (claim.paid_at or utcnow()).date()
    reasons: list[str] = ["different_amount"] if response == "different_amount" and not paypal_amount else []

    claim.received_amount, claim.received_currency = rec_amt, rec_cur
    claim.recipient_txn_id = _norm_txn(recipient_txn_id) if recipient_txn_id else None
    rate = Decimal(str(manual_rate)) if manual_rate not in (None, "") else None
    try:
        claim.converted_amount, claim.fx_rate, claim.fx_source = fx.convert(
            db, rec_amt, rec_cur, rel.currency, on, rate)
    except fx.FxUnavailable:
        claim.converted_amount, claim.fx_rate, claim.fx_source = None, None, None
        reasons.append("fx_unavailable")

    # sent vs received, compared in USD (fees and conversion lose a little)
    try:
        if rec_cur == claim.claimed_currency:
            rec_cmp, claim_cmp = rec_amt, Decimal(claim.claimed_amount)
        else:
            rec_cmp = _to_usd(db, rec_amt, rec_cur, on)
            claim_cmp = _to_usd(db, Decimal(claim.claimed_amount), claim.claimed_currency, on)
        if paypal_amount:
            pass
        elif rec_cmp < claim_cmp * settings.payment_tolerance:
            reasons.append("amount_below_tolerance")
        elif rec_cmp > claim_cmp * (2 - settings.payment_tolerance):
            reasons.append("amount_above_claim")
    except fx.FxUnavailable:
        if "fx_unavailable" not in reasons:
            reasons.append("fx_unavailable")

    debtor_ids = _debtor_identities(db, rel)
    for name in (claim.payer_name, claim.payer_email, payer_name_seen):
        if name and not same_party(name, *debtor_ids):
            reasons.append("payer_mismatch")
            break
    if payer_name_seen:
        claim.payer_name = claim.payer_name or payer_name_seen
    if claim.payee_name and not same_party(claim.payee_name, *_creditor_identities(db, rel)):
        reasons.append("payee_mismatch")
    if claim.paypal_status and claim.paypal_status.lower() != "completed":
        reasons.append("paypal_status_not_completed")
    if claim.converted_amount is not None:
        outstanding = ledger.balance(db, rel)["balance"]
        if claim.converted_amount > outstanding:
            reasons.append("overpayment")

    claim.review_reasons = reasons
    if reasons:
        claim.state = "needs_review"
        audit(db, actor, "claim.needs_review", "payment_claim", claim.id, rel.id, before,
              snapshot(claim, CLAIM_FIELDS))
        notify(db, claim.submitted_by, "claim_under_review",
               f"{actor.name} received your payment; it's being reviewed before the balance "
               "is updated.", rel.id)
        return claim
    return _allocate(db, claim, rel, actor, claim.converted_amount, before, "claim.allocated")


def _allocate(db: Session, claim: PaymentClaim, rel: Relationship, actor: User, amount,
              before: dict, action: str, note: str | None = None) -> PaymentClaim:
    desc = "PayPal payment" + (f" {claim.sender_txn_id}" if claim.sender_txn_id else "")
    if claim.received_currency and claim.received_currency != rel.currency:
        desc += f" ({claim.received_amount} {claim.received_currency})"
    entry = ledger.add_entry(db, rel, actor, "payment", amount, description=desc,
                             occurred_at=claim.paid_at, source="claim", claim_id=claim.id)
    claim.allocated_entry_id = entry.id
    claim.state, claim.resolved_by, claim.resolved_at = "allocated", actor.id, utcnow()
    claim.resolution_note = note
    audit(db, actor, action, "payment_claim", claim.id, rel.id, before,
          snapshot(claim, CLAIM_FIELDS) | {"entry_id": entry.id}, reason=note)
    if claim.submitted_by != actor.id:
        notify(db, claim.submitted_by, "claim_allocated",
               f"{actor.name} confirmed your payment. {entry.amount} {rel.currency} was taken "
               f"off the balance owed by {debtor_name(rel)}.", rel.id)
    return claim


# ---------------------------------------------------------------- 4. review
def resolve(db: Session, claim: PaymentClaim, rel: Relationship, actor: User, *, action: str,
            amount=None, note: str | None = None) -> PaymentClaim:
    if actor.id != claim.recipient_user_id:
        raise HTTPException(403, "Only the recipient can decide on this payment")
    if claim.state not in {"needs_review", "held"}:
        raise HTTPException(409, "This claim isn't waiting for review")
    before = snapshot(claim, CLAIM_FIELDS)
    if action == "allocate":
        amt = amount if amount not in (None, "") else claim.converted_amount
        if amt is None:
            raise HTTPException(400, f"Enter the amount in {rel.currency} to take off the balance")
        return _allocate(db, claim, rel, actor, amt, before, "claim.allocated_after_review", note)
    if action == "hold":
        claim.state = "held"
        audit(db, actor, "claim.held", "payment_claim", claim.id, rel.id, before,
              {"state": "held"}, reason=note)
        return claim
    if action == "reject":
        claim.state, claim.resolved_by, claim.resolved_at = "rejected", actor.id, utcnow()
        claim.resolution_note = note
        audit(db, actor, "claim.rejected", "payment_claim", claim.id, rel.id, before,
              {"state": "rejected"}, reason=note)
        notify(db, claim.submitted_by, "claim_rejected",
               f"{actor.name} rejected your {claim.claimed_amount} {claim.claimed_currency} "
               "payment claim" + (f": {note}" if note else "."), rel.id)
        return claim
    raise HTTPException(400, "Action must be allocate, hold or reject")


def reverse(db: Session, claim: PaymentClaim, rel: Relationship, actor: User,
            reason: str) -> PaymentClaim:
    """Refund or chargeback after allocation: adds a reversal entry, deletes nothing."""
    if actor.id != claim.recipient_user_id:
        raise HTTPException(403, "Only the recipient can reverse this payment")
    if claim.state != "allocated" or not claim.allocated_entry_id:
        raise HTTPException(409, "Only an allocated payment can be reversed")
    from app.models import LedgerEntry

    entry = db.get(LedgerEntry, claim.allocated_entry_id)
    ledger.reverse_entry(db, entry, rel, actor, reason)
    claim.state = "reversed"
    claim.resolution_note = reason
    audit(db, actor, "claim.reversed", "payment_claim", claim.id, rel.id,
          {"state": "allocated"}, {"state": "reversed"}, reason=reason)
    return claim


def role_check(rel: Relationship, actor: User) -> str:
    role = role_in(rel, actor)
    if not role:
        raise HTTPException(404, "Record not found")
    return role
