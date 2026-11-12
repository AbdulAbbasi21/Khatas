from datetime import timedelta

import bcrypt
import jwt

from app.core.config import settings
from app.core.timeutil import utcnow

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": utcnow() + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        if payload.get("purpose"):  # e.g. a PayPal "state" token is not a login
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def create_purpose_token(user_id: int, purpose: str, minutes: int = 15, **extra) -> str:
    payload = {"sub": str(user_id), "purpose": purpose, "exp": utcnow() + timedelta(minutes=minutes), **extra}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_purpose_token(token: str, purpose: str, full: bool = False):
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        if payload.get("purpose") != purpose:
            return None
        return payload if full else int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def _fernet():
    import base64
    import hashlib

    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(("khataz-secrets:" + settings.jwt_secret).encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
