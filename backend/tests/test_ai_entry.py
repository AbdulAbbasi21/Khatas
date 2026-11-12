"""Type an entry: built-in rules, AI provider, fallback, and the endpoint."""

import pytest

from app.core import config
from app.services import ai_entry as ai

RECORDS = [
    {"relationship_id": 1, "name": "Marwan Shahid", "local_id": "CUST-001", "khataz_id": "marwan"},
    {"relationship_id": 2, "name": "Faizan Ali", "local_id": "CUST-002", "khataz_id": "faizan"},
    {"relationship_id": 3, "name": "Packaging Supplier", "local_id": "SUP-001", "khataz_id": None},
    {"relationship_id": 4, "name": "Ali Raza", "local_id": "CUST-003", "khataz_id": None},
]


@pytest.mark.parametrize("text, action, amount, currency, rel, desc", [
    ("Marwan took 5 kg milk for $20", "add", "20.00", "USD", 1, "5 kg milk"),
    ("Marwan paid 10 cash", "subtract", "10.00", None, 1, None),
    ("CUST-001 took 3 boxes for 45 dollars", "add", "45.00", "USD", 1, "3 boxes"),
    ("Faizan liya 2 kg ghee 1200", "add", "1200.00", None, 2, "2 kg ghee"),
    ("Ali ne 500 rupees jama karaye", "subtract", "500.00", "PKR", None, None),  # two Alis: ask
    ("@faizan returned 15 via PayPal", "subtract", "15.00", None, 2, None),
    ("Bought 200 boxes on credit from Packaging Supplier 30", "add", "30.00", None, 3, "200 boxes"),
])
def test_rules(text, action, amount, currency, rel, desc):
    d = ai.parse(text, RECORDS, "USD")
    assert (d["action"], d["amount"], d["currency"], d["relationship_id"], d["description"], d["source"]) == \
        (action, amount, currency, rel, desc, "Built-in")


@pytest.fixture
def groq_on():
    object.__setattr__(config.settings, "groq_api_key", "test-key")
    yield
    object.__setattr__(config.settings, "groq_api_key", "")


def test_ai_provider_used_and_rules_fill_gaps(groq_on, monkeypatch):
    monkeypatch.setattr(ai, "_call", lambda base, key, model, prompt: {
        "person": "Faizan", "action": "subtract", "amount": 25, "currency": None,
        "description": "Part payment", "method": "Bank"})
    d = ai.parse("faizan sent 25 by bank, part payment", RECORDS, "USD")
    assert d["source"] == "Groq" and d["action"] == "subtract" and d["amount"] == "25.00"
    assert d["relationship_id"] == 2 and d["description"] == "Part payment" and d["method"] == "Bank"


def test_falls_back_to_rules_when_ai_fails(groq_on, monkeypatch):
    def boom(*a):
        raise RuntimeError("HTTP 429: rate limited")
    monkeypatch.setattr(ai, "_call", boom)
    d = ai.parse("Marwan took 5 kg milk for $20", RECORDS, "USD")
    assert d["source"] == "Built-in" and d["amount"] == "20.00" and d["relationship_id"] == 1


def test_endpoint_uses_my_records(linked):
    abdul, marwan, rel_id = linked
    d = abdul.ok("post", "/api/ai/entry", {"text": "Marwan took 2 litres milk for 4 dollars"})
    assert d["relationship_id"] == rel_id and d["amount"] == "4.00" and d["action"] == "add"
    assert d["records"][0]["name"] == "Marwan Shahid"
    # the counterparty sees the business, not the contact
    d2 = marwan.ok("post", "/api/ai/entry", {"text": "paid Milk Supply 10 cash"})
    assert d2["relationship_id"] == rel_id and d2["action"] == "subtract" and d2["method"] == "Cash"


def test_new_person_gets_a_new_record(linked):
    abdul, marwan, rel_id = linked
    d = abdul.ok("post", "/api/ai/entry", {"text": "Usman took 2 litres milk for 300 from Milk Supply"})
    biz = d["businesses"][0]
    assert d["business_id"] == biz["business_id"] and d["matches"] == [] and d["new_person"] == "Usman"
    assert d["side"] == "receivable" and d["amount"] == "300.00" and d["description"] == "2 litres milk"
    r = abdul.ok("post", "/api/ai/save", {"new_record": {"business_id": d["business_id"], "name": "Usman",
                                                         "side": "receivable", "local_id": None},
                                          "action": "add", "amount": "300", "description": "2 litres milk"}, 201)
    new = abdul.ok("get", f"/api/relationships/{r['relationship_id']}")
    assert new["summary"]["other_party"] == "Usman" and new["summary"]["balance"] == "300.00"
    assert new["summary"]["local_id"] == biz["next_ids"]["receivable"]
    # the same ID can't be used twice
    clash = abdul.post("/api/ai/save", {"new_record": {"business_id": d["business_id"], "name": "Other",
                                                       "side": "receivable", "local_id": new["summary"]["local_id"]},
                                        "action": "add", "amount": "5"})
    assert clash.status_code == 409


def test_typo_finds_the_existing_record(linked):
    abdul, marwan, rel_id = linked
    d = abdul.ok("post", "/api/ai/entry", {"text": "marvan took 5 kg milk from milk supply"})
    assert d["relationship_id"] == rel_id and d["new_person"] == "Marvan" and d["amount"] is None
    assert d["description"] == "5 kg milk"
    abdul.ok("post", "/api/ai/save", {"relationship_id": rel_id, "action": "add", "amount": "12.50",
                                      "description": "5 kg milk"}, 201)
    assert abdul.ok("get", f"/api/relationships/{rel_id}")["summary"]["balance"] == "112.50"


def test_save_checks(linked, make_user):
    abdul, marwan, rel_id = linked
    assert abdul.post("/api/ai/save", {"action": "add", "amount": "5"}).status_code == 400
    biz = abdul.ok("post", "/api/ai/entry", {"text": "x took 1"})["businesses"][0]["business_id"]
    other = make_user("z@example.com", "Zed")
    r = other.post("/api/ai/save", {"new_record": {"business_id": biz, "name": "A", "side": "receivable"},
                                    "action": "add", "amount": "5"})
    assert r.status_code == 404


def test_open_business_is_used_when_none_is_named():
    from app.services.ai_entry import resolve
    biz = [{"business_id": 1, "name": "Milk Supply", "currency": "USD"},
           {"business_id": 2, "name": "Electronics Store", "currency": "EUR"}]
    recs = [{"relationship_id": 10, "business_id": 1, "business_name": "Milk Supply", "name": "Ali Khan",
             "local_id": "CUST-001", "khataz_id": None, "balance": "0", "currency": "USD"},
            {"relationship_id": 20, "business_id": 2, "business_name": "Electronics Store", "name": "Ali Khan",
             "local_id": "CUST-009", "khataz_id": None, "balance": "0", "currency": "EUR"}]
    # same name in both businesses: the open one (2) wins
    d = resolve("Ali Khan took 5", None, "Built-in", recs, "USD", biz, focus_business_id=2)
    assert d["business_id"] == 2 and d["relationship_id"] == 20
    # a new person goes to the open business, not the first one
    d = resolve("Zara took 5", None, "Built-in", recs, "USD", biz, focus_business_id=2)
    assert d["business_id"] == 2 and d["relationship_id"] is None
    # naming a business still beats the open one
    d = resolve("Ali Khan took 5 at milk supply", None, "Built-in", recs, "USD", biz, focus_business_id=2)
    assert d["business_id"] == 1 and d["relationship_id"] == 10
    # someone only in the other business is still found
    d = resolve("Ali Khan took 5", None, "Built-in", recs[:1], "USD", biz, focus_business_id=2)
    assert d["relationship_id"] == 10
