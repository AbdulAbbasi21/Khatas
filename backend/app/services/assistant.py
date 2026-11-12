"""
The Khataz assistant: answers questions about using Khataz, and turns a conversation like
  "marvan took 5 kg milk from gujjar milk shop" -> "how much was it?" -> "20 dollars"
into an entry draft. It never saves anything: the user checks the draft and saves it.

Uses the same free providers as ai_entry (Groq, then OpenRouter). Without them, entries still
work with the built-in reader, and help questions get a short "not available" answer.
"""

import json
import logging
import re
from decimal import Decimal

from app.services import ai_entry

log = logging.getLogger("khataz.assistant")

GUIDE = """Khataz is a shared credit book (khata) for businesses. It RECORDS debts and payments;
it never moves money. Main ideas and where to find them:
- Dashboard: totals "Money owed to me" / "Money I owe", your businesses (blue bars). Click a
  business to see its people in two tabs: Money Owed to Me (customers) and Money I Owe (suppliers).
- Add business: "+ Add business" on the dashboard (name, category, currency).
- Add person: open a business -> "Add person". Give their Khataz ID (@name, if they use Khataz)
  and/or Your ID (your own code like CUST-001, unique in that business).
- A person's record: buttons Add money (they owe more), Subtract money (a payment; write the
  payment method), Update money (correct the balance, a reason is required), PayPal payment.
  Entries are never deleted; mistakes are fixed with Reverse or Update money. Newest entries on top.
  If a customer gives you more than they owed (money or goods), the balance goes the other way and
  the record moves to Money I Owe by itself ("You owe Marwan 10"); it moves back when settled.
- Shared records: if the other person is on Khataz and accepts the invite ("Add Khataz ID"),
  both see the same balance. Entries they add wait until the owner confirms. The owner's entries
  can be accepted or cancelled by the other person within 24 hours (they're told by a
  notification); a cancel takes effect at once and the owner is told. After 24 hours it's final. "Invite to Khataz" emails someone who isn't on Khataz yet.
- PayPal payments: the payer clicks "I paid by PayPal" and uploads the PayPal receipt screenshot.
  Khataz checks it is a real PayPal receipt (shop receipts "processed by PayPal" are refused),
  reads the amount, transaction ID and date, and sends it with the image to the receiver, who
  confirms ("Yes, received" / "Different amount" / "Not received"). Only then does the balance change.
  Small differences (fees, under 5%) are fine; bigger ones go to Review.
- Profile -> PayPal account: "Connect with PayPal" proves your real PayPal email; payers must
  connect before sending receipts, and receivers see "verified".
- Profile -> Automatic payment check: a receiver adds their PayPal app Client ID + Secret; Khataz
  then confirms receipts by itself when the payment shows up in their PayPal (can take minutes).
- Review page: payments to confirm or review, entries waiting for you, disputes, invites.
- Notifications page and emails (turn emails off in Settings).
- Chats (top menu / bottom bar on phones): private messages with other Khataz users. Start one by
  typing their @Khataz ID on the Chats page, or press "Message" on a shared record. "Seen" shows
  when they've read your last message.
- Typing an entry: write e.g. "Marwan took 5 kg milk for $20" in the box on the dashboard or here.
- Voice: tap the microphone in this assistant and speak (English or Urdu). It can add entries,
  set a balance ("set Marwan's balance to 80"), undo the last entry, or remove a record whose
  balance is zero. Every change is shown first and only happens after you tap Confirm.
- Search (top bar): find people by name, #your ID or @Khataz ID.
- Settings: name, currency, time zone, country, email notifications. Profile: picture, Khataz ID.
- Remove a record: on a person's record, "Remove record" appears when the balance is zero. The
  history is kept. Forgot password: "Forgot password?" on the log-in page emails a reset link.
- Currencies: each record has one currency; PayPal payments in other currencies are converted
  with the day's rate."""

SYSTEM = """You are the Khataz assistant inside the Khataz web app. Be brief and friendly
(1-4 short sentences, plain text, no markdown tables). You do two things:

1. Help: answer questions about using Khataz, using only this guide. If something isn't in the
   guide, say you're not sure.
   OFF TOPIC: if the message has nothing to do with Khataz, the user's records, entries, payments
   or this app (e.g. weather, jokes, homework, news, coding, general chat), set "task": "off_topic"
   and don't answer it. Greetings and thanks are fine: reply briefly and offer help with Khataz.
{guide}

2. Tasks on records (the user may speak; expect informal text and typos):
   - "update_balance": set a person's balance to a new amount ("Marwan's balance should be 80").
   - "undo_entry": undo / delete / reverse the last entry on a person's record.
   - "remove_record": delete / remove a person's record (only possible when the balance is zero).
   - "show_record": show / open / check a person's record, balance or entries ("show me Marwan's
     record", "how much does Marwan owe?"). Khataz shows it right here in the chat.
   - "show_summary": a list of balances ("who owes me?", "show all my records", "what do I owe?").
     Put "owed_to_me" or "i_owe" in target.filter when the user means one side.
   NEVER tell the user to go and search or open a page themselves: use show_record / show_summary.
   For these, fill "target" (person, business, new_balance, reason). If the person is missing, ask.
   Entries are never really deleted: undo adds a reversing entry. Say so if asked.

3. Entries: when the user describes money or goods given/taken/paid, build ONE entry from the
   conversation since the last "Saved" or "Done" message:
   person (as written), business (one of the user's businesses if named), side ("owes_me" for a
   customer, "i_owe" for a supplier), action ("add" = debt grows, "subtract" = a payment / return),
   amount (money, not quantities like 5 kg), currency (3-letter or null), description (short, what
   it was for), method (payments only: Cash, Bank, PayPal...).
   If the amount or the person is missing, ask for that ONE thing in "reply". When you have both,
   set "ready": true and say in "reply" what will be saved, and that they can check it before saving.

The user's businesses: {businesses}
The user's people: {people}

Reply with ONE JSON object only:
{{"reply": string,
  "task": "help"|"add_entry"|"update_balance"|"undo_entry"|"remove_record"|"show_record"|"show_summary"|"off_topic",
  "entry": null or {{"person": string|null, "business": string|null,
  "side": "owes_me"|"i_owe", "action": "add"|"subtract", "amount": number|null,
  "currency": string|null, "description": string|null, "method": string|null}},
  "target": null or {{"person": string|null, "business": string|null, "new_balance": number|null,
  "reason": string|null, "filter": "owed_to_me"|"i_owe"|null}},
  "ready": boolean}}"""

ENTRY_HINT = re.compile(r"\d|\b(took|paid|pay|gave|returned|bought|borrowed|lent|owes?|credit|cash|"
                        r"liya|liye|diye|jama|udhaa?r|wapas)\b", re.I)
OFF_TOPIC_REPLY = ("I can only help with Khataz: your records, entries, payments and how to use the app. "
                   "Please ask me something about Khataz.")
KHATAZ_WORDS = re.compile(
    r"\b(khataz|khata|record|records|ledger|entry|entries|balance|owe[sd]?|owing|credit|debt|udhaa?r|payment|"
    r"pay|paid|paypal|receipt|invoice|refund|transaction|money|amount|currency|customer|supplier|business|"
    r"shop|store|invite|link|chat|message|dispute|review|confirm|notification|profile|settings|account|"
    r"id|password|email|login|log in|sign up|register|search|reverse|undo|delete|remove|update|add|subtract|"
    r"voice|mic|assistant|help|dashboard)\b", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey|salam|assalam[ou] ?alaikum|aoa|thanks|thank you|shukriya|ok|okay|good "
                      r"(morning|evening|afternoon))\b[\s!.?]*$", re.I)


def _off_topic(text: str, records: list[dict], businesses: list[dict]) -> bool:
    """Built-in check: nothing about Khataz, no amounts, no names from the user's records."""
    if ENTRY_HINT.search(text) or KHATAZ_WORDS.search(text) or GREETING.search(text):
        return False
    words = ai_entry._tokens(text)
    names = set()
    for r in records:
        names |= ai_entry._tokens(r["name"]) | {(r.get("local_id") or "").lower(), (r.get("khataz_id") or "").lower()}
    for b in businesses:
        names |= ai_entry._tokens(b["name"])
    return not any(ai_entry._similar(w, n) for w in words for n in names if n)


QUESTION_HINT = re.compile(r"\?|^(how|what|where|why|can|does|do|is|are|who|when|help)\b", re.I)


def _segment(messages: list[dict]) -> list[dict]:
    """The conversation since the last saved entry."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] == "assistant" and messages[i]["content"].startswith(("Saved", "Done")):
            return messages[i + 1:]
    return messages


def _user_text(messages: list[dict]) -> str:
    return " . ".join(m["content"] for m in _segment(messages) if m["role"] == "user")


def _missing(draft: dict) -> list[str]:
    out = []
    if not draft.get("relationship_id") and not draft.get("matches") and not draft.get("new_person"):
        out.append("person")
    if not draft.get("amount"):
        out.append("amount")
    return out


def _ask(missing: list[str], draft: dict) -> str:
    if "person" in missing:
        return "Who is this entry for?"
    what = f" for the {draft['description']}" if draft.get("description") else ""
    return f"How much was it{what}?"


def _llm_draft(j: dict) -> dict | None:
    e = j.get("entry")
    if not isinstance(e, dict):
        return None
    return {
        "person": e.get("person") or None, "business": e.get("business") or None,
        "side": "payable" if str(e.get("side")).lower() == "i_owe" else "receivable",
        "action": "subtract" if str(e.get("action")).lower() == "subtract" else "add",
        "amount": ai_entry._money(e.get("amount")),
        "currency": (str(e.get("currency") or "").upper()[:3] or None),
        "description": e.get("description") or None, "method": e.get("method") or None,
    }


UNDO = re.compile(r"\b(undo|reverse|cancel|delete|remove|galat|wapas)\b.*\b(last|previous|latest|pichl[ia]|entry|"
                  r"transaction)\b|\bundo\b", re.I)
REMOVE = re.compile(r"\b(delete|remove|close|khatam)\b.*\b(record|account|khata|customer|supplier|person|ledger)\b", re.I)
SET_BAL = re.compile(r"\b(set|update|change|correct|make|fix)\b.*\bbalance\b|\bbalance\b.*\b(should be|to|is now|=)\b",
                     re.I)


SHOW = re.compile(r"\b(show|open|see|view|check|display|find|dikha\w*|batao|bata\w*)\b|\bhow much\b|\bkitn[ae]\b|"
                  r"\bbalance\b|\bhistory\b|\bentries\b|\brecord\b|\bkhata\b", re.I)
SUMMARY = re.compile(r"\b(who|everyone|all|list|summary|total|sab|kaun)\b.*\b(owe|owes|owed|records|customers|"
                     r"suppliers|balances?|khat[ae])\b|\bwhat do i owe\b|\bmy records\b", re.I)


def _rules_task(text: str) -> str | None:
    if REMOVE.search(text) and not re.search(r"\b(last|previous|latest)\b", text, re.I):
        return "remove_record"
    if UNDO.search(text):
        return "undo_entry"
    if SET_BAL.search(text):
        return "update_balance"
    if SUMMARY.search(text):
        return "show_summary"
    if SHOW.search(text) and not re.search(r"\d", text):  # numbers mean an entry, not a lookup
        return "show_record"
    return None


def _target(text: str, person: str | None, business_hint: str | None, records: list[dict],
            businesses: list[dict], owner_only: bool = True) -> tuple[dict | None, list[dict]]:
    """The record the task is about: (chosen, candidates). Changes need the owner's records."""
    own = [r for r in records if r.get("role") == "owner"] if owner_only else records
    business = ai_entry.find_business(text, business_hint, businesses)
    pool = [r for r in own if not business or r.get("business_id") == business["business_id"]]
    biz_words = ai_entry._tokens(business["name"]) if business else set()
    matches = ai_entry.match_people(text, person, pool, ignore=biz_words)
    if not matches:
        return None, []
    top, second = matches[0]["score"], (matches[1]["score"] if len(matches) > 1 else 0)
    if second == 0 or (top >= 30 and top - second >= 15) or top >= 2 * second:
        return matches[0], matches
    return None, matches


def _summary(t: dict, text: str, records: list[dict], businesses: list[dict], source: str) -> dict:
    low = text.lower()
    flt = t.get("filter")
    if not flt:
        if re.search(r"\b(owes? me|owed to me|customers?|receivable)\b", low):
            flt = "owed_to_me"
        elif re.search(r"\b(i owe|do i owe|suppliers?|payable)\b", low):
            flt = "i_owe"
    business = ai_entry.find_business(text, t.get("business"), businesses)
    rows = [r for r in records if (not flt or r["direction"] == flt)
            and (not business or r.get("business_id") == business["business_id"])
            and Decimal(r["balance"]) != 0]
    rows.sort(key=lambda r: -Decimal(r["amount"]))
    totals: dict[str, dict[str, Decimal]] = {}
    for r in rows:
        side = totals.setdefault(r["direction"], {})
        side[r["currency"]] = side.get(r["currency"], Decimal(0)) + Decimal(r["amount"])

    def fmt(side):
        return " + ".join(f"{v:,.2f} {c}" for c, v in totals.get(side, {}).items())
    parts = []
    if totals.get("owed_to_me"):
        parts.append(f"people owe you {fmt('owed_to_me')}")
    if totals.get("i_owe"):
        parts.append(f"you owe {fmt('i_owe')}")
    where = f" in {business['name']}" if business else ""
    reply = (f"In total{where}, " + " and ".join(parts) + ".") if parts else f"No open balances{where}."
    if parts:
        reply = reply[0].upper() + reply[1:]
    items = [{"relationship_id": r["relationship_id"], "name": r["name"], "business_name": r["business_name"],
              "local_id": r.get("local_id"), "balance": r["amount"], "currency": r["currency"],
              "perspective": r["direction"]} for r in rows[:12]]
    return {"reply": reply, "draft": None, "ready": False, "source": source,
            "records_list": {"items": items, "more": max(0, len(rows) - 12)}}


def _show(rec: dict, info: dict, source: str) -> dict:
    bal = Decimal(info["balance"])
    now = rec["perspective"] if bal >= 0 else ("i_owe" if rec["perspective"] == "owed_to_me" else "owed_to_me")
    owes = (f"{rec['name']} owes you" if now == "owed_to_me" else f"You owe {rec['name']}")
    reply = f"{owes} {abs(bal):,.2f} {rec['currency']}."
    if Decimal(info["balance"]) == 0:
        reply = f"{rec['name']}'s record is settled (balance 0.00 {rec['currency']})."
    card = {"relationship_id": rec["relationship_id"], "name": rec["name"], "business_name": rec["business_name"],
            "local_id": rec.get("local_id"), "khataz_id": rec.get("khataz_id"), "currency": rec["currency"],
            "perspective": now, "balance": f"{abs(bal):.2f}", "recent": info.get("recent", []),
            "waiting": info.get("waiting", False)}
    return {"reply": reply, "draft": None, "ready": False, "source": source, "record": card}


def _task(kind: str, t: dict, text: str, reply: str, records, businesses, lookup, source: str) -> dict:
    if kind == "show_summary":
        return _summary(t, text, records, businesses, source)
    rec, candidates = _target(text, t.get("person"), t.get("business"), records, businesses,
                              owner_only=kind != "show_record")
    if kind == "show_record" and not rec and candidates:
        return {"reply": "Which one do you mean?", "draft": None, "ready": False, "source": source,
                "records_list": {"items": [{"relationship_id": c["relationship_id"], "name": c["name"],
                                            "business_name": c["business_name"], "local_id": c.get("local_id"),
                                            "balance": c["amount"], "currency": c["currency"],
                                            "perspective": c["direction"]} for c in candidates[:5]], "more": 0}}
    if not rec:
        if candidates:
            names = " or ".join(f"{c['name']} ({c['business_name']})" for c in candidates[:3])
            return {"reply": f"Which one: {names}?", "draft": None, "ready": False, "source": source}
        return {"reply": "Whose record is it?", "draft": None, "ready": False, "source": source}
    info = lookup(rec["relationship_id"])
    if kind == "show_record":
        return _show(rec, info, source)
    base = {"relationship_id": rec["relationship_id"], "name": rec["name"], "business_name": rec["business_name"],
            "currency": rec["currency"], "balance": info["balance"]}
    if kind == "update_balance":
        new = ai_entry._money(t.get("new_balance")) if t.get("new_balance") not in (None, "") else None
        if new is None and str(t.get("new_balance")).strip() in ("0", "0.0", "0.00"):
            new = "0.00"
        if new is None:
            amount, _ = ai_entry._amount(text)
            new = ai_entry._money(amount) or ("0.00" if amount in ("0", "0.00") else None)
        if new is None:
            return {"reply": f"What should {rec['name']}'s balance be?", "draft": None, "ready": False, "source": source}
        if new == info["balance"]:
            return {"reply": f"{rec['name']}'s balance is already {new} {rec['currency']}.", "draft": None,
                    "ready": False, "source": source}
        action = base | {"kind": "update_balance", "to": new, "reason": t.get("reason") or "Balance corrected"}
        msg = f"Set {rec['name']}'s balance from {info['balance']} to {new} {rec['currency']}?"
    elif kind == "undo_entry":
        last = info.get("last_entry")
        if not last:
            return {"reply": f"There's no entry to undo on {rec['name']}'s record.", "draft": None,
                    "ready": False, "source": source}
        action = base | {"kind": "undo_entry", "entry": last, "reason": t.get("reason") or "Undone by the owner"}
        msg = f"Undo {rec['name']}'s last entry ({last['label']} {last['amount']} {rec['currency']})?"
    else:
        if info["balance"] != "0.00" or info.get("waiting"):
            return {"reply": f"{rec['name']}'s record can't be removed: the balance is {info['balance']} "
                             f"{rec['currency']}. Settle it to zero first.", "draft": None, "ready": False,
                    "source": source}
        action = base | {"kind": "remove_record"}
        msg = f"Remove {rec['name']}'s record from {rec['business_name']}? Its history is kept."
    return {"reply": msg if source == "Built-in" or not reply else reply, "draft": None, "action": action,
            "ready": True, "source": source}


def chat(messages: list[dict], records: list[dict], businesses: list[dict], default_currency: str,
         last_draft: dict | None = None, lookup=None, focus_business_id: int | None = None) -> dict:
    messages = [m for m in messages if m.get("role") in {"user", "assistant"} and m.get("content")][-16:]
    last = messages[-1]["content"] if messages else ""
    text = _user_text(messages)
    people = "; ".join(f"{r['name']}" + (f" ({r['local_id']})" if r.get("local_id") else "")
                       + f" [{r.get('business_name', '')}]" for r in records[:200]) or "none"
    system = SYSTEM.format(guide=GUIDE, businesses=", ".join(b["name"] for b in businesses) or "none",
                           people=people)

    for name, base, key, model in ai_entry.providers():
        try:
            j = _complete(base, key, model, system, messages)
        except Exception as e:  # rate limit, network, bad JSON: try the next one
            log.warning("Assistant: %s failed: %s", name, e)
            continue
        reply = str(j.get("reply") or "").strip()
        task = str(j.get("task") or "").lower()
        if task == "off_topic":
            return {"reply": OFF_TOPIC_REPLY, "draft": None, "ready": False, "source": name}
        if task in {"update_balance", "undo_entry", "remove_record", "show_record", "show_summary"} and lookup:
            return _task(task, j.get("target") or {}, text, reply, records, businesses, lookup, name)
        fields = _llm_draft(j)
        if not fields:
            return {"reply": reply or "Sorry, I didn't get that.", "draft": None, "ready": False, "source": name}
        draft = ai_entry.resolve(text, fields, name, records, default_currency, businesses, focus_business_id)
        missing = _missing(draft)
        if missing:
            if j.get("ready") or not reply.endswith("?"):
                reply = _ask(missing, draft)
            return {"reply": reply, "draft": draft, "ready": False, "missing": missing, "source": name}
        return {"reply": reply or "Ready. Check it and save.", "draft": draft, "ready": True, "source": name}

    return _without_ai(last, text, records, businesses, default_currency, last_draft, lookup, focus_business_id)


def _complete(base: str, key: str, model: str, system: str, messages: list[dict]) -> dict:
    import httpx

    from app.core.config import settings
    with httpx.Client(timeout=settings.ai_timeout_seconds) as c:
        r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "temperature": 0.2,
                         "messages": [{"role": "system", "content": system}, *messages]})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    content = r.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", content, re.S)
    if not m:  # plain-text answer: treat it as help
        return {"reply": content.strip(), "entry": None, "ready": False}
    return json.loads(m.group(0))


def _without_ai(last: str, text: str, records, businesses, default_currency, last_draft, lookup=None,
                focus_business_id: int | None = None) -> dict:
    """No AI available: the built-in reader still does entries and simple tasks."""
    task = _rules_task(last)
    if task and lookup:
        return _task(task, {}, last, "", records, businesses, lookup, "Built-in")
    if GREETING.search(last):
        return {"reply": "Hi! Tell me an entry, like “Marwan took 5 kg milk for $20”, or what to change.",
                "draft": None, "ready": False, "source": "Built-in"}
    if not (last_draft and not last_draft.get("amount")) and _off_topic(last, records, businesses):
        return {"reply": OFF_TOPIC_REPLY, "draft": None, "ready": False, "source": "Built-in"}
    # an answer to "How much was it?"
    if last_draft and not last_draft.get("amount"):
        amount, cur = ai_entry._amount(last)
        if amount:
            d = dict(last_draft, amount=ai_entry._money(amount), currency=cur or last_draft.get("currency"))
            return {"reply": "Ready. Check it and save.", "draft": d, "ready": True, "source": "Built-in"}
    if QUESTION_HINT.search(last.strip()) and not ENTRY_HINT.search(last):
        return {"reply": "The AI helper isn't available right now, so I can't answer questions. "
                         "I can still add entries: type something like “Marwan took 5 kg milk for $20”.",
                "draft": None, "ready": False, "source": "Built-in"}
    draft = ai_entry.resolve(last, None, "Built-in", records, default_currency, businesses, focus_business_id)
    missing = _missing(draft)
    if missing:
        return {"reply": _ask(missing, draft), "draft": draft, "ready": False, "missing": missing,
                "source": "Built-in"}
    return {"reply": "Ready. Check it and save.", "draft": draft, "ready": True, "source": "Built-in"}
