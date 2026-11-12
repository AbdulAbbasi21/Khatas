from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.money import currency as check_currency
from app.models import Business, Contact, Relationship, User
from app.routers.auth import current_user
from app.schemas import BusinessIn, BusinessOut, ContactIn, ContactOut, LocalIdIn, RelationshipSummary
from app.services import links
from app.services.common import audit, owned_business
from app.services.views import summary

router = APIRouter(prefix="/api", tags=["businesses"])


def _check_local_id_free(db: Session, business_id: int, local_id: str | None, except_contact: int | None = None):
    """Your own IDs are unique within a business (any letter case)."""
    if not local_id:
        return
    clash = db.scalar(select(Contact).where(Contact.business_id == business_id,
                                            Contact.local_key == local_id.lower()))
    if clash and clash.id != except_contact:
        raise HTTPException(409, f"You already use the ID #{clash.local_id} for {clash.name} in this business")


@router.get("/businesses", response_model=list[BusinessOut])
def list_businesses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Business).where(Business.owner_id == user.id).order_by(Business.name)).all()


@router.post("/businesses", response_model=BusinessOut, status_code=201)
def create_business(data: BusinessIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    fields = data.model_dump()
    fields["default_currency"] = fields["default_currency"] or user.default_currency
    b = Business(owner_id=user.id, **fields)
    db.add(b)
    db.flush()
    audit(db, user, "business.created", "business", b.id, after=fields)
    db.commit()
    return b


@router.get("/businesses/{business_id}", response_model=BusinessOut)
def get_business(business_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned_business(db, user, business_id)


@router.patch("/businesses/{business_id}", response_model=BusinessOut)
def update_business(business_id: int, data: BusinessIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    b = owned_business(db, user, business_id)
    before = {"name": b.name, "category": b.category, "default_currency": b.default_currency}
    for k, v in data.model_dump().items():
        if v is not None or k == "category":
            setattr(b, k, v)
    audit(db, user, "business.updated", "business", b.id, before=before, after=data.model_dump())
    db.commit()
    return b


@router.get("/businesses/{business_id}/relationships", response_model=list[RelationshipSummary])
def business_relationships(business_id: int, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    b = owned_business(db, user, business_id)
    rels = db.scalars(select(Relationship).join(Contact).where(Relationship.business_id == b.id,
                                                               Relationship.archived_at.is_(None))
                      .order_by(Contact.name)).all()
    return [summary(db, r, user) for r in rels]


@router.post("/businesses/{business_id}/contacts", response_model=RelationshipSummary,
             status_code=201)
def add_person(business_id: int, data: ContactIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Add Person: creates the contact and its ledger (receivable or payable) in one step."""
    b = owned_business(db, user, business_id)
    fields = data.model_dump(exclude={"side", "currency", "khataz_id"})
    if data.khataz_id and not links.find_by_khataz_id(db, data.khataz_id):
        raise HTTPException(404, f"Nobody on Khataz has the ID @{data.khataz_id.lstrip('@').lower()}")
    _check_local_id_free(db, b.id, data.local_id)
    contact = Contact(business_id=b.id, local_key=data.local_id.lower() if data.local_id else None, **fields)
    db.add(contact)
    db.flush()
    rel = Relationship(business_id=b.id, contact_id=contact.id, side=data.side,
                       currency=data.currency or b.default_currency)
    db.add(rel)
    db.flush()
    audit(db, user, "contact.created", "contact", contact.id, rel.id,
          after=fields | {"side": data.side, "currency": rel.currency})
    if data.khataz_id:  # they're on Khataz: ask them to link (they still have to accept)
        links.invite(db, contact, user, rel.id, khataz_id=data.khataz_id)
    db.commit()
    return summary(db, rel, user)


class SideIn(BaseModel):
    side: str
    currency: str | None = None


@router.post("/contacts/{contact_id}/relationships", response_model=RelationshipSummary,
             status_code=201)
def add_other_side(contact_id: int, data: SideIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Same person, other direction (e.g. a customer who is also a supplier)."""
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    b = owned_business(db, user, contact.business_id)
    if data.side not in {"receivable", "payable"}:
        raise HTTPException(400, "side must be receivable or payable")
    if db.scalar(select(Relationship).where(Relationship.contact_id == contact.id,
                                            Relationship.side == data.side)):
        raise HTTPException(409, "This ledger already exists")
    rel = Relationship(business_id=b.id, contact_id=contact.id, side=data.side,
                       currency=check_currency(data.currency or b.default_currency))
    db.add(rel)
    db.flush()
    audit(db, user, "relationship.created", "relationship", rel.id, rel.id,
          after={"side": rel.side, "currency": rel.currency})
    db.commit()
    return summary(db, rel, user)


@router.put("/contacts/{contact_id}/local-id", response_model=ContactOut)
def set_local_id(contact_id: int, data: LocalIdIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Change your own ID for a person."""
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    owned_business(db, user, contact.business_id)
    _check_local_id_free(db, contact.business_id, data.local_id, except_contact=contact.id)
    before = {"local_id": contact.local_id}
    contact.local_id, contact.local_key = data.local_id, data.local_id.lower()
    for rel_id in db.scalars(select(Relationship.id).where(Relationship.contact_id == contact.id)):
        audit(db, user, "contact.local_id_changed", "contact", contact.id, rel_id,
              before=before, after={"local_id": data.local_id})
    db.commit()
    return contact


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: int, data: ContactIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    owned_business(db, user, contact.business_id)
    fields = data.model_dump(exclude={"side", "currency", "khataz_id"})
    _check_local_id_free(db, contact.business_id, data.local_id, except_contact=contact.id)
    fields["local_key"] = data.local_id.lower() if data.local_id else None
    before = {k: getattr(contact, k) for k in fields}
    for k, v in fields.items():
        setattr(contact, k, v)
    audit(db, user, "contact.updated", "contact", contact.id, before=before, after=fields)
    db.commit()
    return contact
