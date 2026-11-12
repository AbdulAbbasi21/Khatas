import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field } from "../components/ui";
import { CURRENCIES, timeZones } from "../format";

export default function Settings() {
  const { user, setUser } = useAuth();
  const [form, setForm] = useState({
    name: user.name, timezone: user.timezone, country: user.country || "", default_currency: user.default_currency,
    paypal_email: user.paypal_email || "", can_receive_paypal: user.can_receive_paypal,
    email_notifications: user.email_notifications ?? true,
  });
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const zones = timeZones();
  const set = (k) => (e) => { setSaved(false); setForm({ ...form, [k]: e.target.value }); };

  async function save(e) {
    e.preventDefault();
    setError(null); setSaved(false); setBusy(true);
    try {
      const body = { ...form, country: form.country.trim() || null, paypal_email: form.paypal_email.trim() || null };
      setUser(await api("/api/me", { method: "PATCH", body }));
      setSaved(true);
    } catch (err) { setError(err); }
    setBusy(false);
  }

  return (
    <>
      <div className="page-head"><div><h1>Settings</h1></div></div>
      <form className="card card-pad" style={{ maxWidth: 620 }} onSubmit={save}>
        <Field label="Name"><input value={form.name} onChange={set("name")} /></Field>
        <Field label="Your currency" hint="New businesses start in this currency. Existing records keep theirs.">
          <select value={form.default_currency} onChange={set("default_currency")}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select>
        </Field>
        <div className="field-row">
          <Field label="Time zone" hint="Dates are shown in this zone; receipt times you enter are read in it">
            <select value={form.timezone} onChange={set("timezone")}>
              {(zones.includes(form.timezone) ? zones : [form.timezone, ...zones]).map((z) => <option key={z}>{z}</option>)}
            </select>
          </Field>
          <Field label="Country code" hint="Two letters, e.g. GB, US, DE">
            <input maxLength={2} value={form.country} onChange={(e) => set("country")({ target: { value: e.target.value.toUpperCase() } })} />
          </Field>
        </div>
        <h3 style={{ marginTop: 8 }}>PayPal</h3>
        <Field label="Your PayPal email"><input type="email" value={form.paypal_email} onChange={set("paypal_email")} /></Field>
        <label className="check" style={{ marginBottom: 18 }}>
          <input type="checkbox" checked={form.can_receive_paypal} onChange={(e) => { setSaved(false); setForm({ ...form, can_receive_paypal: e.target.checked }); }} />
          My PayPal account can receive payments
        </label>
        <h3 style={{ marginTop: 8 }}>Email</h3>
        <label className="check" style={{ marginBottom: 18 }}>
          <input type="checkbox" checked={form.email_notifications} onChange={(e) => { setSaved(false); setForm({ ...form, email_notifications: e.target.checked }); }} />
          Email me about payments, confirmations and disputes
        </label>
        <ErrorBox error={error} />
        <div className="row" style={{ gap: 12, alignItems: "center" }}>
          <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button>
          {saved && <span className="saved-note">✓ Saved</span>}
        </div>
      </form>
    </>
  );
}
