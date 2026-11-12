"""PayPal: connect your account (verified sender) and the receiver's automatic payment check."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_purpose_token, decode_purpose_token, encrypt_secret
from app.core.timeutil import utcnow
from app.models import PaymentClaim, User
from app.routers.auth import current_user
from app.services import autocheck, paypal
from app.services.common import audit

router = APIRouter(prefix="/api/paypal", tags=["paypal"])
STATE = "paypal_connect"


class CallbackIn(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=2000)


class AutoCheckIn(BaseModel):
    client_id: str = Field(min_length=10, max_length=255)
    secret: str = Field(min_length=10, max_length=255)


def _hint(cid: str | None) -> str | None:
    return cid[:6] + "…" + cid[-4:] if cid else None


def _status(user: User) -> dict:
    return {
        "login_enabled": paypal.login_enabled(),
        "env": settings.paypal_env,
        # PayPal sends people to a page outside Khataz (e.g. https://example.com): they paste the link
        "paste_mode": not settings.paypal_redirect_uri.startswith(settings.app_url),
        "connected": None if not user.paypal_user_id else {
            "email": user.paypal_verified_email, "name": user.paypal_verified_name,
            "payer_id": user.paypal_payer_id, "verified": user.paypal_account_verified,
            "connected_at": user.paypal_connected_at,
        },
        "autocheck": {
            "enabled": autocheck.enabled_for(user),
            "client_id_hint": _hint(user.paypal_api_client_id or
                                    (settings.paypal_client_id if autocheck.uses_app_keys(user) else None)),
            # "app": always on with Khataz's own PayPal app keys (nothing to enter or turn off)
            "source": "own" if user.paypal_api_client_id else ("app" if autocheck.uses_app_keys(user) else None),
            "checked_at": user.paypal_api_checked_at,
            "error": user.paypal_api_error,
            "every_seconds": settings.paypal_sync_seconds,
        },
    }


@router.get("/status")
def status(user: User = Depends(current_user)):
    return _status(user)


@router.get("/connect-url")
def connect_url(user: User = Depends(current_user)):
    if not paypal.login_enabled():
        raise HTTPException(400, "PayPal login isn't set up on this server (PAYPAL_CLIENT_ID).")
    return {"url": paypal.connect_url(create_purpose_token(user.id, STATE))}


@router.post("/callback")
async def callback(data: CallbackIn, db: Session = Depends(get_db)):
    """PayPal sends the user back here. The state token says which Khataz user it was."""
    uid = decode_purpose_token(data.state, STATE)
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(400, "This PayPal link expired. Start again from your profile.")
    try:
        info = await run_in_threadpool(paypal.exchange_code, data.code)
    except paypal.PayPalError as e:
        raise HTTPException(502, str(e))
    other = db.scalar(select(User).where(User.paypal_user_id == info["user_id"], User.id != user.id))
    if other:
        raise HTTPException(409, f"This PayPal account is already connected to @{other.khataz_id}.")
    user.paypal_user_id, user.paypal_payer_id = info["user_id"], info["payer_id"]
    user.paypal_verified_email, user.paypal_verified_name = info["email"], info["name"]
    user.paypal_account_verified, user.paypal_connected_at = info["verified"], utcnow()
    audit(db, user, "paypal.connected", "user", user.id, after={"email": info["email"]})
    db.commit()
    return {"email": info["email"], "name": info["name"]}


@router.delete("/connection")
def disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.paypal_user_id = user.paypal_payer_id = None
    user.paypal_verified_email = user.paypal_verified_name = None
    user.paypal_account_verified = user.paypal_connected_at = None
    audit(db, user, "paypal.disconnected", "user", user.id)
    db.commit()
    return _status(user)


@router.put("/autocheck")
async def save_autocheck(data: AutoCheckIn, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    cid, secret = data.client_id.strip(), data.secret.strip()
    try:
        await run_in_threadpool(paypal.check_credentials, cid, secret)
    except paypal.PayPalError as e:
        raise HTTPException(400, str(e))
    user.paypal_api_client_id, user.paypal_api_secret_enc = cid, encrypt_secret(secret)
    user.paypal_api_error, user.paypal_api_checked_at = None, utcnow()
    audit(db, user, "paypal.autocheck_on", "user", user.id)
    db.commit()
    return _status(user)


@router.delete("/autocheck")
def remove_autocheck(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.paypal_api_client_id = user.paypal_api_secret_enc = None
    user.paypal_api_error = user.paypal_api_checked_at = None
    audit(db, user, "paypal.autocheck_off", "user", user.id)
    db.commit()
    return _status(user)


@router.get("/live")
def live(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Small, cheap status for the live "checking PayPal" indicator (polled every few seconds)."""
    return autocheck.live_status(db, user)


@router.post("/autocheck/run")
async def run_now(claim_id: int | None = None, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Check PayPal now (all my pending payments, or just one)."""
    if claim_id is not None:
        c = db.get(PaymentClaim, claim_id)
        if not c or c.recipient_user_id != user.id:
            raise HTTPException(404, "Payment not found")
    result = await run_in_threadpool(autocheck.check_receiver, db, user, claim_id)
    db.commit()
    return result
