"""Private chat between Khataz users (found by their Khataz ID). The app polls for new messages."""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.khataz_id import normalize
from app.core.timeutil import utcnow
from app.models import ChatMessage, Conversation, User
from app.routers.auth import current_user

router = APIRouter(prefix="/api/chats", tags=["chats"])


class StartIn(BaseModel):
    khataz_id: str = Field(min_length=1, max_length=40)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Write a message")
        return v.strip()


def _person(u: User) -> dict:
    return {"id": u.id, "name": u.name, "khataz_id": u.khataz_id, "has_avatar": u.has_avatar}


def _message(m: ChatMessage, me: int) -> dict:
    return {"id": m.id, "body": m.body, "mine": m.sender_id == me, "created_at": m.created_at,
            "read": m.read_at is not None}


def _mine(db: Session, user: User, chat_id: int) -> Conversation:
    c = db.get(Conversation, chat_id)
    if not c or user.id not in (c.user_a_id, c.user_b_id):
        raise HTTPException(404, "Chat not found")
    return c


def _unread_q(user: User):
    return (select(func.count(ChatMessage.id)).join(Conversation, Conversation.id == ChatMessage.conversation_id)
            .where(or_(Conversation.user_a_id == user.id, Conversation.user_b_id == user.id),
                   ChatMessage.sender_id != user.id, ChatMessage.read_at.is_(None)))


def _summary(db: Session, c: Conversation, user: User) -> dict:
    other = db.get(User, c.other(user.id))
    last = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == c.id)
                     .order_by(ChatMessage.id.desc()).limit(1))
    unread = db.scalar(_unread_q(user).where(Conversation.id == c.id)) or 0
    return {"id": c.id, "with": _person(other), "unread": unread,
            "last": _message(last, user.id) if last else None,
            "updated_at": c.last_message_at or c.created_at}


@router.get("")
def list_chats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    chats = db.scalars(select(Conversation).where(
        or_(Conversation.user_a_id == user.id, Conversation.user_b_id == user.id))).all()
    out = [_summary(db, c, user) for c in chats]
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


@router.get("/unread")
def unread(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"unread": db.scalar(_unread_q(user)) or 0}


@router.post("")
def start_chat(data: StartIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Open (or create) the chat with the user who has this Khataz ID."""
    other = db.scalar(select(User).where(User.khataz_id == normalize(data.khataz_id)))
    if not other:
        raise HTTPException(404, "No Khataz user with that ID")
    if other.id == user.id:
        raise HTTPException(400, "That's your own Khataz ID")
    a, b = sorted((user.id, other.id))
    c = db.scalar(select(Conversation).where(and_(Conversation.user_a_id == a, Conversation.user_b_id == b)))
    if not c:
        c = Conversation(user_a_id=a, user_b_id=b)
        db.add(c)
        db.commit()
    return _summary(db, c, user)


@router.get("/{chat_id}/messages")
def messages(chat_id: int, after_id: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Messages after `after_id` (all of the last 200 when 0). Marks the other person's as read."""
    c = _mine(db, user, chat_id)
    q = select(ChatMessage).where(ChatMessage.conversation_id == c.id)
    if after_id:
        rows = db.scalars(q.where(ChatMessage.id > after_id).order_by(ChatMessage.id)).all()
    else:
        rows = list(reversed(db.scalars(q.order_by(ChatMessage.id.desc()).limit(200)).all()))
    now = utcnow()
    for m in db.scalars(q.where(ChatMessage.sender_id != user.id, ChatMessage.read_at.is_(None))):
        m.read_at = now
    db.commit()
    # read receipts for my own messages already on screen
    seen_up_to = db.scalar(select(func.max(ChatMessage.id)).where(
        ChatMessage.conversation_id == c.id, ChatMessage.sender_id == user.id, ChatMessage.read_at.is_not(None)))
    return {"chat": _summary(db, c, user), "messages": [_message(m, user.id) for m in rows],
            "read_up_to": seen_up_to or 0}


@router.post("/{chat_id}/messages", status_code=201)
def send(chat_id: int, data: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _mine(db, user, chat_id)
    m = ChatMessage(conversation_id=c.id, sender_id=user.id, body=data.body)
    db.add(m)
    c.last_message_at = utcnow()
    db.commit()
    return _message(m, user.id)
