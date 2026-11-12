import hashlib
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import khataz_id as kid
from app.core.config import settings
from app.core.database import get_db
from app.core.email import send_email
from app.core.security import (create_purpose_token, create_token, decode_purpose_token, decode_token,
                               hash_password, verify_password)
from app.models import User
from app.schemas import PublicUserOut, RegisterIn, TokenOut, UserOut, UserUpdate

router = APIRouter(prefix="/api", tags=["auth"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def current_user(token: str | None = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    user_id = decode_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(401, "Please log in", headers={"WWW-Authenticate": "Bearer"})
    return user


def _by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


class LoginIn(BaseModel):
    email: str
    password: str


def _login(db: Session, email: str, password: str) -> TokenOut:
    user = _by_email(db, email.strip())
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return TokenOut(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if _by_email(db, data.email):
        raise HTTPException(409, "An account with this email already exists")
    if db.scalar(select(User).where(User.khataz_id == data.khataz_id)):
        raise HTTPException(409, f"The Khataz ID @{data.khataz_id} is taken. Try another.")
    user = User(email=data.email.lower(), khataz_id=data.khataz_id, name=data.name.strip(),
                password_hash=hash_password(data.password), timezone=data.timezone,
                default_currency=data.default_currency,
                country=data.country.upper() if data.country else None)
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.get("/auth/khataz-id")
def khataz_id_available(id: str, db: Session = Depends(get_db)):
    """Sign-up form: is this Khataz ID valid and free?"""
    value = kid.normalize(id)
    why = kid.problem(value)
    if why:
        return {"khataz_id": value, "available": False, "reason": why}
    taken = db.scalar(select(User.id).where(User.khataz_id == value)) is not None
    return {"khataz_id": value, "available": not taken,
            "reason": "Already taken" if taken else None}


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)
    password: str = Field(min_length=8, max_length=128)


def _pw_stamp(user: User) -> str:
    """Changes when the password changes, so a reset link works only once."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]


@router.post("/auth/forgot")
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    """Email a reset link (valid 30 minutes). Same answer whether or not the email has an account."""
    user = _by_email(db, data.email)
    if user:
        token = create_purpose_token(user.id, "password_reset", minutes=30, pw=_pw_stamp(user))
        link = f"{settings.app_url}/reset-password?token={token}"
        send_email(user.email, "Reset your Khataz password",
                   f"Hi {user.name},\n\nReset your password here (valid for 30 minutes):\n{link}\n\n"
                   f"If you didn't ask for this, ignore this email.",
                   f"<p>Hi {user.name},</p><p><a href=\"{link}\">Reset your Khataz password</a> "
                   f"(valid for 30 minutes).</p><p>If you didn't ask for this, ignore this email.</p>")
    return {"ok": True}


@router.post("/auth/reset", response_model=TokenOut)
def reset_password(data: ResetIn, db: Session = Depends(get_db)):
    payload = decode_purpose_token(data.token, "password_reset", full=True)
    user = db.get(User, int(payload["sub"])) if payload else None
    if not user or payload.get("pw") != _pw_stamp(user):
        raise HTTPException(400, "This reset link has expired or was already used. Ask for a new one.")
    user.password_hash = hash_password(data.password)
    db.commit()
    return TokenOut(access_token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    return _login(db, data.email, data.password)


@router.post("/auth/token", response_model=TokenOut, include_in_schema=False)
def token_for_docs(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Lets the 'Authorize' button in /docs work (username = email)."""
    return _login(db, form.username, form.password)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(data: UserUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "country" and value:
            value = value.upper()
        setattr(user, field, value)
    db.commit()
    return user


# ---------------------------------------------------------------- profile picture
AVATAR_SIZE = 256
AVATAR_MAX_MB = 5


def _avatar_dir() -> Path:
    p = Path(settings.storage_dir) / "avatars"
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Any photo -> a 256x256 square PNG (centre-cropped, phone rotation fixed)."""
    data = await file.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(data) > AVATAR_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Picture must be smaller than {AVATAR_MAX_MB} MB")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "Upload a JPG, PNG or WEBP picture")
    img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    digest = hashlib.sha256(out.getvalue()).hexdigest()[:10]
    path = _avatar_dir() / f"{user.id}-{digest}.png"
    path.write_bytes(out.getvalue())
    old = user.avatar_path
    user.avatar_path = str(path)
    db.commit()
    if old and old != str(path):
        Path(old).unlink(missing_ok=True)
    return user


@router.delete("/me/avatar", response_model=UserOut)
def remove_avatar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.avatar_path:
        Path(user.avatar_path).unlink(missing_ok=True)
        user.avatar_path = None
        db.commit()
    return user


@router.get("/users/{khataz_id}", response_model=PublicUserOut)
def public_profile(khataz_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    target = db.scalar(select(User).where(User.khataz_id == kid.normalize(khataz_id)))
    if not target:
        raise HTTPException(404, "No one on Khataz has this ID")
    return target


@router.get("/users/{khataz_id}/avatar")
def avatar_image(khataz_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    target = db.scalar(select(User).where(User.khataz_id == kid.normalize(khataz_id)))
    if not target or not target.avatar_path or not Path(target.avatar_path).exists():
        raise HTTPException(404, "No picture")
    return FileResponse(target.avatar_path, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})
