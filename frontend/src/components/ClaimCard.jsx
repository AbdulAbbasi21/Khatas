import { useState } from "react";
import { api } from "../api";
import { PayPalLiveLine } from "./PayPalLive";
import { CLAIM_STATE, dateTime, money } from "../format";
import { CurrencySelect } from "./Forms";
import { AuthImage, ErrorBox, Field, Modal } from "./ui";

function ConfirmForm({ claim, rel, onDone }) {
  const [response, setResponse] = useState("received");
  const [form, setForm] = useState({
    received_amount: claim.claimed_amount, received_currency: claim.claimed_currency,
    payer_name_seen: "", recipient_txn_id: "", manual_rate: "",
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [paypalNote, setPaypalNote] = useState(null); // PayPal doesn't show the payment (yet)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const differentCurrency = form.received_currency !== rel.summary.currency;

  async function submit(withoutPaypal = false) {
    setBusy(true); setError(null); setPaypalNote(null);
    const body = response === "not_received" ? { response } : {
      confirm_without_paypal: withoutPaypal,
      response,
      received_amount: form.received_amount || null,
      received_currency: form.received_currency,
      payer_name_seen: form.payer_name_seen || null,
      recipient_txn_id: form.recipient_txn_id || null,
      manual_rate: form.manual_rate || null,
    };
    try { await api(`/api/claims/${claim.id}/respond`, { method: "POST", body }); onDone(); }
    catch (err) {
      if (err.status === 409 && err.message.startsWith("PAYPAL_CHECK: ")) setPaypalNote(err.message.slice(14));
      else setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="card card-pad" style={{ marginTop: 12, background: "var(--surface)", boxShadow: "none" }}>
      <p><strong>Did this money arrive in your PayPal?</strong></p>
      {claim.auto_check && <p className="muted small">Khataz checks your PayPal for this first and credits only what actually arrived.</p>}
      <ErrorBox error={error} />
      {paypalNote && (
        <div className="alert alert-warn" style={{ margin: "10px 0" }}>
          <p>{paypalNote}</p>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <button className="btn btn-outline" disabled={busy} onClick={() => submit(false)}>Check PayPal again</button>
            <button className="btn btn-outline" disabled={busy} onClick={() => submit(true)}>Confirm without PayPal</button>
          </div>
        </div>
      )}
      <div className="segmented" style={{ margin: "10px 0 14px" }}>
        {[["received", "Yes, received"], ["different_amount", "Different amount"], ["not_received", "Not received"]].map(([k, label]) => (
          <button key={k} type="button" className={response === k ? "on" : ""} onClick={() => setResponse(k)}>{label}</button>
        ))}
      </div>
      {response !== "not_received" && (
        <>
          <div className="field-row">
            <Field label="Amount that arrived" hint="After PayPal fees and conversion">
              <input inputMode="decimal" value={form.received_amount} onChange={set("received_amount")} />
            </Field>
            <Field label="Currency"><CurrencySelect value={form.received_currency} onChange={(v) => setForm({ ...form, received_currency: v })} /></Field>
          </div>
          <div className="field-row">
            <Field label="Sender name in your PayPal (optional)" hint="Flags payments made by someone else">
              <input value={form.payer_name_seen} onChange={set("payer_name_seen")} />
            </Field>
            <Field label="Your transaction ID (optional)"><input className="mono" value={form.recipient_txn_id} onChange={set("recipient_txn_id")} /></Field>
          </div>
          {differentCurrency && (
            <Field label={`Exchange rate ${form.received_currency} → ${rel.summary.currency} (optional)`} hint="Leave empty to use the day's market rate">
              <input inputMode="decimal" value={form.manual_rate} onChange={set("manual_rate")} />
            </Field>
          )}
        </>
      )}
      <button className={`btn ${response === "not_received" ? "btn-danger" : "btn-primary"}`} disabled={busy} onClick={() => submit(false)}>
        {response === "not_received" ? "I did not receive it" : "Confirm"}
      </button>
    </div>
  );
}

function ReviewForm({ claim, rel, onDone }) {
  const [amount, setAmount] = useState(claim.converted_amount || "");
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function act(action) {
    setBusy(true); setError(null);
    try {
      await api(`/api/claims/${claim.id}/resolve`, { method: "POST", body: { action, amount: action === "allocate" ? amount || null : null, note: note || null } });
      onDone();
    } catch (err) { setError(err); setBusy(false); }
  }

  return (
    <div className="card card-pad" style={{ marginTop: 12, background: "var(--surface)", boxShadow: "none" }}>
      <p><strong>Your decision is needed</strong></p>
      <ul className="small" style={{ margin: "0 0 12px", paddingLeft: 18 }}>
        {claim.review_reason_text.map((r) => <li key={r}>{r}</li>)}
      </ul>
      <ErrorBox error={error} />
      <div className="field-row">
        <Field label={`Amount to take off the balance (${rel.summary.currency})`}><input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Note (kept in the history)"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <div className="row">
        <button className="btn btn-primary" disabled={busy} onClick={() => act("allocate")}>Apply to balance</button>
        {claim.state !== "held" && <button className="btn btn-outline" disabled={busy} onClick={() => act("hold")}>Keep on hold</button>}
        <button className="btn btn-danger" disabled={busy} onClick={() => act("reject")}>Reject</button>
      </div>
    </div>
  );
}

function ReverseButton({ claim, onDone }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  async function go() {
    try { await api(`/api/claims/${claim.id}/reverse`, { method: "POST", body: { reason } }); setOpen(false); onDone(); }
    catch (err) { setError(err); }
  }
  return (
    <>
      <button className="btn btn-ghost btn-sm" onClick={() => setOpen(true)}>Refund or chargeback…</button>
      {open && (
        <Modal title="Reverse this payment" onClose={() => setOpen(false)}
               footer={<><button className="btn btn-outline" onClick={() => setOpen(false)}>Cancel</button>
                         <button className="btn btn-danger" disabled={!reason.trim()} onClick={go}>Reverse payment</button></>}>
          <ErrorBox error={error} />
          <Field label="Reason"><input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. PayPal chargeback on 12 Nov" /></Field>
        </Modal>
      )}
    </>
  );
}

function AutoCheckLine({ claim, onDone }) {
  return <div className="auto-line"><PayPalLiveLine claimId={claim.id} onConfirmed={onDone} /></div>;
}

const VERDICT = {
  match: ["ok", "Amount matches"], linked_match: ["ok", "Amount matches"],
  different_amount: ["bad", "Amount is different"], linked_differs: ["bad", "Amount is different"],
  pending: ["warn", "Not completed yet"], not_found: ["warn", "Not in your PayPal yet"],
  linked_missing: ["warn", "Transaction not found"], no_identity: ["grey", "Sender not connected"],
  off: ["grey", "PayPal check is off"], error: ["bad", "Couldn't check PayPal"],
};

function PayPalCheckPanel({ claim, tz }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function load() {
    setBusy(true); setError(null);
    try { setData(await api(`/api/claims/${claim.id}/paypal`)); } catch (err) { setError(err); }
    setBusy(false);
  }
  function toggle() { const next = !open; setOpen(next); if (next && !data) load(); }
  const [tone, title] = data ? (VERDICT[data.verdict] || ["grey", data.verdict]) : [];
  return (
    <div className="pp-check">
      <button className="btn btn-outline btn-sm" onClick={toggle} aria-expanded={open}>
        <span className="pp-mark" aria-hidden="true">P</span>{open ? "Hide PayPal check" : "PayPal check"}
      </button>
      {open && (
        <div className="pp-check-body">
          <ErrorBox error={error} />
          {busy && !data && <p className="small muted">Looking in your PayPal account…</p>}
          {data && <>
            <div className={`pp-verdict pp-verdict-${tone}`}>
              <strong>{title}</strong>
              <span>{data.message}</span>
            </div>
            <div className="pp-compare">
              <div><span className="small muted">Claimed</span><strong>{money(data.claimed_amount, data.claimed_currency)}</strong></div>
              <div><span className="small muted">In your PayPal</span><strong>{(() => {
                const p = data.payments.find((x) => x.note === "this payment") || (["match", "different_amount"].includes(data.verdict) && data.payments.find((x) => !x.note && x.status === "completed"));
                return p ? money(p.amount, p.currency) : "—";
              })()}</strong></div>
            </div>
            {data.payments.length > 0 && (
              <table className="pp-table">
                <thead><tr><th>PayPal transaction</th><th>Amount</th><th>From</th><th>When</th><th>Status</th></tr></thead>
                <tbody>{data.payments.map((p) => (
                  <tr key={p.id} className={p.note === "this payment" ? "is-this" : ""}>
                    <td className="mono">{p.id}{p.note && <div className="small muted">{p.note}</div>}</td>
                    <td><strong>{money(p.amount, p.currency)}</strong></td>
                    <td>{p.from}</td>
                    <td>{p.at ? dateTime(p.at, tz) : "—"}</td>
                    <td>{p.status}</td>
                  </tr>))}</tbody>
              </table>
            )}
            <div className="row" style={{ gap: 10, marginTop: 8 }}>
              <span className="small muted">Read from your PayPal {dateTime(data.checked_at, tz)}</span>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={load}>{busy ? "Checking…" : "Refresh"}</button>
            </div>
          </>}
        </div>
      )}
    </div>
  );
}

export default function ClaimCard({ claim, rel, tz, onChange }) {
  const [zoom, setZoom] = useState(null);
  const st = CLAIM_STATE[claim.state] || { label: claim.state, cls: "badge-grey" };
  const me = rel.my_user_id;
  const iAmRecipient = claim.recipient_user_id === me;
  const by = rel.names[claim.submitted_by] || "Someone";

  return (
    <div className="claim">
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
          {claim.has_image && <AuthImage src={`/api/claims/${claim.id}/image`} className="thumb" alt="Payment screenshot" onClick={setZoom} />}
          <div>
            <div className="row">
              <span className="small muted">{claim.submitted_by === me ? "You said" : `${by} says`}</span>
              <span className="amount" style={{ fontSize: 18 }}>{money(claim.claimed_amount, claim.claimed_currency)}</span>
              <span className={`badge ${st.cls}`}>{st.label}</span>
              {claim.auto_confirmed && <span className="badge badge-solid">Confirmed by PayPal</span>}
            </div>
            <dl className="kv" style={{ marginTop: 6 }}>
              <dt>Sent by</dt><dd>{claim.payer_name || "—"} <span className="muted small">(submitted by {claim.submitted_by === me ? "you" : by})</span></dd>
              {claim.payer_paypal_email && <><dt>PayPal account</dt><dd><span className="verified-line">{claim.payer_paypal_email} <span className="tick" title="Who paid is verified with Log in with PayPal. The amount is checked separately.">✓ verified sender</span></span></dd></>}
              {claim.sender_txn_id && <><dt>Their transaction ID</dt><dd className="mono">{claim.sender_txn_id}</dd></>}
              {claim.paid_at && <><dt>Paid</dt><dd>{dateTime(claim.paid_at, tz)}</dd></>}
              {claim.received_amount && <><dt>{claim.auto_confirmed ? "PayPal shows" : "Arrived"}</dt><dd>{money(claim.received_amount, claim.received_currency)}{claim.converted_amount && claim.received_currency !== rel.summary.currency ? ` = ${money(claim.converted_amount, rel.summary.currency)}` : ""}{claim.fx_source && claim.fx_source !== "same currency" ? <span className="muted small"> · rate {Number(claim.fx_rate).toFixed(4)} ({claim.fx_source})</span> : ""}</dd></>}
              {claim.note && <><dt>Note</dt><dd>{claim.note}</dd></>}
              {claim.resolution_note && <><dt>Decision</dt><dd>{claim.resolution_note}</dd></>}
            </dl>
          </div>
        </div>
        <div className="row">
          {iAmRecipient && claim.state === "allocated" && <ReverseButton claim={claim} onDone={onChange} />}
          <span className="small muted">{dateTime(claim.created_at, tz)}</span>
        </div>
      </div>
      {iAmRecipient && (claim.payer_paypal_email || claim.recipient_txn_id) && <PayPalCheckPanel claim={claim} tz={tz} />}
      {iAmRecipient && claim.state === "pending_confirmation" && claim.auto_check && <AutoCheckLine claim={claim} onDone={onChange} />}
      {iAmRecipient && claim.state === "pending_confirmation" && <ConfirmForm claim={claim} rel={rel} onDone={onChange} />}
      {iAmRecipient && ["needs_review", "held"].includes(claim.state) && <ReviewForm claim={claim} rel={rel} onDone={onChange} />}
      {zoom && <Modal title="Payment screenshot" wide onClose={() => setZoom(null)}><img src={zoom} alt="Payment screenshot" className="preview-img" style={{ maxHeight: "75vh" }} /></Modal>}
    </div>
  );
}
