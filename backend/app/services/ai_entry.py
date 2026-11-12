"""
"Type an entry": turn a sentence like "Marwan took 5 kg milk for $20" into a ledger entry draft.

Order: Groq -> OpenRouter -> built-in rules. Every provider is free to use; the rules need no
internet at all, so the feature always works. Nothing is saved here: the user checks the draft
and saves it through the normal entries endpoint.
"""

import json
import logging
import re
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings

log = logging.getLogger("khataz.ai")

SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "rs": "PKR", "rs.": "PKR", "pkr": "PKR", "rupees": "PKR",
           "rupee": "PKR", "dollars": "USD", "dollar": "USD", "usd": "USD", "eur": "EUR", "euro": "EUR",
           "euros": "EUR", "gbp": "GBP", "pounds": "GBP", "aed": "AED", "dirham": "AED", "dirhams": "AED",
           "sar": "SAR", "riyal": "SAR", "riyals": "SAR", "inr": "INR", "cad": "CAD", "aud": "AUD"}

SUBTRACT_WORDS = {"paid", "pay", "pays", "paying", "payment", "returned", "return", "gave back", "repaid",
                  "received", "sent", "settled", "deposited", "cleared", "jama", "diye", "de diye", "wapas",
                  "ada", "cash"}
ADD_WORDS = {"took", "take", "taken", "bought", "buy", "borrowed", "borrow", "credit", "owes", "owe",
             "loan", "lent", "liya", "liye", "le gaya", "le gayi", "udhaar", "udhar", "supplied",
             "delivered", "sold", "purchased", "purchase", "on credit"}
METHODS = ["paypal", "bank transfer", "bank", "cash", "cheque", "check", "card", "easypaisa", "jazzcash",
           "goods", "services"]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w@#.\- ]", " ", s.lower())).strip()


def _tokens(s: str | None) -> set[str]:
    return {t for t in _norm(s or "").replace("@", " ").replace("#", " ").split() if len(t) > 1}


# ---------------------------------------------------------------- finding the person
def _similar(a: str, b: str) -> bool:
    """Same word, allowing a small typo ("marvan" ~ "marwan")."""
    if a == b:
        return True
    def forms(w):  # "marvans" -> also "marvan"
        return {w} | ({w[:-1]} if len(w) > 4 and w.endswith("s") else set())
    return any(x == y or (min(len(x), len(y)) >= 4 and SequenceMatcher(None, x, y).ratio() >= 0.8)
               for x in forms(a) for y in forms(b))


def _overlap(name: set[str], words: set[str]) -> int:
    return sum(1 for n in name if any(_similar(n, w) for w in words))


def find_business(text: str, hint: str | None, businesses: list[dict]) -> dict | None:
    """The user's own business the note mentions (by name, typos allowed)."""
    words = _tokens(text) | _tokens(hint)
    best, best_score = None, 0.0
    for b in businesses:
        name = _tokens(b["name"]) - {"shop", "store", "the", "and", "co", "ltd"} or _tokens(b["name"])
        if not name:
            continue
        score = _overlap(name, words) / len(name)
        if score > best_score:
            best, best_score = b, score
    return best if best_score >= 0.6 else None


def match_people(text: str, person: str | None, records: list[dict],
                 ignore: set[str] | None = None) -> list[dict]:
    """Records ranked by how well they match the person named (or the sentence)."""
    probe, sentence = _tokens(person), _tokens(text) - (ignore or set())
    low = text.lower()
    scored = []
    for r in records:
        score = 0.0
        if r.get("local_id") and re.search(rf"(?<![\w-]){re.escape(r['local_id'].lower())}(?![\w-])", low):
            score += 100
        if r.get("khataz_id") and f"@{r['khataz_id'].lower()}" in low:
            score += 100
        name = _tokens(r["name"])
        if name:
            if probe:
                hit = _overlap(name, probe)
                score += 40 * hit / len(name | probe) + (30 if hit == len(probe) else 0)
            score += 20 * _overlap(name, sentence) / len(name)
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [r | {"score": round(s, 1)} for s, r in scored[:5]]


def guess_person(text: str, business: dict | None) -> str | None:
    """Rules only: the words before the first action word, e.g. "marvan took ..." -> "Marvan"."""
    t = re.sub(r"@\w+", " ", text)
    if business:  # "... from Gujjar Milk Shop": drop the business name
        for w in re.findall(r"[\w']+", business["name"]):
            t = re.sub(rf"\b{re.escape(w)}\b", " ", t, flags=re.I)
    actions = sorted(SUBTRACT_WORDS | ADD_WORDS, key=len, reverse=True)
    m = re.search(r"\b(" + "|".join(re.escape(w) for w in actions) + r")\b", t, re.I)
    head = t[:m.start()] if m else ""
    words = [w for w in re.findall(r"[A-Za-z][\w'.-]*", head) if w.lower() not in FILLER | {"mr", "mrs", "ms"}]
    if not words and m:  # "paid Marwan 20": the name comes after the verb
        tail = re.findall(r"[A-Za-z][\w'.-]*", t[m.end():])
        words = [w for w in tail[:2] if w.lower() not in FILLER and w.lower() not in QTY_UNITS and not
                 re.match(CUR_WORD + "$", w.lower())][:1]
    name = " ".join(words[:3]).strip()
    return name.title() if name else None


def guess_side(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(i|we)\s+(took|bought|borrowed|got|owe)\b|\bbought from\b|\bsupplier\b|\bpurchased\b", low):
        return "payable"
    return "receivable"


# ---------------------------------------------------------------- built-in rules
NUM = r"\d[\d,]*(?:\.\d+)?"
CUR_WORD = (r"dollars?|usd|rupees?|rs\.?|pkr|euros?|eur|pounds|gbp|aed|dirhams?|sar|riyals?|inr|cad|aud")
QTY_UNITS = {"kg", "kgs", "g", "gm", "l", "litre", "litres", "liter", "liters", "ltr", "pcs", "pc", "boxes",
             "box", "dozen", "bags", "bag", "units", "unit", "packs", "pack", "metres", "meters", "m", "x",
             "bottles", "cartons", "carton", "sacks", "maund", "items", "piece", "pieces"}


def _amount(text: str) -> tuple[str | None, str | None]:
    low = text.lower()
    m = re.search(rf"([$€£])\s*({NUM})", text)
    if m:
        return m.group(2), SYMBOLS[m.group(1)]
    m = re.search(rf"({NUM})\s*({CUR_WORD})(?![a-z])", low)
    if m:
        return m.group(1), SYMBOLS.get(m.group(2)) or SYMBOLS.get(m.group(2).rstrip("."))
    m = re.search(rf"(?<![a-z])({CUR_WORD})\s*({NUM})", low)
    if m:
        return m.group(2), SYMBOLS.get(m.group(1)) or SYMBOLS.get(m.group(1).rstrip("."))
    # no currency given: skip quantities ("5 kg") and IDs ("CUST-001"); the price is usually last
    prices = [m.group(1) for m in re.finditer(rf"(?<![\w-])({NUM})(?:\s*([a-z]+))?", low)
              if (m.group(2) or "") not in QTY_UNITS]
    return (prices[-1] if prices else None), None


def parse_rules(text: str, default_currency: str) -> dict:
    low = " " + text.lower() + " "
    amount, currency = _amount(text)

    sub = any(re.search(rf"\b{re.escape(w)}\b", low) for w in SUBTRACT_WORDS)
    add = any(re.search(rf"\b{re.escape(w)}\b", low) for w in ADD_WORDS)
    action = "subtract" if sub and not add else "add"
    if sub and add:  # e.g. "paid 20 for milk he took" -> the payment wins if "paid" comes first
        first_sub = min(low.find(w) for w in SUBTRACT_WORDS if re.search(rf"\b{re.escape(w)}\b", low))
        first_add = min(low.find(w) for w in ADD_WORDS if re.search(rf"\b{re.escape(w)}\b", low))
        action = "subtract" if first_sub < first_add else "add"
    method = next((m.title() if m not in {"paypal", "easypaisa", "jazzcash"} else
                   {"paypal": "PayPal", "easypaisa": "Easypaisa", "jazzcash": "JazzCash"}[m]
                   for m in METHODS if re.search(rf"\b{m}\b", low)), None) if action == "subtract" else None

    return {"action": action, "amount": _money(amount), "currency": currency,
            "person": None, "description": None, "method": method}


FILLER = {"for", "by", "of", "from", "to", "the", "a", "an", "ne", "ko", "se", "karaye", "karay", "kiye",
          "kia", "kiya", "diya", "in", "on", "worth", "he", "she", "they", "me", "i", "my", "his", "her",
          "has", "have", "had", "and", "via", "through", "today", "aaj", "rupay", "back", "gave", "give"}


def describe(text: str, record: dict | None, method: str | None, extra: set[str] | None = None,
             business_name: str | None = None) -> str | None:
    """What it was for: the note without the name, ID, price, payment words and filler."""
    if business_name:  # "... from Gujjar Milk Shop" -> drop the whole phrase, keep "milk" elsewhere
        words = [re.escape(w) for w in re.findall(r"[\w']+", business_name)]
        text = re.sub(r"\b(?:from|at|of|in)?\s*" + r"\W+".join(words) + r"\b", " ", text, flags=re.I)
    t = re.sub(rf"[$€£]\s*{NUM}|{NUM}\s*(?:{CUR_WORD})(?![a-z])|(?<![a-z])(?:{CUR_WORD})\s*{NUM}", " ",
               text, flags=re.I)
    amount, _ = _amount(text)
    drop = set(FILLER) | {w for w in SUBTRACT_WORDS | ADD_WORDS if " " not in w}
    if record:
        drop |= _tokens(record["name"]) | {(record.get("local_id") or "").lower(),
                                           "@" + (record.get("khataz_id") or "").lower()}
    if method:
        drop |= set(method.lower().split())
    drop |= extra or set()
    words = [w for w in re.split(r"\s+", t) if w]
    keep, removed_amount = [], False
    for w in words:
        bare = w.strip(".,!?;:").lower()
        if not removed_amount and amount and bare == amount.lower():
            removed_amount = True
            continue
        if bare in drop or bare.lstrip("@") in drop:
            continue
        keep.append(w.strip(".,!?;:"))
    out = " ".join(keep).strip()
    return out[:1].upper() + out[1:] if out else None


def _money(v) -> str | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", ""))
    except InvalidOperation:
        return None
    return f"{d:.2f}" if d > 0 else None


# ---------------------------------------------------------------- language models
PROMPT = """You turn one short note from a shopkeeper's credit book (khata) into JSON.
The note may be English or Roman Urdu. Reply with ONE JSON object and nothing else:
{{"person": string|null, "business": string|null, "side": "owes_me"|"i_owe",
  "action": "add"|"subtract", "amount": number|null,
  "currency": 3-letter code|null, "description": string|null, "method": string|null}}

Rules:
- person: the other person named in the note, as written (or their ID like CUST-001 or @name).
- business: one of the user's businesses if the note names it (e.g. "from Gujjar Milk Shop"), else null.
- side: "owes_me" if that person owes the user's business (a customer), "i_owe" if the user owes them (a supplier).
- action "add": the debt grows (they took goods/money on credit, borrowed, I bought on credit from a supplier).
- action "subtract": the debt shrinks (a payment was made either way, money returned, goods returned).
- amount: the money value, not quantities like "5 kg". currency: from symbols/words ($ = USD, Rs = PKR), else null.
- description: what it was for, short (e.g. "5 kg milk"). method: for payments only (Cash, Bank, PayPal...), else null.

The user's businesses: {businesses}
The user's people: {people}
Note: {text}"""


def _call(base: str, key: str, model: str, prompt: str) -> dict:
    with httpx.Client(timeout=settings.ai_timeout_seconds) as c:
        r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "temperature": 0,
                         "messages": [{"role": "user", "content": prompt}]})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    content = r.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise RuntimeError("no JSON in reply")
    return json.loads(m.group(0))


def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    """Groq Whisper: audio -> text (English, Urdu and mixed speech)."""
    with httpx.Client(timeout=max(settings.ai_timeout_seconds, 30)) as c:
        r = c.post("https://api.groq.com/openai/v1/audio/transcriptions",
                   headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                   data={"model": settings.groq_stt_model, "response_format": "json", "temperature": "0"},
                   files={"file": (filename, audio, content_type)})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return (r.json().get("text") or "").strip()


def providers() -> list[tuple[str, str, str, str]]:
    out = []
    if settings.groq_api_key:
        out.append(("Groq", "https://api.groq.com/openai/v1", settings.groq_api_key, settings.groq_model))
    if settings.openrouter_api_key and settings.openrouter_model:
        out.append(("OpenRouter", "https://openrouter.ai/api/v1", settings.openrouter_api_key,
                    settings.openrouter_model))
    return out


def parse(text: str, records: list[dict], default_currency: str,
          businesses: list[dict] | None = None, focus_business_id: int | None = None) -> dict:
    businesses = businesses or []
    people = "; ".join(f"{r['name']}" + (f" ({r['local_id']})" if r.get("local_id") else "")
                       + (f" @{r['khataz_id']}" if r.get("khataz_id") else "")
                       + f" [{r.get('business_name', '')}]" for r in records[:200]) or "none"
    biz_names = ", ".join(b["name"] for b in businesses) or "none"
    draft, source = None, "Built-in"
    for name, base, key, model in providers():
        try:
            j = _call(base, key, model, PROMPT.format(people=people, businesses=biz_names, text=text))
            draft = {
                "person": (j.get("person") or None),
                "business": (j.get("business") or None),
                "side": "payable" if str(j.get("side")).lower() == "i_owe" else "receivable",
                "action": "subtract" if str(j.get("action")).lower() == "subtract" else "add",
                "amount": _money(j.get("amount")),
                "currency": (str(j.get("currency") or "").upper()[:3] or None),
                "description": (j.get("description") or None),
                "method": (j.get("method") or None),
            }
            source = name
            break
        except Exception as e:  # rate limit, network, bad JSON: try the next one
            log.warning("AI entry: %s failed: %s", name, e)
    return resolve(text, draft, source, records, default_currency, businesses, focus_business_id)


def resolve(text: str, draft: dict | None, source: str, records: list[dict], default_currency: str,
            businesses: list[dict], focus_business_id: int | None = None) -> dict:
    """Fill gaps with the rules, then find the business and person in the user's own records."""
    rules = parse_rules(text, default_currency)
    if draft is None:
        draft = rules | {"business": None, "side": guess_side(text)}
    else:  # fill gaps the model left
        for k in ("amount", "currency", "method"):
            draft[k] = draft[k] or rules[k]
    draft["source"] = source

    # which of my businesses (only own businesses can get new people)
    named = find_business(text, draft.get("business"), businesses)
    business = named
    # not named: the business open on screen, else the only one
    if not business and focus_business_id:
        business = next((b for b in businesses if b["business_id"] == focus_business_id), None)
    if not business and len(businesses) == 1:
        business = businesses[0]
    draft["business_id"] = business["business_id"] if business else None
    biz_words = _tokens(business["name"]) if business else set()
    if not draft.get("person"):
        draft["person"] = guess_person(text, business)

    pool = records
    focus = business["business_id"] if business else focus_business_id
    if focus:  # the named (or open) business narrows the search to its people
        pool = [r for r in records if r.get("business_id") == focus]
    matches = match_people(text, draft.get("person"), pool, ignore=biz_words)
    if not matches and not named:  # nobody there: look in all my records
        matches = match_people(text, draft.get("person"), records, ignore=biz_words)
    draft["matches"] = matches
    chosen = None
    if matches:
        top, second = matches[0]["score"], (matches[1]["score"] if len(matches) > 1 else 0)
        if second == 0 or (top >= 30 and top - second >= 15) or top >= 2 * second:
            chosen = matches[0]
    draft["relationship_id"] = chosen["relationship_id"] if chosen else None
    # nobody like this yet: offer to create the record
    draft["new_person"] = draft.get("person") or None  # name to use if they choose a new record
    if source == "Built-in" or not draft.get("description"):
        rec = chosen or (matches[0] if matches else None)
        draft["description"] = describe(text, rec, draft.get("method"), extra=_tokens(draft.get("person")),
                                        business_name=business["name"] if business else None)
    if draft["action"] != "subtract":
        draft["method"] = None
    return draft
