"""Khataz ID, profile picture, search, adding a person by Khataz ID."""
import io

from PIL import Image


def png_bytes(w=800, h=500, color=(0, 112, 224)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def test_khataz_id_chosen_at_signup_is_unique_and_validated(client, make_user):
    u = make_user("hadi@example.com", "Abdul Hadi", khataz_id="Abdul.Hadi")
    assert u.user["khataz_id"] == "abdul.hadi"  # stored lowercase

    def reg(kid, email="x@example.com"):
        return client.post("/api/auth/register", json={"email": email, "name": "X", "khataz_id": kid,
                                                       "password": "password123"})
    assert reg("ABDUL.HADI").status_code == 409            # unique whatever the case
    for bad in ["ab", "1abc", "has space", "a..b", "abc.", "admin", "x" * 21]:
        assert reg(bad).status_code == 422, bad
    assert client.get("/api/auth/khataz-id", params={"id": "@Abdul.Hadi"}).json()["available"] is False
    r = client.get("/api/auth/khataz-id", params={"id": "free_name"}).json()
    assert r == {"khataz_id": "free_name", "available": True, "reason": None}
    assert client.get("/api/auth/khataz-id", params={"id": "9x"}).json()["reason"] == "Use 3 to 20 characters"
    # can't be changed later
    u.patch("/api/me", {"khataz_id": "something.else"})
    assert u.ok("get", "/api/me")["khataz_id"] == "abdul.hadi"


def test_profile_picture_upload_and_remove(make_user):
    u = make_user("pic@example.com", "Pic")
    other = make_user("viewer@example.com", "Viewer")
    r = u.c.post("/api/me/avatar", headers=u.h, files={"file": ("me.png", png_bytes(), "image/png")})
    assert r.status_code == 200 and r.json()["has_avatar"] and r.json()["avatar_version"]
    img = other.get(f"/api/users/{u.user['khataz_id']}/avatar")
    assert img.status_code == 200
    assert Image.open(io.BytesIO(img.content)).size == (256, 256)  # cropped to a square
    assert u.c.post("/api/me/avatar", headers=u.h, files={"file": ("x.txt", b"nope", "text/plain")}).status_code == 400
    assert u.c.get(f"/api/users/{u.user['khataz_id']}/avatar").status_code == 401  # login needed
    u.c.delete("/api/me/avatar", headers=u.h)
    assert other.get(f"/api/users/{u.user['khataz_id']}/avatar").status_code == 404


def test_search_records_by_name_and_people_by_khataz_id(make_user):
    abdul = make_user("abdul@example.com", "Abdul", khataz_id="abdul")
    marwan = make_user("marwan@example.com", "Marwan Shahid", khataz_id="marwan.s")
    b = abdul.ok("post", "/api/businesses", {"name": "Milk Supply"}, 201)
    abdul.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Ahmed's Shop", "side": "receivable", "local_id": "T001"}, 201)

    r = abdul.ok("get", "/api/search?q=ahmed")
    assert [x["other_party"] for x in r["records"]] == ["Ahmed's Shop"] and r["people"] == []
    # other users are found by Khataz ID only, never by name
    assert abdul.ok("get", "/api/search?q=Marwan Shahid")["people"] == []
    p = abdul.ok("get", "/api/search?q=@marw")["people"]
    assert p[0]["khataz_id"] == "marwan.s" and p[0]["name"] == "Marwan Shahid" and p[0]["record_ids"] == []
    assert "email" not in p[0]
    assert abdul.ok("get", "/api/search?q=abdul")["people"] == []  # not yourself


def test_add_person_by_khataz_id_invites_them(make_user):
    abdul = make_user("abdul@example.com", "Abdul", khataz_id="abdul")
    marwan = make_user("marwan@example.com", "Marwan Shahid", khataz_id="marwan.s")
    b = abdul.ok("post", "/api/businesses", {"name": "Milk Supply"}, 201)
    rel = abdul.ok("post", f"/api/businesses/{b['id']}/contacts",
                   {"name": "Marwan", "side": "receivable", "khataz_id": "@Marwan.S"}, 201)
    detail = abdul.ok("get", f"/api/relationships/{rel['id']}")
    assert detail["pending_invite_email"] == "@marwan.s"  # the owner sees the ID, not the email
    inv = marwan.ok("get", "/api/invites")
    assert len(inv) == 1 and inv[0]["invited_email"] is None and "@abdul" in inv[0]["invited_by"]
    marwan.ok("post", f"/api/invites/{inv[0]['id']}/accept")
    s = abdul.ok("get", f"/api/relationships/{rel['id']}")["summary"]
    assert s["linked"] and s["other_khataz_id"] == "marwan.s"
    assert marwan.ok("get", f"/api/relationships/{rel['id']}")["summary"]["other_khataz_id"] == "abdul"
    # search now finds the shared record by his ID
    assert abdul.ok("get", "/api/search?q=marwan.s")["people"][0]["record_ids"] == [rel["id"]]

    assert abdul.post(f"/api/businesses/{b['id']}/contacts",
                      {"name": "Ghost", "side": "receivable", "khataz_id": "nobody.here"}).status_code == 404


def test_invite_existing_contact_by_khataz_id(make_user):
    abdul = make_user("abdul@example.com", "Abdul", khataz_id="abdul")
    make_user("ali@example.com", "Ali", khataz_id="ali.k")
    b = abdul.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = abdul.ok("post", f"/api/businesses/{b['id']}/contacts", {"name": "Ali", "side": "payable", "local_id": "T002"}, 201)
    assert abdul.post(f"/api/relationships/{rel['id']}/invite", {"khataz_id": "abdul"}).status_code == 400
    assert abdul.post(f"/api/relationships/{rel['id']}/invite", {}).status_code == 422
    abdul.ok("post", f"/api/relationships/{rel['id']}/invite", {"khataz_id": "ali.k"}, 201)


def test_owner_can_undo_an_invite(make_user):
    abdul = make_user("abdul@example.com", "Abdul", khataz_id="abdul")
    marwan = make_user("marwan@example.com", "Marwan", khataz_id="marwan.s")
    stranger = make_user("x@example.com", "X", khataz_id="xxx")
    b = abdul.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    rel = abdul.ok("post", f"/api/businesses/{b['id']}/contacts",
                   {"name": "Marwan", "side": "receivable", "khataz_id": "marwan.s"}, 201)
    inv_id = abdul.ok("get", f"/api/relationships/{rel['id']}")["pending_invite_id"]
    assert inv_id and len(marwan.ok("get", "/api/invites")) == 1

    assert stranger.post(f"/api/invites/{inv_id}/cancel").status_code == 404   # only the owner
    assert marwan.post(f"/api/invites/{inv_id}/cancel").status_code == 404     # not the invitee either
    abdul.ok("post", f"/api/invites/{inv_id}/cancel")

    assert marwan.ok("get", "/api/invites") == []                               # gone for Marwan
    assert marwan.post(f"/api/invites/{inv_id}/accept").status_code == 404      # can't accept it now
    assert any("withdrew the invite" in n["message"] for n in marwan.ok("get", "/api/notifications"))
    d = abdul.ok("get", f"/api/relationships/{rel['id']}")
    assert d["pending_invite_id"] is None and not d["summary"]["linked"]
    assert abdul.post(f"/api/invites/{inv_id}/cancel").status_code == 409      # only once
    assert "contact.invite_cancelled" in [a["action"] for a in abdul.ok("get", f"/api/relationships/{rel['id']}/audit")]
    # a new invite can be sent afterwards
    abdul.ok("post", f"/api/relationships/{rel['id']}/invite", {"khataz_id": "marwan.s"}, 201)
    assert len(marwan.ok("get", "/api/invites")) == 1


def test_own_id_for_people_in_my_records(make_user):
    """Each person needs their Khataz ID or my own ID; my IDs are unique in a business."""
    abdul = make_user("abdul@example.com", "Abdul", khataz_id="abdul")
    marwan = make_user("marwan@example.com", "Marwan", khataz_id="marwan.s")
    milk = abdul.ok("post", "/api/businesses", {"name": "Milk Supply"}, 201)
    shop = abdul.ok("post", "/api/businesses", {"name": "Shop"}, 201)
    url = f"/api/businesses/{milk['id']}/contacts"

    assert abdul.post(url, {"name": "Nobody", "side": "receivable"}).status_code == 422      # needs one of the two
    assert abdul.post(url, {"name": "Bad", "side": "receivable", "local_id": "has space"}).status_code == 422
    r = abdul.ok("post", url, {"name": "Ahmed", "side": "receivable", "local_id": "#CUST-001"}, 201)
    assert r["local_id"] == "CUST-001"
    dup = abdul.post(url, {"name": "Ali", "side": "payable", "local_id": "cust-001"})       # any case
    assert dup.status_code == 409 and "Ahmed" in dup.json()["detail"]
    # the same ID in another business is fine (e.g. the same person there)
    abdul.ok("post", f"/api/businesses/{shop['id']}/contacts", {"name": "Ahmed", "side": "receivable", "local_id": "CUST-001"}, 201)
    # Khataz ID alone is enough
    k = abdul.ok("post", url, {"name": "Marwan", "side": "receivable", "khataz_id": "marwan.s"}, 201)
    assert k["local_id"] is None

    # search by my own ID
    found = abdul.ok("get", "/api/search?q=%23cust-001")["records"]
    assert {x["business_name"] for x in found} == {"Milk Supply", "Shop"}

    # rename it; still unique
    contact_id = abdul.ok("get", f"/api/relationships/{r['id']}")["contact"]["id"]
    abdul.c.put(f"/api/contacts/{contact_id}/local-id", json={"local_id": "AHMED"}, headers=abdul.h).raise_for_status()
    assert abdul.ok("get", f"/api/relationships/{r['id']}")["summary"]["local_id"] == "AHMED"
    clash = abdul.ok("post", url, {"name": "Z", "side": "receivable", "local_id": "Z1"}, 201)
    zid = abdul.ok("get", f"/api/relationships/{clash['id']}")["contact"]["id"]
    assert abdul.c.put(f"/api/contacts/{zid}/local-id", json={"local_id": "ahmed"}, headers=abdul.h).status_code == 409

    # only the owner sees their IDs: Marwan links (he was added by Khataz ID), Abdul names him M-7
    marwan.ok("post", f"/api/invites/{marwan.ok('get', '/api/invites')[0]['id']}/accept")
    mid = abdul.ok("get", f"/api/relationships/{k['id']}")["contact"]["id"]
    abdul.c.put(f"/api/contacts/{mid}/local-id", json={"local_id": "M-7"}, headers=abdul.h).raise_for_status()
    assert abdul.ok("get", f"/api/relationships/{k['id']}")["summary"]["local_id"] == "M-7"
    assert marwan.ok("get", f"/api/relationships/{k['id']}")["summary"]["local_id"] is None
    assert marwan.c.put(f"/api/contacts/{mid}/local-id", json={"local_id": "X"}, headers=marwan.h).status_code == 404


def test_database_down_gives_a_clear_message(client):
    from sqlalchemy.exc import OperationalError
    from app.core.database import get_db
    from app.main import app

    def broken():
        raise OperationalError("connect", {}, Exception("connection refused"))
        yield
    app.dependency_overrides[get_db] = broken
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 503 and "docker compose up -d" in r.json()["detail"]


def test_forgot_and_reset_password(client, make_user, monkeypatch):
    import re
    from app.routers import auth
    sent = []
    monkeypatch.setattr(auth, "send_email", lambda to, subject, text, html=None: sent.append((to, text)))
    make_user("pw@example.com", "Pat")
    assert client.post("/api/auth/forgot", json={"email": "nobody@example.com"}).json() == {"ok": True}
    assert sent == []  # no account: same answer, nothing sent
    client.post("/api/auth/forgot", json={"email": "PW@example.com"})
    token = re.search(r"token=(\S+)", sent[0][1]).group(1)
    assert client.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code == 422
    r = client.post("/api/auth/reset", json={"token": token, "password": "brand-new-pass"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "pw@example.com"
    assert client.post("/api/auth/reset", json={"token": token, "password": "another-pass1"}).status_code == 400  # used once
    assert client.post("/api/auth/login", json={"email": "pw@example.com", "password": "brand-new-pass"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": "x" * 40, "password": "brand-new-pass"}).status_code == 400
