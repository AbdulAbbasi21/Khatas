"""Tests run on a throwaway SQLite database; exchange rates are faked."""

import os
import re
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["SCANNER_ENABLED"] = "false"
os.environ["PAYPAL_SYNC_SECONDS"] = "0"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.services import fx

RATES_TO_USD = {"USD": Decimal("1"), "EUR": Decimal("1.08"), "GBP": Decimal("1.27"),
                "PKR": Decimal("0.0036")}


def fake_fetch(base, quote, on):
    if base not in RATES_TO_USD or quote not in RATES_TO_USD:
        raise fx.FxUnavailable("no rate")
    return RATES_TO_USD[base] / RATES_TO_USD[quote], "test rates"


@pytest.fixture
def client(monkeypatch, tmp_path):
    pg = os.getenv("TEST_DATABASE_URL")  # e.g. a throwaway PostgreSQL database
    if pg:
        engine = create_engine(pg)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(fx, "fetch_rate", fake_fetch)
    from app.core import config
    monkeypatch.setattr(config.settings.__class__, "storage_dir", str(tmp_path), raising=False)
    object.__setattr__(config.settings, "storage_dir", str(tmp_path))
    yield TestClient(app)
    app.dependency_overrides.clear()


class Api:
    """Small helper: one logged-in user."""

    def __init__(self, client, email, name, tz="UTC", khataz_id=None):
        self.c = client
        if khataz_id is None:  # derive a valid one from the email: o2@x.com -> user o2
            local = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())
            khataz_id = local if len(local) >= 3 and local[0].isalpha() else f"user{local}"
        r = client.post("/api/auth/register", json={"email": email, "name": name, "khataz_id": khataz_id,
                                                    "password": "password123", "timezone": tz})
        assert r.status_code == 201, r.text
        self.user = r.json()["user"]
        self.h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def get(self, url, **kw):
        return self.c.get(url, headers=self.h, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self.h, **kw)

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self.h)

    def put(self, url, json=None):
        return self.c.put(url, json=json, headers=self.h)

    def delete(self, url, json=None):
        return self.c.delete(url, headers=self.h)

    def ok(self, method, url, json=None, status=200):
        r = self.get(url) if method == "get" else getattr(self, method)(url, json=json)
        assert r.status_code == status, f"{url}: {r.status_code} {r.text}"
        return r.json()


@pytest.fixture
def make_user(client):
    return lambda email, name, tz="UTC", khataz_id=None: Api(client, email, name, tz, khataz_id)


@pytest.fixture
def linked(make_user):
    """Abdul owns 'Milk Supply'; Marwan owes it 100 USD and has linked his account."""
    abdul = make_user("abdul@example.com", "Abdul Hadi", "Asia/Karachi")
    marwan = make_user("marwan@example.com", "Marwan Shahid", "Europe/London")
    biz = abdul.ok("post", "/api/businesses", {"name": "Milk Supply", "default_currency": "USD"}, 201)
    rel = abdul.ok("post", f"/api/businesses/{biz['id']}/contacts",
                   {"name": "Marwan Shahid", "side": "receivable", "email": "marwan@example.com", "local_id": "T014"}, 201)
    abdul.ok("post", f"/api/relationships/{rel['id']}/invite", {"email": "marwan@example.com"}, 201)
    inv = marwan.ok("get", "/api/invites")[0]
    marwan.ok("post", f"/api/invites/{inv['id']}/accept")
    abdul.ok("post", f"/api/relationships/{rel['id']}/entries",
             {"type": "credit", "amount": "100.00", "description": "Milk, 50 litres"}, 201)
    return abdul, marwan, rel["id"]
