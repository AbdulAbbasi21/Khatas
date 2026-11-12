import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { CURRENCIES, browserTimeZone } from "../format";

// best guess from the browser's region; the person can change it
const REGION_CURRENCY = { US: "USD", GB: "GBP", PK: "PKR", IN: "INR", AE: "AED", SA: "SAR", CA: "CAD", AU: "AUD",
  NZ: "NZD", JP: "JPY", CN: "CNY", SG: "SGD", HK: "HKD", CH: "CHF", SE: "SEK", NO: "NOK", DK: "DKK", PL: "PLN",
  TR: "TRY", ZA: "ZAR", BR: "BRL", MX: "MXN", BD: "BDT", EG: "EGP", NG: "NGN", KE: "KES", MY: "MYR", TH: "THB",
  PH: "PHP", ID: "IDR", KR: "KRW", DE: "EUR", FR: "EUR", ES: "EUR", IT: "EUR", NL: "EUR", IE: "EUR", BE: "EUR",
  AT: "EUR", PT: "EUR", FI: "EUR", GR: "EUR" };
function guessCurrency() {
  try {
    const region = new Intl.Locale(navigator.language).maximize().region;
    return REGION_CURRENCY[region] || "USD";
  } catch { return "USD"; }
}
import { ErrorBox, Field, Logo } from "../components/ui";

function Shell({ children }) {
  return (
    <div className="auth-wrap">
      <section className="auth-hero">
        <Logo light />
        <div>
          <h1>Your business credit book, shared and verified.</h1>
          <p>Record who owes what, let both sides see the same ledger, and confirm PayPal payments before they change a balance.</p>
          <ul className="auth-points">
            <li>Separate books for every business you run</li>
            <li>Customers confirm or dispute entries themselves</li>
            <li>PayPal receipts checked, then confirmed by the person who got paid</li>
          </ul>
        </div>
        <p className="small" style={{ color: "#8fa6d4" }}>Khataz records payments. It never moves money.</p>
      </section>
      <section className="auth-form">{children}</section>
    </div>
  );
}

export function Login() {
  const { signIn } = useAuth();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { signIn(await api("/api/auth/login", { method: "POST", body: form })); }
    catch (err) { setError(err); setBusy(false); }
  }

  return (
    <Shell>
      <form onSubmit={submit} className="stack">
        <div><h1>Log in</h1></div>
        <ErrorBox error={error} />
        <Field label="Email">
          <input type="email" autoComplete="email" required value={form.email}
                 onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={form.password}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
        <p className="small" style={{ textAlign: "center", margin: 0 }}><Link to="/forgot-password">Forgot password?</Link></p>
        <p className="muted small" style={{ textAlign: "center" }}>New to Khataz? <Link to="/register">Create an account</Link></p>
      </form>
    </Shell>
  );
}

/** Checks the Khataz ID while the person types (debounced). */
function useKhatazIdCheck(value) {
  const [state, setState] = useState(null);
  useEffect(() => {
    const v = value.trim().replace(/^@/, "");
    if (!v) { setState(null); return; }
    setState({ checking: true });
    const t = setTimeout(() => {
      api(`/api/auth/khataz-id?id=${encodeURIComponent(v)}`).then(setState).catch(() => setState(null));
    }, 350);
    return () => clearTimeout(t);
  }, [value]);
  return state;
}

export function Register() {
  const { signIn } = useAuth();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ name: "", email: params.get("email") || "", khataz_id: "", password: "",
                                     timezone: browserTimeZone(), default_currency: guessCurrency() });
  const idCheck = useKhatazIdCheck(form.khataz_id);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { signIn(await api("/api/auth/register", { method: "POST", body: { ...form, khataz_id: form.khataz_id.trim().replace(/^@/, "") } })); }
    catch (err) { setError(err); setBusy(false); }
  }

  return (
    <Shell>
      <form onSubmit={submit} className="stack">
        <div><h1>Create your account</h1></div>
        <ErrorBox error={error} />
        <Field label="Full name"><input required value={form.name} onChange={set("name")} autoComplete="name" /></Field>
        <Field label="Email"><input type="email" required value={form.email} onChange={set("email")} autoComplete="email" /></Field>
        <div className="field">
          <label>Khataz ID</label>
          <div className="prefix-input"><span>@</span>
            <input required value={form.khataz_id} onChange={(e) => setForm({ ...form, khataz_id: e.target.value.toLowerCase().replace(/\s/g, "") })}
                   placeholder="your.name" autoCapitalize="off" spellCheck="false" maxLength={21} />
          </div>
          <span className={`hint ${idCheck?.available === false ? "hint-bad" : idCheck?.available ? "hint-good" : ""}`}>
            {!idCheck ? ""
              : idCheck.checking ? "Checking…"
              : idCheck.available ? `@${idCheck.khataz_id} is available`
              : idCheck.reason}
          </span>
        </div>
        <Field label="Password" hint="At least 8 characters">
          <input type="password" required minLength={8} value={form.password} onChange={set("password")} autoComplete="new-password" />
        </Field>
        <div className="field-row">
          <Field label="Your currency" hint="Used for your books. You can change it later.">
            <select value={form.default_currency} onChange={set("default_currency")}>
              {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </Field>
          <Field label="Time zone" hint="From your browser">
            <input value={form.timezone} onChange={set("timezone")} />
          </Field>
        </div>
        <button className="btn btn-primary btn-block" disabled={busy || idCheck?.available === false}>{busy ? "Creating…" : "Create account"}</button>
        <p className="muted small" style={{ textAlign: "center" }}>Already have an account? <Link to="/login">Log in</Link></p>
      </form>
    </Shell>
  );
}


export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/api/auth/forgot", { method: "POST", body: { email } }); setSent(true); }
    catch (err) { setError(err); }
    setBusy(false);
  }
  return (
    <Shell>
      <form onSubmit={submit} className="stack">
        <div><h1>Reset password</h1></div>
        <ErrorBox error={error} />
        {sent ? (
          <div className="alert alert-info">If {email} has a Khataz account, a reset link is on its way. It works for 30 minutes.</div>
        ) : (
          <>
            <Field label="Email"><input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
          </>
        )}
        <p className="muted small" style={{ textAlign: "center" }}><Link to="/login">Back to log in</Link></p>
      </form>
    </Shell>
  );
}

export function ResetPassword() {
  const { signIn } = useAuth();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ password: "", again: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setError(null);
    if (form.password !== form.again) return setError(new Error("The passwords don't match"));
    setBusy(true);
    try { signIn(await api("/api/auth/reset", { method: "POST", body: { token: params.get("token") || "", password: form.password } })); }
    catch (err) { setError(err); setBusy(false); }
  }
  return (
    <Shell>
      <form onSubmit={submit} className="stack">
        <div><h1>New password</h1></div>
        <ErrorBox error={error} />
        <Field label="New password"><input type="password" autoComplete="new-password" minLength={8} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <Field label="Type it again"><input type="password" autoComplete="new-password" minLength={8} required value={form.again} onChange={(e) => setForm({ ...form, again: e.target.value })} /></Field>
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Saving…" : "Save and log in"}</button>
        <p className="muted small" style={{ textAlign: "center" }}><Link to="/forgot-password">Get a new link</Link></p>
      </form>
    </Shell>
  );
}
