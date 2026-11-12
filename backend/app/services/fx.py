"""Exchange rates. Every rate used is saved in fx_rates with its source and date."""

from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.money import money
from app.models import FxRate


class FxUnavailable(Exception):
    pass


def fetch_rate(base: str, quote: str, on: date) -> tuple[Decimal, str]:
    """Ask public rate APIs. Replaced in tests."""
    t = settings.fx_timeout_seconds
    try:  # ECB reference rates, historical, ~30 currencies
        r = httpx.get(f"https://api.frankfurter.app/{on.isoformat()}",
                      params={"from": base, "to": quote}, timeout=t)
        if r.status_code == 200 and quote in r.json().get("rates", {}):
            return Decimal(str(r.json()["rates"][quote])), "frankfurter.app (ECB)"
    except (httpx.HTTPError, ValueError):
        pass
    try:  # broader currency list, latest rates only
        r = httpx.get(f"https://open.er-api.com/v6/latest/{base}", timeout=t)
        data = r.json()
        if r.status_code == 200 and quote in data.get("rates", {}):
            return Decimal(str(data["rates"][quote])), "open.er-api.com (latest)"
    except (httpx.HTTPError, ValueError):
        pass
    raise FxUnavailable(f"No exchange rate for {base} to {quote}")


def get_rate(db: Session, base: str, quote: str, on: date) -> tuple[Decimal, str]:
    if base == quote:
        return Decimal(1), "same currency"
    cached = db.scalar(select(FxRate).where(FxRate.date == on, FxRate.base == base,
                                            FxRate.quote == quote))
    if cached:
        return Decimal(cached.rate), cached.source
    rate, source = fetch_rate(base, quote, on)
    db.add(FxRate(date=on, base=base, quote=quote, rate=rate, source=source))
    db.flush()
    return rate, source


def convert(db: Session, amount: Decimal, base: str, quote: str, on: date,
            manual_rate: Decimal | None = None) -> tuple[Decimal, Decimal, str]:
    """Returns (converted amount, rate, source)."""
    if manual_rate is not None:
        if manual_rate <= 0:
            raise ValueError("Exchange rate must be positive")
        return money(amount * manual_rate), manual_rate, "entered manually"
    rate, source = get_rate(db, base, quote, on)
    return money(amount * rate), rate, source
