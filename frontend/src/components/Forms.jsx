import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { CURRENCIES } from "../format";
import { ErrorBox, Field, Modal } from "./ui";

function CurrencySelect({ value, onChange }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
    </select>
  );
}

export function AddBusinessModal({ onClose, onCreated }) {
  const { user } = useAuth();
  const [form, setForm] = useState({ name: "", category: "", default_currency: user?.default_currency || "USD" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const b = await api("/api/businesses", { method: "POST", body: { ...form, category: form.category || null } });
      onCreated(b);
    } catch (err) { setError(err); setBusy(false); }
  }

  return (
    <Modal title="Add business" onClose={onClose}
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className="btn btn-primary" form="add-biz" disabled={busy}>Create business</button></>}>
      <form id="add-biz" onSubmit={submit}>
        <ErrorBox error={error} />
        <Field label="Business name"><input required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <div className="field-row">
          <Field label="Category (optional)"><input value={form.category} placeholder="e.g. Dairy" onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
          <Field label="Currency" hint="Your account currency. Change it only if this business uses another">
            <CurrencySelect value={form.default_currency} onChange={(v) => setForm({ ...form, default_currency: v })} />
          </Field>
        </div>
      </form>
    </Modal>
  );
}

export function AddPersonModal({ business: fixedBusiness, businesses, note, side: initialSide, initial = {}, onClose, onCreated }) {
  const [businessId, setBusinessId] = useState(fixedBusiness?.id ?? businesses?.[0]?.id);
  const business = fixedBusiness || businesses?.find((b) => b.id === Number(businessId)) || businesses?.[0];
  const [form, setForm] = useState({
    name: "", side: initialSide || "receivable",
    email: "", phone: "", company: "", paypal_email: "", notes: "", khataz_id: "", local_id: "", ...initial,
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, typeof v === "string" && v.trim() === "" ? null : v]));
    if (body.khataz_id) body.khataz_id = body.khataz_id.trim().replace(/^@/, "");
    if (body.local_id) body.local_id = body.local_id.trim().replace(/^#/, "");
    if (!body.khataz_id && !body.local_id) {
      setBusy(false);
      setError(new Error("Enter their Khataz ID, or give them your own ID (for example CUST-001)."));
      return;
    }
    try { onCreated(await api(`/api/businesses/${business.id}/contacts`, { method: "POST", body })); }
    catch (err) { setError(err); setBusy(false); }
  }

  return (
    <Modal title={fixedBusiness ? `Add person to ${business.name}` : "Add to your records"} onClose={onClose}
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className="btn btn-primary" form="add-person" disabled={busy}>Add person</button></>}>
      <form id="add-person" onSubmit={submit}>
        {note && <p className="small muted" style={{ marginTop: 0 }}>{note}</p>}
        <ErrorBox error={error} />
        {!fixedBusiness && (
          <Field label="Business">
            <select value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
              {businesses.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Which book?">
          <div className="segmented">
            <button type="button" className={form.side === "receivable" ? "on" : ""} onClick={() => setForm({ ...form, side: "receivable" })}>They owe me</button>
            <button type="button" className={form.side === "payable" ? "on" : ""} onClick={() => setForm({ ...form, side: "payable" })}>I owe them</button>
          </div>
        </Field>
        <Field label="Name" hint={business ? `Amounts are in ${business.default_currency}, the currency of ${business.name}` : undefined}>
          <input required autoFocus value={form.name} onChange={set("name")} />
        </Field>
        <div className="id-pair">
          <Field label="Khataz ID" hint="If you know it. They'll be asked to link so you share this record">
            <div className="prefix-input"><span>@</span><input value={form.khataz_id} onChange={set("khataz_id")} placeholder="their.id" autoCapitalize="off" spellCheck="false" /></div>
          </Field>
          <span className="id-or">or</span>
          <Field label="Your ID for them" hint="Unique in this business. Only you see it">
            <div className="prefix-input"><span>#</span><input value={form.local_id} onChange={set("local_id")} placeholder="CUST-001" autoCapitalize="characters" spellCheck="false" maxLength={30} /></div>
          </Field>
        </div>
        <div className="field-row">
          <Field label="Email (optional)" hint="Used to invite them to Khataz"><input type="email" value={form.email} onChange={set("email")} /></Field>
          <Field label="Phone (optional)"><input value={form.phone} onChange={set("phone")} /></Field>
        </div>
        <div className="field-row">
          <Field label="Business name (optional)"><input value={form.company} onChange={set("company")} /></Field>
          <Field label="PayPal email (optional)" hint="Helps match their payments"><input type="email" value={form.paypal_email} onChange={set("paypal_email")} /></Field>
        </div>
        <Field label="Private notes (optional)" hint="Only you can see these"><textarea value={form.notes} onChange={set("notes")} /></Field>
      </form>
    </Modal>
  );
}

export { CurrencySelect };
