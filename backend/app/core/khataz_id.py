"""Khataz ID: the public, unique handle a user picks at sign-up (e.g. @abdul.hadi).

Rules: 3-20 characters, starts with a letter, only a-z, 0-9, '_' and '.',
no '..', can't end with '.'. Stored lowercase; unique regardless of case. Can't be changed.
"""

import re

KHATAZ_ID_RE = re.compile(r"^[a-z][a-z0-9_.]{2,19}$")
RESERVED = {"admin", "administrator", "khataz", "khatas", "support", "help", "paypal", "root",
            "system", "api", "me", "null", "undefined", "settings", "official", "staff"}


def normalize(value: str | None) -> str:
    return (value or "").strip().lstrip("@").lower()


def problem(value: str) -> str | None:
    """Why this ID can't be used, or None if it's valid (uniqueness is checked separately)."""
    v = normalize(value)
    if not 3 <= len(v) <= 20:
        return "Use 3 to 20 characters"
    if not v[0].isalpha():
        return "Start with a letter"
    if not KHATAZ_ID_RE.match(v):
        return "Use only letters, numbers, _ and ."
    if ".." in v or v.endswith("."):
        return "Dots can't be doubled or at the end"
    if v in RESERVED:
        return "This ID is reserved"
    return None
