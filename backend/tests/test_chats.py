"""Chat between Khataz users."""


def test_chat_flow(linked, make_user):
    abdul, marwan, _ = linked
    me = abdul.ok("get", "/api/me")["khataz_id"]
    them = marwan.ok("get", "/api/me")["khataz_id"]
    c = abdul.ok("post", "/api/chats", {"khataz_id": "@" + them.upper()})
    assert c["with"]["name"] == "Marwan Shahid" and c["last"] is None
    assert abdul.ok("post", "/api/chats", {"khataz_id": them})["id"] == c["id"]   # same chat
    assert marwan.ok("post", "/api/chats", {"khataz_id": me})["id"] == c["id"]    # from either side

    m1 = abdul.ok("post", f"/api/chats/{c['id']}/messages", {"body": "  Salam, milk bill is ready  "}, 201)
    assert m1["body"] == "Salam, milk bill is ready" and m1["mine"]
    assert marwan.ok("get", "/api/chats/unread") == {"unread": 1}
    lst = marwan.ok("get", "/api/chats")
    assert lst[0]["unread"] == 1 and lst[0]["last"]["body"] == "Salam, milk bill is ready" and not lst[0]["last"]["mine"]

    got = marwan.ok("get", f"/api/chats/{c['id']}/messages")
    assert [m["body"] for m in got["messages"]] == ["Salam, milk bill is ready"]
    assert marwan.ok("get", "/api/chats/unread") == {"unread": 0}
    marwan.ok("post", f"/api/chats/{c['id']}/messages", {"body": "Will pay by PayPal today"}, 201)
    new = abdul.ok("get", f"/api/chats/{c['id']}/messages?after_id={m1['id']}")
    assert [m["body"] for m in new["messages"]] == ["Will pay by PayPal today"] and new["read_up_to"] == m1["id"]


def test_chat_rules(linked, make_user):
    abdul, marwan, _ = linked
    me = abdul.ok("get", "/api/me")["khataz_id"]
    assert abdul.post("/api/chats", {"khataz_id": me}).status_code == 400
    assert abdul.post("/api/chats", {"khataz_id": "nobody_here"}).status_code == 404
    c = abdul.ok("post", "/api/chats", {"khataz_id": marwan.ok("get", "/api/me")["khataz_id"]})
    stranger = make_user("s@example.com", "Stranger")
    assert stranger.c.get(f"/api/chats/{c['id']}/messages", headers=stranger.h).status_code == 404
    assert stranger.post(f"/api/chats/{c['id']}/messages", {"body": "hi"}).status_code == 404
    assert abdul.post(f"/api/chats/{c['id']}/messages", {"body": "   "}).status_code == 422
