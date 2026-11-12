def balance(api, rel_id):
    return api.ok("get", f"/api/relationships/{rel_id}")["totals"]


def test_register_login_and_auth_required(client, make_user):
    make_user("a@example.com", "A", khataz_id="aaa")
    r = client.post("/api/auth/login", json={"email": "A@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope"}).status_code == 401
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/auth/register", json={"email": "a@example.com", "name": "A", "khataz_id": "bbb",
                                                   "password": "password123"}).status_code == 409


def test_balance_is_calculated_from_entries(make_user):
    u = make_user("owner@example.com", "Owner")
    b = u.ok("post", "/api/businesses", {"name": "Milk Supply", "default_currency": "PKR"}, 201)
    rel = u.ok("post", f"/api/businesses/{b['id']}/contacts",
               {"name": "Marwan's Grocery", "side": "receivable", "local_id": "T005"}, 201)
    assert rel["currency"] == "PKR"
    u.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "credit", "amount": "10000"}, 201)
    u.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "payment", "amount": "3000"}, 201)
    t = balance(u, rel["id"])
    assert t["balance"] == "7000.00" and t["credited"] == "10000.00" and t["paid"] == "3000.00"

    # unlinked contact: nothing to confirm
    entries = u.ok("get", f"/api/relationships/{rel['id']}")["entries"]
    assert {e["confirmation"] for e in entries} == {"not_required"}

    # dashboard groups by business and totals per currency
    d = u.ok("get", "/api/dashboard")
    assert d["owed_to_me"]["totals"] == {"PKR": "7000.00"}
    assert d["owed_to_me"]["groups"][0]["items"][0]["balance"] == "7000.00"
    assert d["i_owe"]["groups"][0]["items"] == []


def test_adjustment_and_reversal_never_edit_history(make_user):
    u = make_user("o@example.com", "O")
    b = u.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = u.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Ali", "side": "payable", "local_id": "T006"}, 201)
    e = u.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "credit", "amount": "50.10"}, 201)
    u.ok("post", f"/api/relationships/{rel['id']}/entries",
         {"type": "adjustment", "amount": "0.10", "increase": False}, 201)
    assert balance(u, rel["id"])["balance"] == "50.00"
    rev = u.ok("post", f"/api/entries/{e['id']}/reverse", {"reason": "Typed the wrong amount"}, 201)
    assert rev["delta"] == "-50.10" and rev["reverses_entry_id"] == e["id"]
    assert balance(u, rel["id"])["balance"] == "-0.10"
    assert u.post(f"/api/entries/{e['id']}/reverse", {"reason": "again"}).status_code == 409
    # adjustment without direction is refused
    assert u.post(f"/api/relationships/{rel['id']}/entries",
                  {"type": "adjustment", "amount": "1"}).status_code == 400
    actions = [a["action"] for a in u.ok("get", f"/api/relationships/{rel['id']}/audit")]
    assert "entry.reversed" in actions and "entry.credit" in actions


def test_other_users_cannot_see_records(make_user):
    owner = make_user("o@example.com", "O")
    stranger = make_user("s@example.com", "S")
    b = owner.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = owner.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Ali", "side": "receivable", "local_id": "T007"}, 201)
    assert stranger.get(f"/api/relationships/{rel['id']}").status_code == 404
    assert stranger.get(f"/api/businesses/{b['id']}").status_code == 404
    assert stranger.post(f"/api/relationships/{rel['id']}/entries",
                         {"type": "credit", "amount": "5"}).status_code == 404


def test_linking_and_two_sided_view(linked):
    abdul, marwan, rel_id = linked
    view = marwan.ok("get", f"/api/relationships/{rel_id}")
    assert view["summary"]["perspective"] == "i_owe" and view["summary"]["role"] == "counterparty"
    assert view["totals"]["balance"] == "100.00"
    assert view["contact"] is None  # the owner's private contact notes stay private
    d = marwan.ok("get", "/api/dashboard")
    assert d["i_owe"]["groups"][0]["shared"] is True
    assert d["i_owe"]["totals"] == {"USD": "100.00"}
    # the debtor's own entries are only proposals: they don't change the balance yet
    e = marwan.ok("post", f"/api/relationships/{rel_id}/entries", {"type": "payment", "amount": "100"}, 201)
    assert e["status"] == "pending"
    assert marwan.ok("get", f"/api/relationships/{rel_id}")["totals"]["balance"] == "100.00"


def test_accept_and_dispute(linked):
    abdul, marwan, rel_id = linked
    entry = marwan.ok("get", f"/api/relationships/{rel_id}")["entries"][0]
    assert entry["confirmation"] == "unconfirmed"
    assert marwan.ok("get", "/api/dashboard")["counts"]["entries_to_accept"] == 1

    e2 = abdul.ok("post", f"/api/relationships/{rel_id}/entries", {"type": "credit", "amount": "40"}, 201)
    marwan.ok("post", f"/api/entries/{entry['id']}/accept")
    d = marwan.ok("post", f"/api/entries/{e2['id']}/dispute", {"reason": "I never got this"}, 201)
    t = balance(abdul, rel_id)
    assert t["balance"] == "100.00" and t["disputed"] == "40.00"  # disputed doesn't count

    assert marwan.post(f"/api/disputes/{d['id']}/resolve", {"resolution": "kept"}).status_code == 403
    abdul.ok("post", f"/api/disputes/{d['id']}/resolve", {"resolution": "voided", "note": "My mistake"})
    assert balance(abdul, rel_id)["balance"] == "100.00"
    assert any("cancelled" in n["message"] for n in marwan.ok("get", "/api/notifications"))


def test_other_side_records_goods_owner_confirms(make_user):
    """Marwan owes Ali's shop 20. Ali takes goods worth 10 from Marwan; Marwan records it.
    The balance only drops to 10 after Ali (the owner) confirms."""
    ali = make_user("ali@example.com", "Ali Khan")
    marwan = make_user("marwan2@example.com", "Marwan")
    b = ali.ok("post", "/api/businesses", {"name": "Ali's Shop"}, 201)
    rel = ali.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Marwan", "side": "receivable", "local_id": "T008"}, 201)
    ali.ok("post", f"/api/relationships/{rel['id']}/invite", {"email": "marwan2@example.com"}, 201)
    marwan.ok("post", f"/api/invites/{marwan.ok('get', '/api/invites')[0]['id']}/accept")
    ali.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "credit", "amount": "20"}, 201)

    e = marwan.ok("post", f"/api/relationships/{rel['id']}/entries",
                  {"type": "goods", "amount": "10", "description": "Rice, 5 kg"}, 201)
    assert e["status"] == "pending" and e["delta"] == "-10.00"
    t = ali.ok("get", f"/api/relationships/{rel['id']}")["totals"]
    assert t["balance"] == "20.00" and t["pending"] == "-10.00"   # nothing changes yet

    # Ali is told and has it waiting in Review
    assert any("only after you confirm" in n["message"] for n in ali.ok("get", "/api/notifications"))
    assert ali.ok("get", "/api/dashboard")["counts"]["entries_to_confirm"] == 1
    assert ali.ok("get", "/api/review")["entries_to_confirm"][0]["id"] == e["id"]

    # Marwan can't confirm his own entry, and Marwan's view shows the same pending entry
    assert marwan.post(f"/api/entries/{e['id']}/confirm").status_code == 403

    ali.ok("post", f"/api/entries/{e['id']}/confirm")
    assert ali.ok("get", f"/api/relationships/{rel['id']}")["totals"]["balance"] == "10.00"
    assert marwan.ok("get", f"/api/relationships/{rel['id']}")["totals"]["balance"] == "10.00"
    assert any("confirmed your entry" in n["message"] for n in marwan.ok("get", "/api/notifications"))
    assert ali.post(f"/api/entries/{e['id']}/confirm").status_code == 409  # only once

    # a rejected proposal never touches the balance
    e2 = marwan.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "goods", "amount": "5"}, 201)
    assert ali.post(f"/api/entries/{e2['id']}/reject", {"reason": ""}).status_code == 422
    r = ali.ok("post", f"/api/entries/{e2['id']}/reject", {"reason": "I never took this"})
    assert r["status"] == "rejected"
    assert ali.ok("get", f"/api/relationships/{rel['id']}")["totals"]["balance"] == "10.00"
    actions = [a["action"] for a in ali.ok("get", f"/api/relationships/{rel['id']}/audit")]
    assert {"entry.goods.proposed", "entry.confirmed", "entry.rejected"} <= set(actions)


def test_owner_can_record_goods_taken_too(make_user):
    u = make_user("o2@example.com", "Owner")
    b = u.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = u.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Marwan", "side": "receivable", "local_id": "T009"}, 201)
    u.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "credit", "amount": "20"}, 201)
    e = u.ok("post", f"/api/relationships/{rel['id']}/entries", {"type": "goods", "amount": "10"}, 201)
    assert e["status"] == "active"
    assert u.ok("get", f"/api/relationships/{rel['id']}")["totals"]["balance"] == "10.00"


def test_record_moves_sides_when_the_balance_flips(linked):
    """Marwan owes 100; Abdul takes goods worth 110 from him: now Abdul owes Marwan 10."""
    abdul, marwan, rel_id = linked
    abdul.ok("post", f"/api/relationships/{rel_id}/entries",
             {"type": "payment", "amount": "110", "description": "Goods: 2 crates of eggs"}, 201)
    s = abdul.ok("get", f"/api/relationships/{rel_id}")["summary"]
    assert (s["balance"], s["direction"], s["amount"], s["perspective"]) == ("-10.00", "i_owe", "10.00", "owed_to_me")
    d = abdul.ok("get", "/api/dashboard")
    assert d["i_owe"]["totals"] == {"USD": "10.00"} and d["owed_to_me"]["totals"] == {}
    assert any(i["id"] == rel_id for g in d["i_owe"]["groups"] for i in g["items"])
    assert not any(i["id"] == rel_id for g in d["owed_to_me"]["groups"] for i in g["items"])
    # Marwan sees the mirror image: Milk Supply owes him 10
    m = marwan.ok("get", "/api/dashboard")
    assert m["owed_to_me"]["totals"] == {"USD": "10.00"} and m["i_owe"]["totals"] == {}
    # the assistant says it the right way round
    r = abdul.ok("post", "/api/ai/chat", {"messages": [{"role": "user", "content": "show marwan's record"}]})
    assert r["reply"] == "You owe Marwan Shahid 10.00 USD."
    # adding 10 settles it and it goes back to its usual side
    abdul.ok("post", f"/api/relationships/{rel_id}/entries", {"type": "credit", "amount": "10", "description": "Milk"}, 201)
    s = abdul.ok("get", f"/api/relationships/{rel_id}")["summary"]
    assert (s["balance"], s["direction"]) == ("0.00", "owed_to_me")


# ---------------------------------------------------------------- 24-hour cancel window
def _age_entry(entry_id, hours):
    """Pretend an entry was made `hours` ago."""
    from datetime import timedelta
    from app.core.database import get_db
    from app.main import app
    from app.models import LedgerEntry
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    e = db.get(LedgerEntry, entry_id)
    e.created_at = e.created_at - timedelta(hours=hours)
    db.commit()
    gen.close()


def test_other_side_can_cancel_within_a_day(linked):
    abdul, marwan, rel_id = linked
    e = abdul.ok("post", f"/api/relationships/{rel_id}/entries",
                 {"type": "credit", "amount": "20", "description": "Milk"}, 201)
    assert e["confirmation"] == "unconfirmed" and e["cancel_until"]
    note = marwan.ok("get", "/api/notifications")
    items = note["items"] if isinstance(note, dict) else note
    assert any("cancel it within 24 hours" in n["message"] for n in items)
    assert abdul.post(f"/api/entries/{e['id']}/cancel", {"reason": "x"}).status_code == 403  # not the owner
    assert marwan.post(f"/api/entries/{e['id']}/cancel", {"reason": ""}).status_code == 422
    c = marwan.ok("post", f"/api/entries/{e['id']}/cancel", {"reason": "I didn't take milk that day"})
    assert c["status"] == "cancelled" and c["cancel_until"] is None
    assert abdul.ok("get", f"/api/relationships/{rel_id}")["summary"]["balance"] == "100.00"
    note = abdul.ok("get", "/api/notifications")
    items = note["items"] if isinstance(note, dict) else note
    assert any("cancelled your entry" in n["message"] and "didn't take milk" in n["message"] for n in items)
    assert marwan.post(f"/api/entries/{e['id']}/cancel", {"reason": "again"}).status_code == 409  # only once


def test_after_a_day_the_entry_is_final(linked):
    abdul, marwan, rel_id = linked
    e = abdul.ok("post", f"/api/relationships/{rel_id}/entries",
                 {"type": "credit", "amount": "20", "description": "Milk"}, 201)
    _age_entry(e["id"], 25)
    detail = marwan.ok("get", f"/api/relationships/{rel_id}")
    entry = next(x for x in detail["entries"] if x["id"] == e["id"])
    assert entry["confirmation"] == "auto_accepted" and entry["cancel_until"] is None
    assert marwan.post(f"/api/entries/{e['id']}/cancel", {"reason": "too late"}).status_code == 409
    assert marwan.post(f"/api/entries/{e['id']}/accept").status_code == 409
    assert detail["summary"]["balance"] == "120.00"
    assert all(x["id"] != e["id"] for x in marwan.ok("get", "/api/review")["entries_to_accept"])
