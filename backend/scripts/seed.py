"""
Demo data for the hackathon story. Run from the backend folder AFTER `alembic upgrade head`:

    python -m scripts.seed

To start over with fresh demo data:

    alembic downgrade base
    alembic upgrade head
    python -m scripts.seed

Creates (password for all: password123):
  abdul@khataz.demo   @abdul   owns "Milk Supply" (USD) and "Electronics Store" (EUR)
  marwan@khataz.demo  @marwan  customer of Milk Supply, linked to his account
  faizan@khataz.demo  @faizan  customer of Electronics Store, linked; sometimes pays for Marwan
plus several customers and suppliers who aren't on Khataz, weeks of history, an entry and a
PayPal payment waiting for Abdul, and a chat. It goes through the real API, so every rule applies.
"""

import io
import sys
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models import User

PASSWORD = "password123"
client = TestClient(app)
NOW = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)

# Seeding must not depend on the scanner or PayPal settings of this computer.
object.__setattr__(settings, "scanner_enabled", False)
object.__setattr__(settings, "paypal_client_id", "")
object.__setattr__(settings, "smtp_host", "")


def ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def user(email, name, tz, khataz_id, currency):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": PASSWORD,
                                                "timezone": tz, "khataz_id": khataz_id,
                                                "default_currency": currency})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def call(method, url, headers, json=None, files=None):
    r = client.request(method, url, headers=headers, json=json, files=files)
    if r.status_code >= 400:
        sys.exit(f"{method} {url} failed: {r.status_code} {r.text}")
    return r.json()


def entry(h, rel, kind, amount, description, days_ago, **extra):
    call("POST", f"/api/relationships/{rel['id']}/entries", h,
         {"type": kind, "amount": amount, "description": description, "occurred_at": ago(days_ago), **extra})


def person(h, biz, name, side, local_id, **extra):
    return call("POST", f"/api/businesses/{biz['id']}/contacts", h,
                {"name": name, "side": side, "local_id": local_id, **extra})


def link(owner, rel, guest, khataz_id):
    call("POST", f"/api/relationships/{rel['id']}/invite", owner, {"khataz_id": khataz_id})
    inv = call("GET", "/api/invites", guest)[0]  # the one just sent
    call("POST", f"/api/invites/{inv['id']}/accept", guest)


def demo_receipt_image() -> bytes:
    """A plain placeholder picture, clearly marked as demo data (not a copy of a PayPal screen)."""
    img = Image.new("RGB", (600, 820), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 600, 90], fill=(0, 48, 135))
    d.text((30, 32), "DEMO RECEIPT - Khataz sample data", fill="white")
    lines = ["Payment sent", "", "Amount: 30.00 USD", "To: Abdul Hadi (Milk Supply)", "From: Marwan Shahid",
             "Transaction ID: 7KD21934AB5678012", f"Date: {(NOW - timedelta(days=1)):%d %b %Y}",
             "Status: Completed", "", "Sample image for the demo.", "Upload a real sandbox receipt to try it."]
    for i, line in enumerate(lines):
        d.text((40, 130 + i * 44), line, fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main():
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "abdul@khataz.demo")):
            print("Demo data already exists. Log in as abdul@khataz.demo / password123")
            print("To start over: alembic downgrade base; alembic upgrade head; python -m scripts.seed")
            return

    abdul = user("abdul@khataz.demo", "Abdul Hadi", "Asia/Karachi", "abdul", "USD")
    marwan = user("marwan@khataz.demo", "Marwan Shahid", "Europe/London", "marwan", "USD")
    faizan = user("faizan@khataz.demo", "Faizan Ahmed", "America/New_York", "faizan", "EUR")

    milk = call("POST", "/api/businesses", abdul, {"name": "Milk Supply", "category": "Dairy",
                                                   "default_currency": "USD"})
    shop = call("POST", "/api/businesses", abdul, {"name": "Electronics Store", "category": "Retail",
                                                   "default_currency": "EUR"})

    # ---- Milk Supply: customers and suppliers
    m = person(abdul, milk, "Marwan Shahid", "receivable", "CUST-001", email="marwan@khataz.demo",
               company="Marwan's Grocery Store")
    a = person(abdul, milk, "Ahmed's Shop", "receivable", "CUST-002", phone="+44 7700 900123")
    s = person(abdul, milk, "Sara's Bakery", "receivable", "CUST-003")
    t = person(abdul, milk, "Tea Corner Cafe", "receivable", "CUST-004")
    p = person(abdul, milk, "Packaging Supplier", "payable", "SUP-001")
    f = person(abdul, milk, "Green Valley Farm", "payable", "SUP-002")

    link(abdul, m, marwan, "marwan")
    entry(abdul, m, "credit", "60.00", "Milk, 30 litres", 24)
    entry(abdul, m, "credit", "40.00", "Yogurt, 20 tubs", 17)
    entry(abdul, m, "payment", "50.00", "Cash", 12)
    entry(abdul, m, "credit", "50.00", "Milk, 25 litres", 6)
    entry(abdul, m, "credit", "30.00", "Butter, 10 packs", 2)

    entry(abdul, a, "credit", "45.00", "Milk, 30 litres", 20)
    entry(abdul, a, "credit", "25.00", "Cream, 5 litres", 9)
    entry(abdul, a, "payment", "20.00", "Bank transfer", 4)
    entry(abdul, s, "credit", "90.00", "Milk, 60 litres", 15)
    entry(abdul, s, "payment", "90.00", "PayPal", 8)
    entry(abdul, s, "credit", "35.00", "Butter, 12 packs", 3)
    entry(abdul, t, "credit", "18.00", "Milk, 12 litres", 5)

    entry(abdul, p, "credit", "80.00", "Bottles and caps", 21)
    entry(abdul, p, "payment", "40.00", "Bank transfer", 10)
    entry(abdul, f, "credit", "300.00", "Raw milk, 400 litres", 14)
    entry(abdul, f, "payment", "200.00", "Bank transfer", 7)
    entry(abdul, f, "credit", "150.00", "Raw milk, 200 litres", 1)

    # ---- Electronics Store (EUR)
    u = person(abdul, shop, "Faizan Ahmed", "receivable", "CUST-001", email="faizan@khataz.demo")
    c = person(abdul, shop, "Usman Electronics Repair", "receivable", "CUST-002")
    d = person(abdul, shop, "Electronics Distributor", "payable", "SUP-001")
    link(abdul, u, faizan, "faizan")
    entry(abdul, u, "credit", "120.00", "Headphones", 18)
    entry(abdul, u, "payment", "20.00", "Cash", 11)
    entry(abdul, u, "credit", "65.00", "Phone case and charger", 3)
    entry(abdul, c, "credit", "210.00", "Spare screens x6", 13)
    entry(abdul, c, "payment", "100.00", "Bank transfer", 6)
    entry(abdul, d, "credit", "250.00", "Phone chargers x50", 16)
    entry(abdul, d, "payment", "150.00", "Bank transfer", 9)

    # ---- Waiting for Abdul (Review page)
    # Marwan says he returned two crates: his entry waits for Abdul to confirm
    call("POST", f"/api/relationships/{m['id']}/entries", marwan,
         {"type": "payment", "amount": "8.00", "description": "Returned 2 empty crates"})
    # Marwan paid 30 USD by PayPal and shared the receipt
    scan = call("POST", f"/api/relationships/{m['id']}/claims/scan", marwan,
                files={"file": ("demo-receipt.png", demo_receipt_image(), "image/png")})
    call("POST", f"/api/relationships/{m['id']}/claims", marwan,
         {"amount": "30.00", "currency": "USD", "sender_txn_id": "7KD21934AB5678012",
          "paid_at_local": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
          "image_hash": scan["image_hash"], "note": "Part of this week's bill"})

    # ---- A chat between Abdul and Marwan
    chat = call("POST", "/api/chats", abdul, {"khataz_id": "marwan"})
    for who, text in [(abdul, "Salam Marwan! This week's milk and butter are added to your khata."),
                      (marwan, "Walaikum salam. Got it, thanks. I'll send 30 dollars by PayPal today."),
                      (marwan, "Sent. I uploaded the receipt in Khataz."),
                      (abdul, "Thanks! I'll check my PayPal and confirm.")]:
        call("POST", f"/api/chats/{chat['id']}/messages", who, {"body": text})

    # history: entries older than a day were "made" back then, so their cancel window has closed
    from app.models import LedgerEntry
    from app.services import ledger
    with SessionLocal() as db:
        for e in db.scalars(select(LedgerEntry).where(LedgerEntry.occurred_at < NOW - timedelta(days=1))):
            e.created_at = e.occurred_at
        db.commit()
        ledger.auto_accept_expired(db)

    print("Demo data created. Log in at http://localhost:5173 with:")
    print("  abdul@khataz.demo  / password123   (business owner: 2 businesses, 9 people)")
    print("  marwan@khataz.demo / password123   (customer of Milk Supply)")
    print("  faizan@khataz.demo / password123   (customer of Electronics Store)")


if __name__ == "__main__":
    main()
