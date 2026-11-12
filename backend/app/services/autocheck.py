"""
Automatic payment check: match a receiver's pending payment claims against the receiver's own
PayPal transactions (Transaction Search). A claim is confirmed only when PayPal shows an
incoming, completed payment that
  - came from the payer's verified PayPal account (email or payer ID from "Log in with PayPal"),
  - is in the claimed currency and within the payment tolerance of the claimed amount,
  - happened no earlier than two days before the claimed payment date, and
  - hasn't already been used for another claim.
The confirmation then goes through the normal rules (overpayment etc. still go to review).
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret
from app.core.timeutil import utcnow
from app.models import PaymentClaim, Relationship, User
from app.services import claims as claim_svc
from app.services import paypal
from app.services.common import audit, notify

log = logging.getLogger("khataz.autocheck")


# live state for the "is Khataz checking PayPal right now?" indicator (one server process)
LIVE = {"checking": set(), "loop_last": None, "loop_next": None}


def uses_app_keys(user: User) -> bool:
    """This account receives into the PayPal app's own account, so it uses the app keys from .env."""
    return bool(settings.paypal_client_id and settings.paypal_client_secret
                and (user.email or "").lower() in settings.paypal_receiver_emails)


def credentials(user: User) -> tuple[str, str] | None:
    """(client_id, secret) to read this user's PayPal: their own saved app, else the app keys."""
    if user.paypal_api_client_id and user.paypal_api_secret_enc:
        return user.paypal_api_client_id, decrypt_secret(user.paypal_api_secret_enc)
    if uses_app_keys(user):
        return settings.paypal_client_id, settings.paypal_client_secret
    return None


def enabled_for(user: User) -> bool:
    return bool(user.paypal_api_client_id and user.paypal_api_secret_enc) or uses_app_keys(user)


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _incoming(t: dict) -> dict | None:
    """Normalise one Transaction Search row; None if it isn't a completed incoming payment."""
    info, payer = t.get("transaction_info") or {}, t.get("payer_info") or {}
    amt = info.get("transaction_amount") or {}
    try:
        value = Decimal(str(amt.get("value")))
    except (InvalidOperation, TypeError):
        return None
    if value <= 0 or info.get("transaction_status") != "S" or not info.get("transaction_id"):
        return None
    return {
        "id": info["transaction_id"], "amount": value, "currency": amt.get("currency_code"),
        "at": _parse_time(info.get("transaction_initiation_date") or info.get("transaction_updated_date")),
        "email": (payer.get("email_address") or "").strip().lower() or None,
        "payer_id": payer.get("account_id"),
    }


def _from_payer(claim: PaymentClaim, tx: dict) -> bool:
    """The payment came from this claim's verified payer, in its currency, around its date."""
    by_email = claim.payer_paypal_email and tx["email"] == claim.payer_paypal_email.lower()
    by_id = claim.payer_paypal_id and tx["payer_id"] == claim.payer_paypal_id
    if not (by_email or by_id) or tx["currency"] != claim.claimed_currency:
        return False
    since = _aware(claim.paid_at or claim.created_at) - timedelta(days=2)
    return tx["at"] is None or tx["at"] >= since


def _closest(claim: PaymentClaim, txs: list[dict]) -> dict | None:
    """For a wrong-amount payment: one paid by this payer before the claim was sent
    (a day of slack for clock differences), closest to the claimed amount."""
    until = _aware(claim.created_at) + timedelta(days=1)
    cands = [t for t in txs if _from_payer(claim, t) and (t["at"] is None or t["at"] <= until)]
    claimed = Decimal(claim.claimed_amount)
    return min(cands, key=lambda t: abs(t["amount"] - claimed), default=None)


def _matches(claim: PaymentClaim, tx: dict) -> bool:
    """...and the amount is the claimed one (within the fee tolerance)."""
    if not _from_payer(claim, tx):
        return False
    claimed = Decimal(claim.claimed_amount)
    tol = settings.payment_tolerance
    return claimed * tol <= tx["amount"] <= claimed * (2 - tol)


def check_receiver(db: Session, receiver: User, only_claim_id: int | None = None) -> dict:
    """Check the receiver's pending claims. Returns {checked, confirmed, error}."""
    result = {"checked": 0, "confirmed": 0, "error": None}
    if not enabled_for(receiver):
        result["error"] = "Automatic PayPal check isn't set up"
        return result
    q = select(PaymentClaim).where(PaymentClaim.recipient_user_id == receiver.id,
                                   PaymentClaim.state == "pending_confirmation",
                                   (PaymentClaim.payer_paypal_email.is_not(None))
                                   | (PaymentClaim.payer_paypal_id.is_not(None)))
    if only_claim_id:
        q = q.where(PaymentClaim.id == only_claim_id)
    pending = sorted(db.scalars(q).all(), key=lambda c: c.id)
    result["checked"] = len(pending)
    if not pending:
        return result

    now = datetime.now(timezone.utc)
    start = min(_aware(c.paid_at or c.created_at) for c in pending) - timedelta(days=2)
    LIVE["checking"].add(receiver.id)
    try:
        rows = paypal.list_transactions(*credentials(receiver), max(start, now - timedelta(days=31)), now)
        receiver.paypal_api_error = None
    except paypal.PayPalError as e:
        receiver.paypal_api_error = str(e)
        result["error"] = str(e)
        receiver.paypal_api_checked_at = utcnow()
        return result
    except Exception as e:  # bad stored secret etc.
        receiver.paypal_api_error = "Couldn't use the saved PayPal credentials. Save them again."
        result["error"] = receiver.paypal_api_error
        log.warning("autocheck failed for user %s: %s", receiver.id, e)
        return result
    finally:
        LIVE["checking"].discard(receiver.id)
    receiver.paypal_api_checked_at = utcnow()

    used = set(db.scalars(select(PaymentClaim.recipient_txn_id).where(
        PaymentClaim.recipient_user_id == receiver.id,
        PaymentClaim.recipient_txn_id.is_not(None))).all())
    txs = [t for t in (_incoming(r) for r in rows) if t and t["id"] not in used]

    # pass 1: exact matches; pass 2: the verified payer paid, but not the amount they claimed.
    # PayPal shows what actually arrived, so that amount is credited (never the claimed one).
    todo = list(pending)
    for exact in (True, False):
        for claim in list(todo):
            tx = next((t for t in txs if _matches(claim, t)), None) if exact else _closest(claim, txs)
            if not tx:
                continue
            txs.remove(tx)
            if _confirm(db, receiver, claim, tx):
                todo.remove(claim)
                result["confirmed"] += 1
    return result


def run_all(db_factory) -> None:
    """One background pass over every receiver who turned the check on."""
    db = db_factory()
    try:
        receivers = [u for u in db.scalars(select(User)).all() if enabled_for(u)]
        for r in receivers:
            try:
                check_receiver(db, r)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("autocheck failed for user %s", r.id)
    finally:
        db.close()


def _confirm(db: Session, receiver: User, claim: PaymentClaim, tx: dict) -> bool:
    rel = db.get(Relationship, claim.relationship_id)
    claimed = Decimal(claim.claimed_amount)
    differs = not _matches(claim, tx)
    try:
        with db.begin_nested():
            claim_svc.respond(db, claim, rel, receiver, response="received",
                              received_amount=tx["amount"], received_currency=tx["currency"],
                              recipient_txn_id=tx["id"], paypal_amount=True)
    except HTTPException as e:
        log.warning("autocheck couldn't confirm claim %s: %s", claim.id, e.detail)
        return False
    claim.auto_confirmed = True
    audit(db, receiver, "claim.auto_confirmed", "payment_claim", claim.id, rel.id,
          after={"paypal_transaction": tx["id"], "amount": str(tx["amount"]),
                 "currency": tx["currency"], "payer": tx["email"] or tx["payer_id"],
                 "claimed": str(claimed)})
    who = tx["email"] or "the payer"
    got = f"{tx['amount']} {tx['currency']}"
    if differs:
        msg = (f"PayPal shows {got} from {who} (transaction {tx['id']}), not the "
               f"{claimed} {claim.claimed_currency} that was claimed. Only {got} was credited.")
        notify(db, receiver.id, "claim_auto_confirmed", msg, rel.id)
        notify(db, claim.submitted_by, "claim_amount_corrected", msg, rel.id)
    else:
        notify(db, receiver.id, "claim_auto_confirmed",
               f"PayPal shows {got} from {who} (transaction {tx['id']}). "
               "The payment was confirmed automatically.", rel.id)
    return True


def pending_count(db: Session, receiver: User) -> int:
    from sqlalchemy import func
    return db.scalar(select(func.count()).select_from(PaymentClaim).where(
        PaymentClaim.recipient_user_id == receiver.id, PaymentClaim.state == "pending_confirmation",
        (PaymentClaim.payer_paypal_email.is_not(None)) | (PaymentClaim.payer_paypal_id.is_not(None)))) or 0


def live_status(db: Session, user: User) -> dict:
    on = enabled_for(user)
    return {
        "enabled": on,
        "checking_now": user.id in LIVE["checking"],
        "waiting": pending_count(db, user) if on else 0,
        "last_checked_at": user.paypal_api_checked_at,
        "last_round_at": LIVE["loop_last"],
        "next_check_at": LIVE["loop_next"] if on else None,
        "every_seconds": settings.paypal_sync_seconds,
        "error": user.paypal_api_error if on else None,
    }


PAYPAL_STATUS = {"S": "completed", "P": "pending", "V": "reversed / refunded", "D": "denied", "F": "partly refunded"}


def _any_row(t: dict) -> dict | None:
    """Like _incoming, but keeps pending / reversed payments too (for showing, never for confirming)."""
    info, payer = t.get("transaction_info") or {}, t.get("payer_info") or {}
    amt = info.get("transaction_amount") or {}
    try:
        value = Decimal(str(amt.get("value")))
    except (InvalidOperation, TypeError):
        return None
    if value <= 0 or not info.get("transaction_id"):
        return None
    return {
        "id": info["transaction_id"], "amount": value, "currency": amt.get("currency_code"),
        "at": _parse_time(info.get("transaction_initiation_date") or info.get("transaction_updated_date")),
        "email": (payer.get("email_address") or "").strip().lower() or None,
        "payer_id": payer.get("account_id"),
        "status": PAYPAL_STATUS.get(info.get("transaction_status"), info.get("transaction_status") or "unknown"),
        "completed": info.get("transaction_status") == "S",
    }


def inspect_claim(db: Session, receiver: User, claim: PaymentClaim) -> dict:
    """What the receiver's PayPal account shows for this claim right now. Read-only: changes nothing."""
    claimed = Decimal(claim.claimed_amount)
    out = {"checked_at": utcnow(), "claimed_amount": str(claimed), "claimed_currency": claim.claimed_currency,
           "payer": claim.payer_paypal_email or claim.payer_paypal_id, "linked_txn_id": claim.recipient_txn_id,
           "verdict": None, "message": None, "payments": []}
    if not enabled_for(receiver):
        out.update(verdict="off", message="Automatic PayPal check is off. Add your PayPal app keys in your Profile.")
        return out
    if not out["payer"]:
        out.update(verdict="no_identity", message="The payer hasn't connected PayPal, so Khataz can't tell "
                                                  "which payment in your account is theirs.")
        return out

    now = datetime.now(timezone.utc)
    start = max(_aware(claim.paid_at or claim.created_at) - timedelta(days=2), now - timedelta(days=31))
    LIVE["checking"].add(receiver.id)
    try:
        rows = paypal.list_transactions(*credentials(receiver), start, now)
    except paypal.PayPalError as e:
        out.update(verdict="error", message=str(e))
        return out
    except Exception as e:
        log.warning("inspect failed for user %s: %s", receiver.id, e)
        out.update(verdict="error", message="Couldn't use the saved PayPal credentials. Save them again.")
        return out
    finally:
        LIVE["checking"].discard(receiver.id)
    receiver.paypal_api_checked_at = utcnow()

    used = {txn: cid for txn, cid in db.execute(select(PaymentClaim.recipient_txn_id, PaymentClaim.id).where(
        PaymentClaim.recipient_user_id == receiver.id, PaymentClaim.recipient_txn_id.is_not(None))).all()}
    mine = []
    for t in filter(None, (_any_row(r) for r in rows)):
        same_payer = ((claim.payer_paypal_email and t["email"] == claim.payer_paypal_email.lower())
                      or (claim.payer_paypal_id and t["payer_id"] == claim.payer_paypal_id))
        if same_payer:
            mine.append(t)
    mine.sort(key=lambda t: t["at"] or now, reverse=True)

    def row(t, note):
        return {"id": t["id"], "amount": str(t["amount"]), "currency": t["currency"], "from": t["email"] or t["payer_id"],
                "at": t["at"], "status": t["status"], "note": note}

    for t in mine[:10]:
        if t["id"] == claim.recipient_txn_id:
            note = "this payment"
        elif t["id"] in used:
            note = "used for another payment"
        else:
            note = None
        out["payments"].append(row(t, note))

    got = f"{claimed} {claim.claimed_currency}"
    linked = next((t for t in mine if t["id"] == claim.recipient_txn_id), None)
    free = [t for t in mine if t["id"] not in used and t["completed"]]
    if linked:
        same = linked["currency"] == claim.claimed_currency and linked["amount"] == claimed
        out["verdict"] = "linked_match" if same else "linked_differs"
        out["message"] = (f"PayPal transaction {linked['id']}: {linked['amount']} {linked['currency']} "
                          f"({linked['status']}). The claim said {got}.")
    elif claim.recipient_txn_id:
        out.update(verdict="linked_missing", message=f"Linked to PayPal transaction {claim.recipient_txn_id}, "
                                                     "but it isn't in your PayPal for these dates.")
    elif (exact := next((t for t in free if _matches(claim, t)), None)):
        out.update(verdict="match", message=f"PayPal shows {exact['amount']} {exact['currency']} from "
                                            f"{out['payer']}, matching the claim of {got}.")
    elif free and (near := _closest(claim, free)):
        out.update(verdict="different_amount",
                   message=f"PayPal shows {near['amount']} {near['currency']} from {out['payer']}, "
                           f"but the claim says {got}. Only {near['amount']} {near['currency']} arrived.")
    elif any(not t["completed"] for t in mine):
        out.update(verdict="pending", message="PayPal shows a payment from this payer that isn't completed yet.")
    else:
        out.update(verdict="not_found", message=f"No payment from {out['payer']} in your PayPal for these "
                                                "dates yet. PayPal can take a few minutes (up to 3 hours) to list it.")
    return out
