import { useRef, useState } from "react";
import { ConnectPayPalButton, usePayPalStatus } from "./PayPalSettings";
import { api } from "../api";
import { todayLocal } from "../format";
import { CurrencySelect } from "./Forms";
import { ErrorBox, Field, Modal } from "./ui";

/**
 * "I paid by PayPal": 1) upload the PayPal receipt -> it must be a PayPal receipt, details are
 * read from it, 2) check the details -> send. The recipient gets the details and the image.
 */
export default function ClaimFlowModal({ rel, iAmDebtor, onClose, onDone }) {
  const s = rel.summary;
  const [step, setStep] = useState("upload");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    amount: "", currency: s.currency, sender_txn_id: "", paid_at_local: "",
    payer_name: rel.debtor, payee_name: "", paypal_status: "", note: "",
  });
  const input = useRef();
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const { status: pp } = usePayPalStatus();
  const mustConnect = iAmDebtor && pp?.login_enabled && !pp?.connected;

  function choose(f) {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setError(null);
  }

  async function runScan() {
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api(`/api/relationships/${s.id}/claims/scan`, { method: "POST", form: fd });
      if (r.is_paypal_receipt === false) {
        setScan(null);
        setError(new Error(`Not a PayPal receipt. ${r.reason || ""}`.trim()));
        setBusy(false);
        return;
      }
      setScan(r);
      const p = r.prefill || {};
      setForm((f) => ({
        ...f,
        amount: p.amount ?? f.amount,
        currency: p.currency || f.currency,
        sender_txn_id: p.sender_txn_id || f.sender_txn_id,
        paid_at_local: p.paid_at_local ? p.paid_at_local.slice(0, 10) : f.paid_at_local, // keep the date, drop the time
        payee_name: p.payee_name || f.payee_name,
        payer_name: p.payer_name || f.payer_name,
        paypal_status: p.paypal_status || f.paypal_status,
      }));
      setStep("details");
    } catch (err) { setError(err); }
    setBusy(false);
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    const body = {
      ...form,
      sender_txn_id: form.sender_txn_id.trim() || null,
      paid_at_local: form.paid_at_local ? `${form.paid_at_local}T12:00:00` : null, // date only: midday
      payee_name: form.payee_name || null,
      paypal_status: form.paypal_status || null,
      payer_name: form.payer_name || null,
      note: form.note || null,
      image_hash: scan?.image_hash || null,
      extracted: scan?.scan?.receipt || null,
    };
    try {
      await api(`/api/relationships/${s.id}/claims`, { method: "POST", body });
      onDone();
    } catch (err) { setError(err); setBusy(false); }
  }

  const title = iAmDebtor ? `I paid ${rel.creditor} by PayPal` : `Log a PayPal payment from ${rel.debtor}`;

  if (mustConnect) {
    return (
      <Modal title={title} onClose={onClose}>
        <ErrorBox error={error} />
        <div className="connect-gate">
          <p>Connect your PayPal account first.</p>
          {pp.paste_mode ? <a className="btn btn-paypal" href="/profile"><span className="pp-mark" aria-hidden="true">P</span>Connect on your profile</a>
                         : <ConnectPayPalButton onError={setError} />}
        </div>
      </Modal>
    );
  }

  if (step === "upload") {
    return (
      <Modal title={title} onClose={onClose} wide
             footer={<>
               <button className="btn btn-outline" onClick={onClose}>Cancel</button>
               <button className="btn btn-primary" disabled={!file || busy} onClick={runScan}>{busy ? "Checking receipt…" : "Check receipt"}</button>
             </>}>
        <ErrorBox error={error} />
        <div className="dropzone" onClick={() => input.current.click()}
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files[0]); }}>
          {preview ? <img src={preview} alt="Selected receipt" className="preview-img" />
                   : <strong>Drop the PayPal receipt here or click to choose</strong>}
          <input ref={input} type="file" accept="image/*" hidden onChange={(e) => choose(e.target.files[0])} />
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={title} onClose={onClose} wide
           footer={<>
             <button className="btn btn-outline" onClick={() => setStep("upload")}>Back</button>
             <button className="btn btn-primary" form="claim-form" disabled={busy || scan?.duplicate_claim_id}>{busy ? "Sending…" : iAmDebtor ? `Send to ${rel.creditor} to confirm` : "Save payment"}</button>
           </>}>
      <ErrorBox error={error} />
      {scan?.warnings?.length > 0 && (
        <div className={`alert ${scan.duplicate_claim_id ? "alert-error" : "alert-warn"}`} style={{ marginBottom: 14 }}>
          <strong>Check before sending</strong>
          <ul>{scan.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      <div className="claim-receipt">
        {preview && <img src={preview} alt="PayPal receipt" className="preview-img" />}
      </div>
      <form id="claim-form" onSubmit={submit}>
        <div className="field-row">
          <Field label="Amount sent"><input required inputMode="decimal" value={form.amount} onChange={set("amount")} placeholder="0.00" /></Field>
          <Field label="Currency"><CurrencySelect value={form.currency} onChange={(v) => setForm({ ...form, currency: v })} /></Field>
        </div>
        <div className="field-row">
          <Field label="PayPal transaction ID">
            <input className="mono" value={form.sender_txn_id} onChange={set("sender_txn_id")} placeholder="5TY05013RG002845M" />
          </Field>
          <Field label="Date on the receipt">
            <input type="date" value={form.paid_at_local} max={todayLocal()} onChange={set("paid_at_local")} />
          </Field>
        </div>
        <div className="field-row">
          <Field label="Paid by">
            <input value={form.payer_name} onChange={set("payer_name")} />
          </Field>
          <Field label="Paid to (as shown on the receipt)"><input value={form.payee_name} onChange={set("payee_name")} placeholder={rel.creditor} /></Field>
        </div>
        <div className="field-row">
          <Field label="PayPal status"><input value={form.paypal_status} onChange={set("paypal_status")} placeholder="Completed" /></Field>
          <Field label="Note (optional)"><input value={form.note} onChange={set("note")} /></Field>
        </div>
      </form>
    </Modal>
  );
}
