import { useEffect, useState } from "react";
import { api } from "../api";
import { PayPalLiveLine } from "./PayPalLive";
import { dateTime } from "../format";
import { ErrorBox, Field } from "./ui";

export function usePayPalStatus() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const reload = () => api("/api/paypal/status").then(setStatus).catch(setError);
  useEffect(() => { reload(); }, []);
  return { status, setStatus, error, reload };
}

export async function startPayPalConnect() {
  const { url } = await api("/api/paypal/connect-url");
  window.location.href = url;
}

export function ConnectPayPalButton({ className = "btn btn-paypal", label = "Connect with PayPal", onError }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className={className} disabled={busy}
            onClick={async () => { setBusy(true); try { await startPayPalConnect(); } catch (err) { onError?.(err); setBusy(false); } }}>
      <span className="pp-mark" aria-hidden="true">P</span>{busy ? "Opening PayPal…" : label}
    </button>
  );
}

function PasteLink({ onDone, onError }) {
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); onError(null);
    // read code/state from the raw link: URLSearchParams would turn a "+" in the code into a space
    const raw = (name) => {
      const m = link.trim().match(new RegExp(`[?&]${name}=([^&#]*)`));
      return m ? decodeURIComponent(m[1]) : "";
    };
    const code = raw("code"), state = raw("state");
    if (!code || !state) { onError(new Error("Paste the whole link from the address bar (it has code= in it)")); return; }
    setBusy(true);
    try { await api("/api/paypal/callback", { method: "POST", body: { code, state } }); setLink(""); onDone(); }
    catch (err) { onError(err); setBusy(false); }
  }
  return (
    <form onSubmit={submit} style={{ marginTop: 16 }}>
      <Field label="Link PayPal sent you to"><input value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://example.com/?code=…" autoComplete="off" /></Field>
      <button className="btn btn-primary btn-sm" disabled={busy || !link.trim()}>{busy ? "Connecting…" : "Finish connecting"}</button>
    </form>
  );
}

function AccountCard({ status, setStatus, tz }) {
  const [error, setError] = useState(null);
  const c = status.connected;
  async function disconnect() {
    try { setStatus(await api("/api/paypal/connection", { method: "DELETE" })); } catch (err) { setError(err); }
  }
  return (
    <div className="card card-pad">
      <div className="card-head"><h2>PayPal account</h2>{c && <span className="badge badge-solid">Connected</span>}</div>
      <ErrorBox error={error} />
      {c ? (
        <>
          <dl className="kv">
            <dt>Email</dt><dd>{c.email}</dd>
            {c.name && <><dt>Name</dt><dd>{c.name}</dd></>}
            <dt>Status</dt><dd>{c.verified === true ? "Verified by PayPal" : c.verified === false ? "Unverified PayPal account" : "—"}</dd>
            <dt>Connected</dt><dd>{dateTime(c.connected_at, tz)}</dd>
          </dl>
          <button className="btn btn-outline btn-sm" style={{ marginTop: 14 }} onClick={disconnect}>Disconnect</button>
        </>
      ) : status.login_enabled ? (
        <>
          <ConnectPayPalButton onError={setError} />
          {status.paste_mode && <PasteLink onError={setError} onDone={async () => setStatus(await api("/api/paypal/status"))} />}
        </>
      ) : (
        <p className="muted">PayPal isn't set up on this server.</p>
      )}
    </div>
  );
}

function AutoCheckCard({ status, setStatus, tz }) {
  const a = status.autocheck;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ client_id: "", secret: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { setStatus(await api("/api/paypal/autocheck", { method: "PUT", body: form })); setEditing(false); setForm({ client_id: "", secret: "" }); }
    catch (err) { setError(err); }
    setBusy(false);
  }
  async function turnOff() {
    try { setStatus(await api("/api/paypal/autocheck", { method: "DELETE" })); } catch (err) { setError(err); }
  }
  return (
    <div className="card card-pad" id="paypal">
      <div className="card-head"><h2>Automatic payment check</h2>{a.enabled && <span className="badge badge-solid">On</span>}</div>
      <ErrorBox error={error} />
      {a.enabled && !editing ? (
        <>
          <dl className="kv">
            <dt>PayPal app</dt><dd><span className="mono">{a.client_id_hint}</span>{a.source === "app" && <span className="muted small"> · Khataz's PayPal app, always on</span>}</dd>
            {a.error && <><dt>Problem</dt><dd style={{ color: "var(--danger)" }}>{a.error}</dd></>}
          </dl>
          <div style={{ marginTop: 12 }}><PayPalLiveLine onConfirmed={async () => setStatus(await api("/api/paypal/status"))} /></div>
          <div className="row" style={{ marginTop: 14 }}>
            {a.source !== "app" && <>
              <button className="btn btn-outline btn-sm" onClick={() => setEditing(true)}>Change app</button>
              <button className="btn btn-ghost btn-sm" onClick={turnOff}>Turn off</button>
            </>}
          </div>
        </>
      ) : (
        <form onSubmit={save}>
          <Field label="Client ID"><input className="mono" required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} autoComplete="off" /></Field>
          <Field label="Secret"><input className="mono" type="password" required value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} autoComplete="new-password" /></Field>
          <div className="row">
            <button className="btn btn-primary btn-sm" disabled={busy}>{busy ? "Checking with PayPal…" : "Turn on"}</button>
            {editing && <button type="button" className="btn btn-outline btn-sm" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </form>
      )}
    </div>
  );
}

export default function PayPalSettings({ tz }) {
  const { status, setStatus, error } = usePayPalStatus();
  if (error) return <ErrorBox error={error} />;
  if (!status) return null;
  return (
    <div className="paypal-grid">
      <AccountCard status={status} setStatus={setStatus} tz={tz} />
      <AutoCheckCard status={status} setStatus={setStatus} tz={tz} />
    </div>
  );
}
