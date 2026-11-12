"""Smarter search with Elasticsearch (optional).

When ELASTIC_URL is set and Elasticsearch answers, the search box uses it:
- typo-tolerant names and IDs ("marvan" finds Marwan),
- full-text search inside ledger entries ("milk", "5 kg"), with the matching line shown,
- results ranked by relevance.

Privacy: every document belongs to ONE viewer and holds only what that viewer already sees
(their own name for the person, their own ID, their own notes are never mixed across users).
Searches always filter on the viewer. If Elasticsearch is off or down, Khataz falls back to
the basic database search, so the app never breaks because of it.
"""

import json
import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import LedgerEntry, Relationship, User

log = logging.getLogger(__name__)
INDEX = "khataz-records"
_down_until = 0.0  # after a failure, don't retry for a minute (keeps search fast)
_index_ready = False

MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {"properties": {
        "viewer": {"type": "keyword"},
        "rel_id": {"type": "integer"},
        "name": {"type": "text"},
        "local_id": {"type": "text", "fields": {"raw": {"type": "keyword", "normalizer": "lowercase"}}},
        "khataz_id": {"type": "text", "fields": {"raw": {"type": "keyword", "normalizer": "lowercase"}}},
        "business": {"type": "text"},
        "company": {"type": "text"},
        "entries": {"type": "text"},
    }},
}
# keyword normalizer used above
MAPPING["settings"]["analysis"] = {"normalizer": {"lowercase": {"type": "custom", "filter": ["lowercase"]}}}


def enabled() -> bool:
    return bool(settings.elastic_url) and time.monotonic() >= _down_until


def _mark_down(e: Exception) -> None:
    global _down_until, _index_ready
    _down_until, _index_ready = time.monotonic() + 60, False
    log.warning("Elasticsearch unavailable, using basic search for a minute: %s", e)


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.elastic_url.rstrip("/"), timeout=3.0,
                        headers={"Content-Type": "application/json"})


def _ensure_index(c: httpx.Client) -> None:
    global _index_ready
    if _index_ready:
        return
    r = c.head(f"/{INDEX}")
    if r.status_code == 404:
        r = c.put(f"/{INDEX}", content=json.dumps(MAPPING))
        if r.status_code >= 400 and "resource_already_exists" not in r.text:
            r.raise_for_status()
    elif r.status_code >= 400:
        r.raise_for_status()
    _index_ready = True


def _docs(db: Session, user: User, rels: list[Relationship], summaries: dict[int, object]) -> list[dict]:
    """One document per record this user can see, with only what they see."""
    ids = [r.id for r in rels]
    lines: dict[int, list[str]] = {i: [] for i in ids}
    if ids:
        rows = db.execute(select(LedgerEntry.relationship_id, LedgerEntry.description, LedgerEntry.amount,
                                 LedgerEntry.currency)
                          .where(LedgerEntry.relationship_id.in_(ids), LedgerEntry.status != "voided")
                          .order_by(LedgerEntry.occurred_at.desc())).all()
        for rid, desc, amount, cur in rows:
            if desc and len(lines[rid]) < 100:
                lines[rid].append(f"{desc} · {amount} {cur}")
    out = []
    for rel in rels:
        s = summaries[rel.id]
        out.append({
            "viewer": str(user.id), "rel_id": rel.id, "name": s.other_party,
            "local_id": s.local_id or "", "khataz_id": s.other_khataz_id or "",
            "business": s.business_name,
            "company": (rel.contact.company or "") if rel.business.owner_id == user.id else "",
            "entries": lines[rel.id],
        })
    return out


def _sync(c: httpx.Client, user: User, docs: list[dict]) -> None:
    """Refresh this user's documents (small: one per record they can see)."""
    c.post(f"/{INDEX}/_delete_by_query", params={"refresh": "true", "conflicts": "proceed"},
           content=json.dumps({"query": {"term": {"viewer": str(user.id)}}})).raise_for_status()
    if not docs:
        return
    body = "".join(json.dumps({"index": {"_index": INDEX, "_id": f"{d['viewer']}-{d['rel_id']}"}}) + "\n"
                   + json.dumps(d) + "\n" for d in docs)
    r = c.post("/_bulk", params={"refresh": "wait_for"}, content=body,
               headers={"Content-Type": "application/x-ndjson"})
    r.raise_for_status()
    if r.json().get("errors"):
        raise RuntimeError("bulk indexing reported errors")


def query_body(user: User, text: str) -> dict:
    needle = text.lstrip("@#")
    return {
        "size": 30,
        "query": {"bool": {
            "filter": [{"term": {"viewer": str(user.id)}}],
            "should": [
                {"term": {"local_id.raw": {"value": needle.lower(), "boost": 20}}},
                {"term": {"khataz_id.raw": {"value": needle.lower(), "boost": 20}}},
                {"multi_match": {"query": needle, "type": "phrase_prefix", "boost": 4,
                                 "fields": ["name^3", "local_id^3", "khataz_id^3", "business", "company"]}},
                {"multi_match": {"query": needle, "fuzziness": "AUTO", "prefix_length": 1, "boost": 2,
                                 "fields": ["name^3", "local_id^2", "khataz_id^2", "business", "company"]}},
                {"match": {"entries": {"query": needle, "fuzziness": "AUTO"}}},
            ],
            "minimum_should_match": 1,
        }},
        "highlight": {"pre_tags": [""], "post_tags": [""],
                      "fields": {"entries": {"fragment_size": 90, "number_of_fragments": 1}}},
    }


def search(db: Session, user: User, text: str, rels: list[Relationship],
           summaries: dict[int, object]) -> list[tuple[int, str | None]] | None:
    """[(relationship id, matching entry line or None)] best first; None = use the basic search."""
    if not enabled():
        return None
    try:
        with _client() as c:
            _ensure_index(c)
            _sync(c, user, _docs(db, user, rels, summaries))
            r = c.post(f"/{INDEX}/_search", content=json.dumps(query_body(user, text)))
            r.raise_for_status()
            hits = r.json()["hits"]["hits"]
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as e:
        _mark_down(e)
        return None
    out = []
    for h in hits:
        src = h["_source"]
        snippet = (h.get("highlight", {}).get("entries") or [None])[0]
        out.append((src["rel_id"], snippet))
    return out
