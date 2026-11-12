import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { getOpenBusiness } from "../openBusiness";
import { money } from "../format";
import { ErrorBox, Field, Modal } from "./ui";

const cents = (v) => Math.round(Number(String(v).replace(/,/g, "")) * 100);

function recordLabel(r) {
  return `${r.name}${r.local_id ? ` · ${r.local_id}` : ""} · ${r.business_name}`;
}

export function CheckEntry({ draft, onClose, onSaved }) {
  const { records, businesses, matches } = draft;
  const firstPick = draft.relationship_id || matches[0]?.relationship_id || "";
  const [mode, setMode] = useState(matches.length ? "existing" : businesses.length ? "new" : "existing");
  const [relId, setRelId] = useState(firstPick ? String(firstPick) : "");
  const [bizId, setBizId] = useState(String(draft.business_id || businesses[0]?.business_id || ""));
  const [name, setName] = useState(draft.new_person || "");
  const [side, setSide] = useState(draft.side || "receivable");
  const biz = businesses.find((b) => String(b.business_id) === bizId);
  const [localId, setLocalId] = useState(biz?.next_ids[side] || "");
  const [idEdited, setIdEdited] = useState(false);
  const [action, setAction] = useState(draft.action);
  const [amount, setAmount] = useState(draft.amount || "");
  const [method, setMethod] = useState(draft.method || "");
  const [description, setDescription] = useState(draft.description || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const rec = mode === "existing" ? records.find((r) => String(r.relationship_id) === relId) : null;
  const currency = rec ? rec.currency : biz?.currency;
  const owner = mode === "new" || rec?.role === "owner";
  const currencyClash = currency && draft.currency && draft.currency !== currency;
  const balance = rec ? rec.balance : "0.00";

  function pickBusiness(id) {
    setBizId(id);
    const b = businesses.find((x) => String(x.business_id) === id);
    if (!idEdited && b) setLocalId(b.next_ids[side]);
  }
  function pickSide(sd) {
    setSide(sd);
    if (!idEdited && biz) setLocalId(biz.next_ids[sd]);
  }

  async function save(e) {
    e.preventDefault(); setError(null);
    if (mode === "existing" && !rec) return setError(new Error("Choose the person"));
    if (mode === "new" && (!name.trim() || !biz)) return setError(new Error("Enter the name and business"));
    if (!(cents(amount) > 0)) return setError(new Error("Enter the amount"));
    const note = action === "subtract" ? [method.trim(), description.trim()].filter(Boolean).join(" · ") : description.trim();
    const body = {
      action, amount: (cents(amount) / 100).toFixed(2), description: note || null,
      ...(mode === "existing" ? { relationship_id: rec.relationship_id }
                              : { new_record: { business_id: biz.business_id, name: name.trim(), side, local_id: localId.trim() || null } }),
    };
    setBusy(true);
    try { const r = await api("/api/ai/save", { method: "POST", body }); onSaved(r.relationship_id); }
    catch (err) { setError(err); setBusy(false); }
  }

  const saveLabel = mode === "new" ? "Create record and save"
    : rec && !owner ? `Send to ${rec.name} to confirm`
    : action === "add" ? "Add money" : "Subtract money";

  return (
    <Modal title={<span className="row" style={{ gap: 10 }}>Check entry <span className="badge badge-blue">{draft.source}</span></span>} onClose={onClose} wide
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className={`btn ${action === "subtract" ? "btn-dark" : "btn-primary"}`} form="quick-form" disabled={busy}>{saveLabel}</button></>}>
      <form id="quick-form" onSubmit={save}>
        <ErrorBox error={error} />

        {matches.length > 0 && (
          <div className="choice-list">
            <div className="choice-q">{draft.new_person ? `Is “${draft.new_person}” one of these?` : "Which record?"}</div>
            {matches.map((m) => {
              const r = records.find((x) => x.relationship_id === m.relationship_id) || m;
              return (
                <label key={m.relationship_id} className={`choice ${mode === "existing" && relId === String(m.relationship_id) ? "on" : ""}`}>
                  <input type="radio" name="who" checked={mode === "existing" && relId === String(m.relationship_id)}
                         onChange={() => { setMode("existing"); setRelId(String(m.relationship_id)); }} />
                  <span><strong>Add to {r.name}</strong><span className="small muted"> {r.local_id ? `· ${r.local_id} ` : ""}· {r.business_name} · {money(r.balance, r.currency)}</span></span>
                </label>
              );
            })}
            {businesses.length > 0 && (
              <label className={`choice ${mode === "new" ? "on" : ""}`}>
                <input type="radio" name="who" checked={mode === "new"} onChange={() => setMode("new")} />
                <span><strong>Create a new record{draft.new_person ? ` for ${draft.new_person}` : ""}</strong></span>
              </label>
            )}
          </div>
        )}

        {mode === "existing" && matches.length === 0 && (
          <Field label="Person">
            <select value={relId} onChange={(e) => setRelId(e.target.value)}>
              <option value="">Choose…</option>
              {records.map((r) => <option key={r.relationship_id} value={r.relationship_id}>{recordLabel(r)}</option>)}
            </select>
          </Field>
        )}

        {mode === "new" && (
          <div className="new-record">
            {matches.length === 0 && <div className="choice-q">New record</div>}
            <div className="field-row">
              <Field label="Name"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Your ID"><input className="mono" value={localId} onChange={(e) => { setIdEdited(true); setLocalId(e.target.value); }} /></Field>
            </div>
            <div className="field-row">
              <Field label="Business">
                <select value={bizId} onChange={(e) => pickBusiness(e.target.value)}>
                  {businesses.map((b) => <option key={b.business_id} value={b.business_id}>{b.name}</option>)}
                </select>
              </Field>
              <Field label="They are">
                <div className="segmented">
                  <button type="button" className={side === "receivable" ? "on" : ""} onClick={() => pickSide("receivable")}>Customer (owes me)</button>
                  <button type="button" className={side === "payable" ? "on" : ""} onClick={() => pickSide("payable")}>Supplier (I owe)</button>
                </div>
              </Field>
            </div>
            {matches.length === 0 && records.length > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode("existing")}>Choose an existing record instead</button>
            )}
          </div>
        )}
        {mode === "existing" && matches.length === 0 && businesses.length > 0 && (
          <button type="button" className="btn btn-ghost btn-sm" style={{ marginBottom: 10 }} onClick={() => setMode("new")}>Create a new record instead</button>
        )}

        <div className="segmented" style={{ margin: "8px 0 14px" }}>
          <button type="button" className={action === "add" ? "on" : ""} onClick={() => setAction("add")}>Add money</button>
          <button type="button" className={action === "subtract" ? "on" : ""} onClick={() => setAction("subtract")}>Subtract money</button>
        </div>
        <div className="field-row">
          <Field label={`Amount${currency ? ` (${currency})` : ""}`}>
            <input required autoFocus={!draft.amount} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
          </Field>
          {action === "subtract"
            ? <Field label="Payment method"><input value={method} onChange={(e) => setMethod(e.target.value)} /></Field>
            : <Field label="Description"><input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>}
        </div>
        {action === "subtract" && <Field label="Description"><input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>}
        {currencyClash && <div className="alert alert-warn">The note says {draft.currency}; this record is in {currency}.</div>}
        {currency && cents(amount) > 0 && (
          <div className="money-preview small">
            Balance {money(balance, currency)} → <strong>{money((cents(balance) + (action === "add" ? 1 : -1) * cents(amount)) / 100, currency)}</strong>
          </div>
        )}
      </form>
    </Modal>
  );
}

export default function QuickEntry({ onSaved }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(null);
  const navigate = useNavigate();

  async function read(e) {
    e.preventDefault();
    if (text.trim().length < 2) return;
    setBusy(true); setError(null);
    try { setDraft(await api("/api/ai/entry", { method: "POST", body: { text, business_id: getOpenBusiness() } })); }
    catch (err) { setError(err); }
    setBusy(false);
  }

  return (
    <>
      <form className="quick-entry" onSubmit={read}>
        <span className="quick-icon" aria-hidden="true">✦</span>
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={500}
               placeholder="Type an entry… e.g. Marwan took 5 kg milk for $20" aria-label="Type an entry" />
        <button className="btn btn-primary" disabled={busy || text.trim().length < 2}>{busy ? "Reading…" : "Read"}</button>
      </form>
      <ErrorBox error={error} />
      {draft && <CheckEntry draft={draft} onClose={() => setDraft(null)}
                            onSaved={(id) => { setDraft(null); setText(""); onSaved?.(); navigate(`/records/${id}`); }} />}
    </>
  );
}
