"""Smart search through Elasticsearch, against a small in-memory fake of its REST API."""

import difflib
import json

import httpx
import pytest

from app.core.config import settings
from app.services import elastic


class FakeElastic:
    """Just enough of Elasticsearch: index create, delete_by_query, _bulk, _search (fuzzy-ish)."""

    def __init__(self):
        self.docs, self.index_made, self.searches = {}, False, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "HEAD":
            return httpx.Response(200 if self.index_made else 404)
        if req.method == "PUT":
            self.index_made = True
            return httpx.Response(200, json={"acknowledged": True})
        body = req.content.decode()
        if path.endswith("/_delete_by_query"):
            viewer = json.loads(body)["query"]["term"]["viewer"]
            self.docs = {k: d for k, d in self.docs.items() if d["viewer"] != viewer}
            return httpx.Response(200, json={"deleted": 1})
        if path == "/_bulk":
            lines = [json.loads(x) for x in body.strip().split("\n")]
            for meta, doc in zip(lines[::2], lines[1::2]):
                self.docs[meta["index"]["_id"]] = doc
            return httpx.Response(200, json={"errors": False})
        if path.endswith("/_search"):
            q = json.loads(body)
            self.searches.append(q)
            viewer = q["query"]["bool"]["filter"][0]["term"]["viewer"]
            needle = q["query"]["bool"]["should"][0]["term"]["local_id.raw"]["value"]
            hits = []
            for d in self.docs.values():
                if d["viewer"] != viewer:  # the privacy filter
                    continue
                words = " ".join([d["name"], d["local_id"], d["khataz_id"], d["business"]]).lower().split()
                close = any(w.startswith(needle) or difflib.SequenceMatcher(None, w, needle).ratio() >= 0.8
                            for w in words)
                lines = [x for x in d["entries"] if needle in x.lower()]
                if close or lines:
                    hit = {"_source": d}
                    if lines:
                        hit["highlight"] = {"entries": [lines[0]]}
                    hits.append(hit)
            return httpx.Response(200, json={"hits": {"hits": hits}})
        return httpx.Response(404)


@pytest.fixture
def fake_es(monkeypatch):
    fake = FakeElastic()
    object.__setattr__(settings, "elastic_url", "http://es.test:9200")
    monkeypatch.setattr(elastic, "_client", lambda: httpx.Client(base_url="http://es.test:9200",
                                                                transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(elastic, "_down_until", 0.0)
    monkeypatch.setattr(elastic, "_index_ready", False)
    yield fake
    object.__setattr__(settings, "elastic_url", "")


def test_basic_search_when_elastic_is_off(linked):
    abdul, _, _ = linked
    r = abdul.ok("get", "/api/search?q=marwan")
    assert r["engine"] == "basic" and r["records"][0]["other_party"] == "Marwan Shahid"
    assert abdul.ok("get", "/api/search?q=marvan")["records"] == []  # no typo help


def test_elastic_finds_typos_and_words_in_entries(linked, fake_es):
    abdul, marwan, rel_id = linked
    r = abdul.ok("get", "/api/search?q=marvan")
    assert r["engine"] == "elastic"
    assert [x["id"] for x in r["records"]] == [rel_id]
    r = abdul.ok("get", "/api/search?q=litres")
    assert r["records"][0]["id"] == rel_id and "Milk, 50 litres" in r["records"][0]["match"]
    # a new entry is searchable straight away
    abdul.ok("post", f"/api/relationships/{rel_id}/entries", {"type": "credit", "amount": "4", "description": "yogurt"}, 201)
    assert abdul.ok("get", "/api/search?q=yogurt")["records"][0]["id"] == rel_id
    # the query always filters on the person searching
    assert all(q["query"]["bool"]["filter"][0]["term"]["viewer"] for q in fake_es.searches)


def test_elastic_keeps_each_users_view_private(linked, fake_es, make_user):
    abdul, marwan, rel_id = linked
    abdul.ok("get", "/api/search?q=marwan")
    outsider = make_user("someone@example.com", "Some One")
    assert outsider.ok("get", "/api/search?q=marwan")["records"] == []
    # Abdul's private ID for Marwan is never in Marwan's own document
    marwan.ok("get", "/api/search?q=milk")
    mine = [d for d in fake_es.docs.values() if d["rel_id"] == rel_id]
    assert {d["local_id"] for d in mine} == {"T014", ""}


def test_falls_back_when_elastic_is_down(linked, monkeypatch):
    abdul, _, _ = linked
    object.__setattr__(settings, "elastic_url", "http://es.test:9200")
    monkeypatch.setattr(elastic, "_down_until", 0.0)

    def down(req):
        raise httpx.ConnectError("refused", request=req)
    monkeypatch.setattr(elastic, "_client", lambda: httpx.Client(base_url="http://es.test:9200",
                                                                transport=httpx.MockTransport(down)))
    try:
        r = abdul.ok("get", "/api/search?q=marwan")
        assert r["engine"] == "basic" and r["records"][0]["other_party"] == "Marwan Shahid"
    finally:
        object.__setattr__(settings, "elastic_url", "")
