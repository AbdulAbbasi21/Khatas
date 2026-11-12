// Live "is Khataz checking PayPal right now?" indicator.
// One shared poll of /api/paypal/live for every place the indicator is shown.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

const POLL_MS = 5000;
const listeners = new Set();
let latest = null;
let timer = null;

async function refresh() {
  try { latest = await api("/api/paypal/live"); } catch { latest = null; }
  listeners.forEach((fn) => fn(latest));
}

function subscribe(fn) {
  listeners.add(fn);
  if (latest) fn(latest);
  if (!timer) { refresh(); timer = setInterval(refresh, POLL_MS); }
  return () => {
    listeners.delete(fn);
    if (!listeners.size) { clearInterval(timer); timer = null; }
  };
}

export function usePayPalLive() {
  const [s, setS] = useState(latest);
  useEffect(() => {
    const off = subscribe(setS);
    const again = () => refresh();
    window.addEventListener("khataz:changed", again);
    return () => { off(); window.removeEventListener("khataz:changed", again); };
  }, []);
  return [s, refresh];
}

function ago(iso, now) {
  if (!iso) return null;
  const sec = Math.max(0, Math.round((now - new Date(iso)) / 1000));
  if (sec < 10) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  return `${Math.round(sec / 3600)} h ago`;
}

function inSecs(iso, now) {
  if (!iso) return null;
  const sec = Math.round((new Date(iso) - now) / 1000);
  if (sec <= 0) return "any moment";
  return sec < 60 ? `in ${sec}s` : `in ${Math.ceil(sec / 60)} min`;
}

function useNow() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  return now;
}

/** state: checking | error | watching | idle | off */
export function liveState(s) {
  if (!s) return "off";
  if (!s.enabled) return "off";
  if (s.checking_now) return "checking";
  if (s.error) return "error";
  return s.waiting > 0 ? "watching" : "idle";
}

/** Compact chip for the top bar. Shown only once PayPal checking is turned on. */
export function PayPalLiveChip() {
  const [s] = usePayPalLive();
  const st = liveState(s);
  if (st !== "checking" && st !== "error") return null; // only while checking, or when it failed
  const text = st === "checking" ? "Checking PayPal…" : "PayPal check failed";
  return (
    <Link to="/profile#paypal" className={`pp-live pp-live-${st}`} title="Automatic PayPal check — open your Profile">
      <span className="pp-dot" />{text}
    </Link>
  );
}

/** Full line with times and a "Check now" button (Settings, waiting payments). */
export function PayPalLiveLine({ claimId, onConfirmed }) {
  const [s, refreshNow] = usePayPalLive();
  const now = useNow();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const st = liveState(s);

  async function run() {
    setBusy(true); setMsg(null);
    const p = api(`/api/paypal/autocheck/run${claimId ? `?claim_id=${claimId}` : ""}`, { method: "POST" });
    setTimeout(refreshNow, 300); // show "Checking PayPal…" while it runs
    try {
      const r = await p;
      if (r.confirmed) { setMsg(`Confirmed ${r.confirmed} payment${r.confirmed > 1 ? "s" : ""} from PayPal.`); onConfirmed?.(); }
      else if (r.error) setMsg(r.error);
      else setMsg(r.checked ? "Not in your PayPal yet. PayPal can take a few minutes (sometimes up to 3 hours) to list a payment." : "No PayPal payments are waiting.");
    } catch (err) { setMsg(err.message); }
    setBusy(false); refreshNow();
  }

  if (st === "off") {
    return <div className="pp-live-line"><span className="pp-live pp-live-off"><span className="pp-dot" />PayPal check is off</span>
      <span className="small muted">Turn it on in your <Link to="/profile#paypal">Profile</Link> to confirm payments automatically.</span></div>;
  }
  const checking = st === "checking" || busy;
  const last = ago(s.last_checked_at || s.last_round_at, now);
  return (
    <div className="pp-live-line">
      {(checking || st === "error") && (
        <span className={`pp-live pp-live-${checking ? "checking" : "error"}`}>
          <span className="pp-dot" />
          {checking ? "Checking PayPal now…" : "Last PayPal check failed"}
        </span>
      )}
      <span className="small muted">
        {checking ? "Looking for the payment in your PayPal account"
          : [last && `last check ${last}`, s.next_check_at && `next ${inSecs(s.next_check_at, now)}`,
             s.waiting ? `${s.waiting} payment${s.waiting > 1 ? "s" : ""} waiting` : "nothing waiting"].filter(Boolean).join(" · ")}
      </span>
      <button className="btn btn-outline btn-sm" disabled={checking} onClick={run}>{checking ? "Checking…" : "Check PayPal now"}</button>
      {st === "error" && !checking && <span className="small" style={{ color: "var(--danger)", width: "100%" }}>{s.error}</span>}
      {msg && !checking && <span className="small muted" style={{ width: "100%" }}>{msg}</span>}
    </div>
  );
}
