"""Currency chosen at sign-up; inviting someone to Khataz by email."""
from app.services import links


def test_currency_chosen_at_signup_is_used_everywhere(client):
    r = client.post("/api/auth/register", json={"email": "eur@example.com", "name": "Eva", "khataz_id": "eva",
                                                "password": "password123", "default_currency": "eur"})
    assert r.status_code == 201 and r.json()["user"]["default_currency"] == "EUR"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    b = client.post("/api/businesses", json={"name": "Bakery"}, headers=h).json()
    assert b["default_currency"] == "EUR"                       # business takes the user's currency
    rel = client.post(f"/api/businesses/{b['id']}/contacts", json={"name": "Ali", "side": "receivable", "local_id": "T010"}, headers=h).json()
    assert rel["currency"] == "EUR"                             # no currency asked per person
    assert client.post("/api/auth/register", json={"email": "x@example.com", "name": "X", "khataz_id": "xxx",
                                                   "password": "password123", "default_currency": "ABC"}).status_code == 422
    client.patch("/api/me", json={"default_currency": "GBP"}, headers=h)
    assert client.get("/api/me", headers=h).json()["default_currency"] == "GBP"


def test_email_invite_sends_an_email(make_user, monkeypatch):
    sent = []
    monkeypatch.setattr(links, "send_email", lambda to, subject, text, html=None: sent.append((to, subject, text)) or True)
    owner = make_user("owner@example.com", "Abdul Hadi", khataz_id="abdul")
    b = owner.ok("post", "/api/businesses", {"name": "Milk Supply"}, 201)
    rel = owner.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Ahmed", "side": "receivable", "local_id": "T011"}, 201)

    r = owner.ok("post", f"/api/relationships/{rel['id']}/invite", {"email": "Ahmed@Example.com"}, 201)
    assert r["email_sent"] is True and r["account_exists"] is False
    to, subject, text = sent[0]
    assert to == "ahmed@example.com" and "Abdul Hadi" in subject
    assert "/register?email=ahmed%40example.com" in text and "Milk Supply" in text
    d = owner.ok("get", f"/api/relationships/{rel['id']}")
    assert d["pending_invite_email"] == "ahmed@example.com" and d["contact"]["email"] == "ahmed@example.com"

    # when Ahmed signs up with that email, the invite is waiting for him
    ahmed = make_user("ahmed@example.com", "Ahmed", khataz_id="ahmed")
    inv = ahmed.ok("get", "/api/invites")
    assert len(inv) == 1 and inv[0]["business_name"] == "Milk Supply"
    ahmed.ok("post", f"/api/invites/{inv[0]['id']}/accept")
    assert owner.ok("get", f"/api/relationships/{rel['id']}")["summary"]["linked"]


def test_email_invite_to_existing_user_links_to_notifications(make_user, monkeypatch):
    sent = []
    monkeypatch.setattr(links, "send_email", lambda to, subject, text, html=None: sent.append(text) or True)
    owner = make_user("owner@example.com", "Owner", khataz_id="owner")
    make_user("member@example.com", "Member", khataz_id="member")
    b = owner.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = owner.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Member", "side": "payable", "local_id": "T012"}, 201)
    r = owner.ok("post", f"/api/relationships/{rel['id']}/invite", {"email": "member@example.com"}, 201)
    assert r["account_exists"] is True and "/notifications" in sent[0]


def test_email_not_configured_still_creates_invite(make_user):
    owner = make_user("owner@example.com", "Owner", khataz_id="owner")
    b = owner.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = owner.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Zed", "side": "receivable", "local_id": "T013"}, 201)
    r = owner.ok("post", f"/api/relationships/{rel['id']}/invite", {"email": "zed@example.com"}, 201)
    assert r["email_sent"] is False and r["email_configured"] is False and "register?email=" in r["link"]
