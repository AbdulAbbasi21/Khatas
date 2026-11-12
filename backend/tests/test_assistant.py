"""The Khataz assistant (Groq faked)."""

import pytest

from app.core import config
from app.services import assistant


@pytest.fixture
def ai(monkeypatch):
    """Queue the AI's next replies."""
    replies = []
    object.__setattr__(config.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(assistant, "_complete", lambda base, key, model, system, messages: replies.pop(0))
    yield replies
    object.__setattr__(config.settings, "groq_api_key", "")


def say(api, messages, draft=None):
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": m} for i, m in enumerate(messages)]
    return api.ok("post", "/api/ai/chat", {"messages": msgs, "draft": draft})


def test_help_question(linked, ai):
    abdul, _, _ = linked
    ai.append({"reply": "Open the person's record and press Subtract money.", "entry": None, "ready": False})
    r = say(abdul, ["how do I record a cash payment?"])
    assert r["reply"].startswith("Open the person's record") and r["draft"] is None and r["source"] == "Groq"


def test_entry_asks_for_the_missing_amount(linked, ai):
    abdul, _, rel_id = linked
    e = {"person": "marvan", "business": "Milk Supply", "side": "owes_me", "action": "add",
         "amount": None, "currency": None, "description": "5 kg milk", "method": None}
    ai.append({"reply": "How much was the milk?", "entry": e, "ready": False})
    r = say(abdul, ["marvan took 5 kg milk from milk supply"])
    assert not r["ready"] and r["missing"] == ["amount"] and r["reply"] == "How much was the milk?"
    assert r["draft"]["relationship_id"] == rel_id
    ai.append({"reply": "Adding USD 20 to Marwan Shahid for 5 kg milk.", "entry": e | {"amount": 20}, "ready": True})
    r = say(abdul, ["marvan took 5 kg milk from milk supply", "How much was the milk?", "20 dollars"])
    assert r["ready"] and r["draft"]["amount"] == "20.00" and r["draft"]["relationship_id"] == rel_id
    assert r["draft"]["records"] and r["draft"]["businesses"]


def test_server_still_asks_when_ai_says_ready_too_early(linked, ai):
    abdul, _, _ = linked
    ai.append({"reply": "Saving it.", "entry": {"person": "Marwan", "action": "add", "amount": None}, "ready": True})
    r = say(abdul, ["Marwan took milk"])
    assert not r["ready"] and r["reply"].startswith("How much was it")


def test_without_ai(linked):
    abdul, _, rel_id = linked
    r = say(abdul, ["what is a khataz id?"])
    assert "isn't available" in r["reply"] and r["draft"] is None
    r = say(abdul, ["marvan took 5 kg milk from milk supply"])
    assert r["reply"] == "How much was it for the 5 kg milk?" and not r["ready"]
    draft = {k: v for k, v in r["draft"].items() if k not in ("records", "businesses")}
    r = say(abdul, ["marvan took 5 kg milk from milk supply", r["reply"], "20"], draft=draft)
    assert r["ready"] and r["draft"]["amount"] == "20.00" and r["draft"]["relationship_id"] == rel_id


def test_ai_failure_falls_back(linked, monkeypatch):
    abdul, _, rel_id = linked
    object.__setattr__(config.settings, "groq_api_key", "test-key")
    try:
        def boom(*a):
            raise RuntimeError("HTTP 429")
        monkeypatch.setattr(assistant, "_complete", boom)
        r = say(abdul, ["Marwan took 5 kg milk for $20"])
        assert r["ready"] and r["source"] == "Built-in" and r["draft"]["relationship_id"] == rel_id
    finally:
        object.__setattr__(config.settings, "groq_api_key", "")


# ---------------------------------------------------------------- tasks (voice or typed)
def task(api, text):
    return api.ok("post", "/api/ai/chat", {"messages": [{"role": "user", "content": text}]})


def test_rules_undo_update_remove(linked):
    abdul, marwan, rel_id = linked
    abdul.ok("post", f"/api/relationships/{rel_id}/entries", {"type": "credit", "amount": "20", "description": "milk"}, 201)

    r = task(abdul, "undo marwan's last entry")
    a = r["action"]
    assert a["kind"] == "undo_entry" and a["entry"]["amount"] == "20.00" and a["entry"]["description"] == "milk"
    abdul.ok("post", f"/api/entries/{a['entry']['id']}/reverse", {"reason": a["reason"]}, 201)

    r = task(abdul, "set marwan balance to 80")
    a = r["action"]
    assert a["kind"] == "update_balance" and (a["balance"], a["to"]) == ("100.00", "80.00")

    r = task(abdul, "delete marwan's record")
    assert "action" not in r and "can't be removed" in r["reply"]

    abdul.ok("post", f"/api/relationships/{rel_id}/entries",
             {"type": "adjustment", "amount": "100", "increase": False, "description": "settled"}, 201)
    r = task(abdul, "delete marwan's record")
    assert r["action"]["kind"] == "remove_record"
    abdul.ok("post", f"/api/relationships/{rel_id}/archive")
    assert all(x["relationship_id"] != rel_id for x in task(abdul, "Marwan took 5 kg milk for $20")["draft"]["records"])


def test_ai_task(linked, ai):
    abdul, _, rel_id = linked
    ai.append({"reply": "Change Marwan's balance to USD 75?", "task": "update_balance",
               "target": {"person": "Marwan", "new_balance": 75, "reason": "Counted again"}, "ready": True})
    r = task(abdul, "marwan ka balance 75 kar do")
    assert r["action"]["kind"] == "update_balance" and r["action"]["to"] == "75.00"
    assert r["action"]["reason"] == "Counted again" and r["reply"] == "Change Marwan's balance to USD 75?"


def test_only_owner_tasks(linked):
    abdul, marwan, rel_id = linked
    r = task(marwan, "undo the last entry of milk supply")
    assert "action" not in r
    assert marwan.post(f"/api/relationships/{rel_id}/archive").status_code == 403
    assert abdul.post(f"/api/relationships/{rel_id}/archive").status_code == 409  # balance 100


def test_transcribe(linked, monkeypatch):
    abdul, _, _ = linked
    files = {"file": ("v.webm", b"fake-audio", "audio/webm")}
    assert abdul.c.post("/api/ai/transcribe", files=files, headers=abdul.h).status_code == 503
    object.__setattr__(config.settings, "groq_api_key", "k")
    try:
        from app.services import ai_entry
        monkeypatch.setattr(ai_entry, "transcribe", lambda audio, name, ct: "Marwan took 5 kg milk for 20 dollars")
        r = abdul.c.post("/api/ai/transcribe", files=files, headers=abdul.h)
        assert r.status_code == 200 and r.json()["text"].startswith("Marwan took")
    finally:
        object.__setattr__(config.settings, "groq_api_key", "")


# ---------------------------------------------------------------- off-topic
def test_off_topic_with_ai(linked, ai):
    abdul, _, _ = linked
    ai.append({"reply": "It's sunny today!", "task": "off_topic", "entry": None, "ready": False})
    r = say(abdul, ["what's the weather in Lahore?"])
    assert r["reply"].startswith("I can only help with Khataz") and r["draft"] is None


def test_off_topic_without_ai(linked):
    abdul, _, _ = linked
    for text in ["tell me a joke", "who won the cricket match", "write my essay on climate change"]:
        r = say(abdul, [text])
        assert r["reply"].startswith("I can only help with Khataz"), text
    assert say(abdul, ["hello"])["reply"].startswith("Hi!")
    # Khataz questions and entries are still handled
    assert "isn't available" in say(abdul, ["how do I invite someone?"])["reply"]
    assert say(abdul, ["Marwan took 5 kg milk for $20"])["ready"]
    assert not say(abdul, ["marvan took milk"])["reply"].startswith("I can only help")


# ---------------------------------------------------------------- showing records
def test_show_record_and_summary_without_ai(linked):
    abdul, marwan, rel_id = linked
    abdul.ok("post", f"/api/relationships/{rel_id}/entries", {"type": "credit", "amount": "20", "description": "milk"}, 201)
    for text in ["show me marvans record", "show me marvan's record", "how much does Marwan owe?", "open marwan khata"]:
        r = say(abdul, [text])
        rec = r["record"]
        assert rec["relationship_id"] == rel_id and rec["balance"] == "120.00", text
        assert r["reply"] == "Marwan Shahid owes you 120.00 USD."
        assert rec["recent"][0]["description"] == "milk" and rec["recent"][0]["sign"] == "+"
    s = say(abdul, ["who owes me?"])
    assert s["reply"] == "In total, people owe you 120.00 USD." and s["records_list"]["items"][0]["name"] == "Marwan Shahid"
    # the other side sees it from their view
    r = say(marwan, ["show my milk supply record"])
    assert r["record"]["relationship_id"] == rel_id and r["reply"].startswith("You owe Milk Supply")
    # an entry with a number is still an entry
    assert say(abdul, ["Marwan paid 10 by check"])["draft"]["action"] == "subtract"


def test_show_record_with_ai(linked, ai):
    abdul, _, rel_id = linked
    ai.append({"reply": "Go to Milk Supply and search for Marwan.", "task": "show_record",
               "target": {"person": "marvan"}, "ready": False})
    r = say(abdul, ["show marvans record"])
    assert r["record"]["relationship_id"] == rel_id and "search" not in r["reply"]
