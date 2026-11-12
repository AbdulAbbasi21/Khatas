"""
PayPal receipt text -> structured fields.

Works on OCR output from:
  - PayPal app / website transaction screenshots ("You sent $25.00 to John Doe")
  - PayPal email receipts ("Receipt for your payment", "Transaction ID", "Total")

No ML dependencies, so it can be unit-tested on plain text.
"""

import re

# ---------------------------------------------------------------- patterns
CURRENCY_CODES = r"USD|EUR|GBP|CAD|AUD|JPY|INR|PKR|AED|SGD|CHF|SEK|NOK|DKK|NZD|HKD|MXN|BRL"
SYMBOLS = r"US\$|CA\$|AU\$|A\$|C\$|\$|€|£|¥|₹"

AMOUNT_RE = re.compile(
    rf"(?P<sign>[-−–])?\s?(?P<sym>{SYMBOLS})?\s?"
    rf"(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d{{2}})?|\d+\.\d{{2}})"
    rf"\s?(?P<code>{CURRENCY_CODES})?\b"
)
SYMBOL_TO_CODE = {"$": "USD", "US$": "USD", "CA$": "CAD", "C$": "CAD", "AU$": "AUD",
                  "A$": "AUD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}

# PayPal transaction IDs: 17 uppercase letters/digits, e.g. 5TY05013RG002845M
TXN_ID_RE = re.compile(r"\b[0-9A-Z]{17}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

MONTHS = (r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
          r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?")
DATE_RE = re.compile(
    rf"\b(?:(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}}"        # Nov 3, 2026
    rf"|\d{{1,2}}\s+(?:{MONTHS})\.?,?\s+\d{{4}}"           # 3 November 2026
    rf"|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}})"            # 03/11/2026
    rf"(?:\s*(?:at|,)?\s*\d{{1,2}}:\d{{2}}(?::\d{{2}})?\s*(?:AM|PM|am|pm)?)?",
    re.IGNORECASE,
)
STATUS_RE = re.compile(r"\b(completed|pending|refunded|partially refunded|denied|"
                       r"unclaimed|cancelled|canceled|reversed|on hold)\b", re.IGNORECASE)

KEYWORDS = ["transaction id", "transaction", "payment", "you sent", "you received",
            "sent you", "you paid", "total", "completed", "receipt", "paid with",
            "funding", "fee", "sent to", "paid to", "merchant"]


# ---------------------------------------------------------------- helpers
def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


def _value_after(lines: list[str], labels: list[str]) -> str | None:
    """Value on the same line after 'Label:' or on the next line."""
    for i, line in enumerate(lines):
        low = line.lower()
        for label in labels:
            if low.startswith(label):
                rest = line[len(label):].strip(" :-\t")
                if rest:
                    return rest
                if i + 1 < len(lines):
                    return lines[i + 1]
    return None


def _parse_amount(s: str) -> dict | None:
    for m in AMOUNT_RE.finditer(s):
        if not (m["sym"] or m["code"]):
            continue  # a bare number like 12.50 is too ambiguous
        value = float(m["num"].replace(",", ""))
        if m["sign"]:
            value = -value
        currency = m["code"] or SYMBOL_TO_CODE.get(m["sym"])
        return {"value": value, "currency": currency, "raw": m.group(0).strip()}
    return None


def _find_txn_id(text: str) -> str | None:
    # Prefer the value next to the label, then any 17-char token with letters+digits
    lab = _value_after(_lines(text), ["transaction id", "transaction code", "receipt number"])
    candidates = [lab.upper().replace(" ", "")] if lab else []
    candidates.append(text)
    for candidate in candidates:
        for tok in TXN_ID_RE.findall(candidate):
            if re.search(r"\d", tok) and re.search(r"[A-Z]", tok):
                return tok
    return None


# ---------------------------------------------------------------- public API
# Wording that only appears on receipts PayPal itself generates (app, website, email)
PAYPAL_ISSUER_PHRASES = [
    "you sent", "you received", "sent you", "you paid", "payment sent", "payment received",
    "money sent", "receipt for your payment", "you've got money", "you sent a payment",
    "paid with", "funding source", "seller info", "merchant transaction id",
    "paypal balance", "help center", "paypal.com", "paypal pte", "paypal, inc", "paypal inc",
    "paypal (europe)", "paypal holdings", "© paypal", "send again", "pay again",
]
# Wording a MERCHANT uses when PayPal was only the payment processor
THIRD_PARTY_PATTERNS = [
    r"processed by\s+paypal", r"processed (?:through|via|using)\s+paypal",
    r"(?:will )?appear on your (?:card |bank )?statement as\s+paypal\s*\*?\s*[\w&.' -]{0,40}",
    r"(?:paid|pay|payment) (?:with|via|using|through|by)\s+paypal",
    r"payment method\s*:?\s*paypal", r"via\s+paypal", r"through\s+paypal",
    r"powered by\s+paypal", r"paypal checkout",
]
STATEMENT_NAME_RE = re.compile(r"statement as\s+paypal\s*\*?\s*([A-Za-z0-9&.' -]{2,40})", re.I)  # stops at line end


def _norm(text: str) -> str:
    """Lowercase, one line: phrases that OCR wraps across lines still match."""
    return re.sub(r"\s+", " ", text.lower().replace("pay pal", "paypal")).strip()


def looks_like_paypal(text: str, min_keyword_hits: int = 2) -> dict:
    """
    Decide who ISSUED the receipt:
      "paypal"              - generated by PayPal (app/web screenshot or PayPal email)
      "merchant_via_paypal" - a shop/event's own receipt that was merely paid through PayPal
      "not_paypal"          - no PayPal evidence
    Only "paypal" passes.
    """
    flat = _norm(text)
    lines = _lines(text)
    hits = [k for k in KEYWORDS if k in flat]
    has_txn = _find_txn_id(text) is not None

    third_party = [p for p in THIRD_PARTY_PATTERNS if re.search(p, flat)]
    # remove "processed by PayPal"-style mentions; does PayPal still appear?
    stripped = flat
    for p in THIRD_PARTY_PATTERNS:
        stripped = re.sub(p, " ", stripped)
    paypal_elsewhere = "paypal" in stripped
    header_brand = any("paypal" in _norm(l) for l in lines[:3])
    issuer_hits = [p for p in PAYPAL_ISSUER_PHRASES if p in stripped]

    if header_brand and not third_party:
        issuer = "paypal"
    elif issuer_hits and (paypal_elsewhere or has_txn) and (len(issuer_hits) >= 2 or not third_party):
        issuer = "paypal"
    elif third_party or "paypal" in flat:
        issuer = "merchant_via_paypal"
    else:
        issuer = "not_paypal"

    m = STATEMENT_NAME_RE.search(text)
    merchant = m.group(1).strip(" .") if m else None
    if merchant and merchant.lower() in {"and", "the"}:
        merchant = None

    passed = issuer == "paypal" and len(hits) >= min_keyword_hits
    return {"passed": passed, "issuer": issuer, "merchant": merchant,
            "mentions_paypal": "paypal" in flat, "has_transaction_id": has_txn,
            "paypal_issuer_signals": issuer_hits, "third_party_signals": len(third_party),
            "keywords_found": hits}


def parse_receipt(text: str) -> dict:
    lines = _lines(text)
    low = text.lower()

    # --- direction + counterparty from the headline
    direction, counterparty = None, None
    patterns = [
        (r"you sent .*? to (.+)", "sent"),
        (r"you paid .*? to (.+)", "sent"),
        (r"payment sent to (.+)", "sent"),
        (r"you received .*? from (.+)", "received"),
        (r"(.+?) sent you", "received"),
        (r"payment received from (.+)", "received"),
    ]
    for line in lines:
        for pat, d in patterns:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                direction, counterparty = d, m.group(1).strip(" .")
                break
        if direction:
            break
    if not direction:
        if "you sent" in low or "payment sent" in low or "you paid" in low:
            direction = "sent"
        elif "you received" in low or "sent you" in low or "payment received" in low:
            direction = "received"
    if not counterparty:
        counterparty = _value_after(lines, ["sent to", "paid to", "merchant", "recipient",
                                            "from:", "to:"])

    # --- amounts: prefer labelled lines, then the headline, then the largest amount
    amount = None
    for label in ["total", "amount", "you sent", "you received", "you paid", "payment"]:
        v = _value_after(lines, [label])
        amount = _parse_amount(f"{label} {v}") if v else None
        if amount:
            break
    if not amount:
        all_amounts = [a for l in lines if (a := _parse_amount(l))]
        amount = max(all_amounts, key=lambda a: abs(a["value"])) if all_amounts else None

    fee = _parse_amount(_value_after(lines, ["fee", "paypal fee", "transaction fee"]) or "")

    date = DATE_RE.search(_value_after(lines, ["transaction date", "date"]) or "") or DATE_RE.search(text)
    status = STATUS_RE.search(text)
    emails = [e for e in EMAIL_RE.findall(text) if "paypal" not in e.lower()]

    return {
        "transaction_id": _find_txn_id(text),
        "direction": direction,
        "counterparty": counterparty,
        "amount": amount["value"] if amount else None,
        "currency": amount["currency"] if amount else None,
        "fee": fee["value"] if fee else None,
        "date": date.group(0).strip() if date else None,
        "status": status.group(1).capitalize() if status else None,
        "funding_source": _value_after(lines, ["paid with", "funding source", "payment method"]),
        "emails": emails or None,
        "note": _value_after(lines, ["note", "message", "purpose"]),
    }
