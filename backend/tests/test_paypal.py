"""Log in with PayPal (verified sender) and the automatic PayPal check. PayPal itself is faked."""

from urllib.parse import parse_qs, urlparse

import pytest

from app.core import config
from app.services import paypal
from tests.test_claims import bal, claim

PAYER = {"user_id": "https://www.paypal.com/webapps/auth/identity/user/MARWAN1", "payer_id": "MARWANPAYER1",
         "email": "marwan.pp@example.com", "name": "Marwan Shahid", "verified": True}


@pytest.fixture
def paypal_on(monkeypatch):
    object.__setattr__(config.settings, "paypal_client_id", "test-client-id-123")
    object.__setattr__(config.settings, "paypal_client_secret", "test-secret-123")
    monkeypatch.setattr(paypal, "exchange_code", lambda code: dict(PAYER) if code == "good" else
                        (_ for _ in ()).throw(paypal.PayPalError("bad code")))
    yield
    object.__setattr__(config.settings, "paypal_client_id", "")
    object.__setattr__(config.settings, "paypal_client_secret", "")


def connect(api, code="good"):
    url = api.ok("get", "/api/paypal/connect-url")["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return api.c.post("/api/paypal/callback", json={"code": code, "state": state}), state


def test_connect_stores_verified_paypal(linked, paypal_on):
    abdul, marwan, rel_id = linked
    r, state = connect(marwan)
    assert r.status_code == 200, r.text
    st = marwan.ok("get", "/api/paypal/status")
    assert st["connected"]["email"] == "marwan.pp@example.com" and st["connected"]["verified"] is True
    # the state token can't be used to log in
    assert marwan.c.get("/api/me", headers={"Authorization": f"Bearer {state}"}).status_code == 401
    # the same PayPal account can't be connected to a second Khataz user
    assert connect(abdul)[0].status_code == 409
    assert marwan.c.post("/api/paypal/callback", json={"code": "good", "state": "junk"}).status_code == 400


def test_payer_must_connect_and_claim_carries_verified_sender(linked, paypal_on):
    abdul, marwan, rel_id = linked
    r = claim(marwan, rel_id)
    assert r.status_code == 400 and "Connect your PayPal" in r.json()["detail"]
    connect(marwan)
    c = claim(marwan, rel_id).json()
    assert c["payer_paypal_email"] == "marwan.pp@example.com"
    note = abdul.ok("get", "/api/notifications")
    assert any("marwan.pp@example.com" in n["message"] for n in (note["items"] if isinstance(note, dict) else note))


def _tx(tid, amount, email="marwan.pp@example.com", cur="USD", status="S", when="2026-11-03T10:20:00+0000"):
    return {"transaction_info": {"transaction_id": tid, "transaction_status": status,
                                 "transaction_initiation_date": when,
                                 "transaction_amount": {"currency_code": cur, "value": amount}},
            "payer_info": {"email_address": email, "account_id": "X"}}


def setup_autocheck(monkeypatch, abdul, rows):
    monkeypatch.setattr(paypal, "check_credentials", lambda cid, s: None)
    monkeypatch.setattr(paypal, "list_transactions", lambda cid, s, a, b: rows)
    st = abdul.ok("put", "/api/paypal/autocheck", {"client_id": "abdul-client-id-1", "secret": "abdul-secret-12345"})
    assert st["autocheck"]["enabled"]


def test_autocheck_confirms_matching_payment(linked, paypal_on, monkeypatch):
    abdul, marwan, rel_id = linked
    connect(marwan)
    c = claim(marwan, rel_id).json()
    rows = [_tx("OTHER000000000001", "30.00", email="someone@else.com"),   # wrong sender
            _tx("SMALL000000000001", "10.00"),                             # wrong amount
            _tx("GOOD0000000000001", "29.40")]                             # fee taken: within 95%
    setup_autocheck(monkeypatch, abdul, rows)
    assert abdul.c.get("/api/claims/0", headers=abdul.h).status_code in (404, 405)
    r = abdul.ok("post", "/api/paypal/autocheck/run")
    assert r == {"checked": 1, "confirmed": 1, "error": None}
    detail = abdul.ok("get", f"/api/relationships/{rel_id}")
    done = next(x for x in detail["claims"] if x["id"] == c["id"])
    assert done["state"] == "allocated" and done["auto_confirmed"] and done["recipient_txn_id"] == "GOOD0000000000001"
    assert bal(abdul, rel_id) == "70.60"
    # the same PayPal transaction can't confirm a second claim: the leftover 10.00 is used instead,
    # and only what actually arrived is credited
    c2 = claim(marwan, rel_id, txn="5TY05013RG002845N").json()
    assert abdul.ok("post", "/api/paypal/autocheck/run")["confirmed"] == 1
    done2 = next(x for x in abdul.ok("get", f"/api/relationships/{rel_id}")["claims"] if x["id"] == c2["id"])
    assert done2["recipient_txn_id"] == "SMALL000000000001" and done2["received_amount"] == "10.00"
    assert bal(abdul, rel_id) == "60.60"


def test_autocheck_ignores_claims_without_verified_sender(linked, monkeypatch):
    abdul, marwan, rel_id = linked
    claim(marwan, rel_id)  # PayPal login off: no verified sender
    setup_autocheck(monkeypatch, abdul, [_tx("GOOD0000000000001", "30.00")])
    assert abdul.ok("post", "/api/paypal/autocheck/run") == {"checked": 0, "confirmed": 0, "error": None}


def test_autocheck_reports_paypal_errors(linked, paypal_on, monkeypatch):
    abdul, marwan, rel_id = linked
    connect(marwan)
    claim(marwan, rel_id)
    setup_autocheck(monkeypatch, abdul, [])

    def boom(*a):
        raise paypal.PayPalError("Transaction search failed: nope")
    monkeypatch.setattr(paypal, "list_transactions", boom)
    r = abdul.ok("post", "/api/paypal/autocheck/run")
    assert r["confirmed"] == 0 and "nope" in r["error"]
    assert "nope" in abdul.ok("get", "/api/paypal/status")["autocheck"]["error"]
    abdul.ok("delete", "/api/paypal/autocheck")
    assert not abdul.ok("get", "/api/paypal/status")["autocheck"]["enabled"]


def test_autocheck_credits_what_paypal_shows_not_the_claim(linked, paypal_on, monkeypatch):
    """Payer claims 30 but sent 25: PayPal's 25 is credited and both sides are told."""
    abdul, marwan, rel_id = linked
    connect(marwan)
    c = claim(marwan, rel_id).json()
    assert c["claimed_amount"] == "30.00"
    setup_autocheck(monkeypatch, abdul, [_tx("LESS0000000000001", "25.00")])
    assert abdul.ok("post", "/api/paypal/autocheck/run")["confirmed"] == 1
    done = next(x for x in abdul.ok("get", f"/api/relationships/{rel_id}")["claims"] if x["id"] == c["id"])
    assert done["state"] == "allocated" and done["received_amount"] == "25.00"
    assert bal(abdul, rel_id) == "75.00"  # 100 - 25, not 100 - 30
    msgs = lambda u: [n["message"] for n in (lambda r: r["items"] if isinstance(r, dict) else r)(u.ok("get", "/api/notifications"))]
    assert any("not the 30.00 USD that was claimed" in m for m in msgs(marwan))
    assert any("Only 25.00 USD was credited" in m for m in msgs(abdul))


def test_manual_yes_received_checks_paypal_first(linked, paypal_on, monkeypatch):
    abdul, marwan, rel_id = linked
    connect(marwan)
    c = claim(marwan, rel_id).json()
    setup_autocheck(monkeypatch, abdul, [])
    # PayPal shows nothing yet: the claimed amount is NOT taken on trust
    r = abdul.c.post(f"/api/claims/{c['id']}/respond", json={"response": "received"}, headers=abdul.h)
    assert r.status_code == 409 and "doesn't show this payment" in r.json()["detail"]
    assert bal(abdul, rel_id) == "100.00"
    # the payment shows up (25, not the claimed 30): "Yes, received" credits PayPal's amount
    monkeypatch.setattr(paypal, "list_transactions", lambda cid, s, a, b: [_tx("LATE0000000000001", "25.00")])
    r = abdul.c.post(f"/api/claims/{c['id']}/respond", json={"response": "received"}, headers=abdul.h)
    assert r.status_code == 200, r.text
    assert r.json()["received_amount"] == "25.00" and r.json()["auto_confirmed"]
    assert bal(abdul, rel_id) == "75.00"


def test_manual_confirm_without_paypal_is_the_receivers_choice(linked, paypal_on, monkeypatch):
    abdul, marwan, rel_id = linked
    connect(marwan)
    c = claim(marwan, rel_id).json()
    setup_autocheck(monkeypatch, abdul, [])
    r = abdul.c.post(f"/api/claims/{c['id']}/respond",
                     json={"response": "received", "confirm_without_paypal": True}, headers=abdul.h)
    assert r.status_code == 200, r.text
    assert not r.json()["auto_confirmed"] and bal(abdul, rel_id) == "70.00"


def test_live_indicator(linked, paypal_on, monkeypatch):
    abdul, marwan, rel_id = linked
    assert abdul.ok("get", "/api/paypal/live")["enabled"] is False
    connect(marwan)
    claim(marwan, rel_id)
    setup_autocheck(monkeypatch, abdul, [])
    live = abdul.ok("get", "/api/paypal/live")
    assert live["enabled"] and live["waiting"] == 1 and live["checking_now"] is False
    seen = {}

    def slow(cid, s, a, b):  # while PayPal is being asked, the indicator says "checking"
        seen["during"] = abdul.ok("get", "/api/paypal/live")["checking_now"]
        return []
    monkeypatch.setattr(paypal, "list_transactions", slow)
    abdul.ok("post", "/api/paypal/autocheck/run")
    assert seen["during"] is True
    after = abdul.ok("get", "/api/paypal/live")
    assert after["checking_now"] is False and after["last_checked_at"]


def test_paypal_check_panel_shows_what_arrived(linked, paypal_on, monkeypatch):
    """Claim says 30, PayPal shows 25: the panel says so before and after confirming."""
    abdul, marwan, rel_id = linked
    connect(marwan)
    c = claim(marwan, rel_id).json()
    setup_autocheck(monkeypatch, abdul, [])
    look = abdul.ok("get", f"/api/claims/{c['id']}/paypal")
    assert look["verdict"] == "not_found" and look["payments"] == []
    monkeypatch.setattr(paypal, "list_transactions", lambda cid, s, a, b: [_tx("EIGHT000000000001", "25.00")])
    look = abdul.ok("get", f"/api/claims/{c['id']}/paypal")
    assert look["verdict"] == "different_amount" and "Only 25.00 USD arrived" in look["message"]
    assert look["payments"][0]["amount"] == "25.00" and look["payments"][0]["status"] == "completed"
    assert look["claimed_amount"] == "30.00"
    # reading PayPal changed nothing
    assert next(x for x in abdul.ok("get", f"/api/relationships/{rel_id}")["claims"] if x["id"] == c["id"])["state"] == "pending_confirmation"
    abdul.ok("post", "/api/paypal/autocheck/run")
    look = abdul.ok("get", f"/api/claims/{c['id']}/paypal")
    assert look["verdict"] == "linked_differs" and look["payments"][0]["note"] == "this payment"
    # only the receiver can look in their PayPal
    assert marwan.c.get(f"/api/claims/{c['id']}/paypal", headers=marwan.h).status_code == 403


def test_app_owner_account_is_always_on(linked, paypal_on, monkeypatch):
    """An account listed in PAYPAL_RECEIVER_EMAILS uses the app keys: on without entering anything."""
    from app.core.config import settings
    abdul, marwan, rel_id = linked
    assert abdul.ok("get", "/api/paypal/live")["enabled"] is False
    me = abdul.ok("get", "/api/me")["email"]
    object.__setattr__(settings, "paypal_receiver_emails", (me.lower(),))
    try:
        _app_owner_flow(abdul, marwan, rel_id, monkeypatch, settings)
    finally:
        object.__setattr__(settings, "paypal_receiver_emails", ())


def _app_owner_flow(abdul, marwan, rel_id, monkeypatch, settings):
    st = abdul.ok("get", "/api/paypal/status")["autocheck"]
    assert st["enabled"] and st["source"] == "app"
    connect(marwan)
    c = claim(marwan, rel_id).json()
    seen = {}

    def rows(cid, secret, a, b):
        seen["keys"] = (cid, secret)
        return [_tx("APPKEY00000000001", "30.00")]
    monkeypatch.setattr(paypal, "list_transactions", rows)
    assert abdul.ok("post", "/api/paypal/autocheck/run")["confirmed"] == 1
    assert seen["keys"] == (settings.paypal_client_id, settings.paypal_client_secret)
    assert abdul.ok("get", f"/api/claims/{c['id']}/paypal")["verdict"] == "linked_match"
