// Money arrives from the API as strings ("125.50"); never do float maths on it for storage.

export const CURRENCIES = [
  "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "JPY", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK",
  "HUF", "ILS", "MXN", "BRL", "HKD", "SGD", "TWD", "THB", "PHP", "MYR", "CNY", "INR", "PKR",
  "AED", "SAR", "TRY", "ZAR", "KRW", "IDR", "BDT", "EGP", "NGN", "KES",
];

export function money(amount, currency) {
  const n = Number(amount ?? 0);
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, currencyDisplay: "code" }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

export function absMoney(amount, currency) {
  return money(Math.abs(Number(amount ?? 0)), currency);
}

// Dates are UTC from the API; show them in the user's own time zone.
export function dateTime(iso, tz) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: tz || undefined }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}

export function dateOnly(iso, tz) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: tz || undefined }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleDateString();
  }
}

export function timeZones() {
  try { return Intl.supportedValuesOf("timeZone"); } catch { return ["UTC"]; }
}

export function browserTimeZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

export const initials = (name = "") =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";

export const CLAIM_STATE = {
  pending_confirmation: { label: "Waiting for recipient", cls: "badge-blue" },
  needs_review: { label: "Needs review", cls: "badge-solid" },
  held: { label: "On hold", cls: "badge-outline" },
  allocated: { label: "Confirmed", cls: "badge-black" },
  rejected: { label: "Rejected", cls: "badge-danger" },
  disputed: { label: "Not received", cls: "badge-danger" },
  reversed: { label: "Reversed", cls: "badge-grey" },
};

export const ENTRY_TYPE = {
  credit: "Credit",
  payment: "Payment",
  goods: "Goods / services",
  adjustment: "Adjustment",
  reversal: "Reversal",
};

// today's date in the user's own time zone, as YYYY-MM-DD (for date pickers)
export function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "5h left" / "40 min left" until the cancel window closes; null once it has. */
export function timeLeft(until) {
  if (!until) return null;
  const ms = new Date(until) - Date.now();
  if (ms <= 0) return null;
  const h = Math.floor(ms / 3600000);
  return h >= 1 ? `${h}h left` : `${Math.max(1, Math.round(ms / 60000))} min left`;
}
