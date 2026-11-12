"""Money is always Decimal with 2 places. Never float."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Currencies PayPal supports, plus a few common ledger currencies
CURRENCIES = {
    "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "JPY", "CHF", "SEK", "NOK", "DKK", "PLN",
    "CZK", "HUF", "ILS", "MXN", "BRL", "HKD", "SGD", "TWD", "THB", "PHP", "MYR", "CNY",
    "INR", "PKR", "AED", "SAR", "TRY", "ZAR", "KRW", "IDR", "BDT", "EGP", "NGN", "KES",
}
CENT = Decimal("0.01")


def money(value) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Invalid amount: {value!r}")
    if not d.is_finite():
        raise ValueError("Invalid amount")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def currency(code: str) -> str:
    code = (code or "").strip().upper()
    if code not in CURRENCIES:
        raise ValueError(f"Unsupported currency: {code or 'empty'}")
    return code
