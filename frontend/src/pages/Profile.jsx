import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import PayPalSettings from "../components/PayPalSettings";
import { Avatar, ErrorBox } from "../components/ui";
import { dateOnly } from "../format";

export default function Profile() {
  const { user, setUser } = useAuth();
  const input = useRef();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  async function upload(file) {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setUser(await api("/api/me/avatar", { method: "POST", form: fd }));
    } catch (err) { setError(err); }
    setBusy(false);
    input.current.value = "";
  }

  async function remove() {
    setBusy(true); setError(null);
    try { setUser(await api("/api/me/avatar", { method: "DELETE" })); } catch (err) { setError(err); }
    setBusy(false);
  }

  async function copyId() {
    try { await navigator.clipboard.writeText(`@${user.khataz_id}`); setCopied(true); setTimeout(() => setCopied(false), 1800); }
    catch { /* clipboard blocked: the ID is still visible to copy by hand */ }
  }

  return (
    <>
      <div className="page-head"><div><h1>Your profile</h1></div></div>

      <div className="card profile-card">
        <div className="profile-hero">
          <div className="profile-photo">
            <Avatar khatazId={user.khataz_id} hasAvatar={user.has_avatar} version={user.avatar_version} name={user.name} size={128} />
            {busy && <span className="profile-busy"><span className="spinner" /></span>}
          </div>
          <div>
            <h2 style={{ fontSize: 26, color: "var(--white)" }}>{user.name}</h2>
            <div className="profile-id">
              <span className="mono">@{user.khataz_id}</span>
              <button className="btn btn-sm profile-copy" onClick={copyId}>{copied ? "Copied" : "Copy ID"}</button>
            </div>
          </div>
        </div>

        <div className="card-pad">
          <ErrorBox error={error} />
          <div className="row" style={{ marginBottom: 20 }}>
            <button className="btn btn-primary" disabled={busy} onClick={() => input.current.click()}>{user.has_avatar ? "Change picture" : "Upload picture"}</button>
            {user.has_avatar && <button className="btn btn-outline" disabled={busy} onClick={remove}>Remove picture</button>}
            <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => upload(e.target.files[0])} />
          </div>

          <dl className="kv profile-kv">
            <dt>Khataz ID</dt><dd><span className="mono">@{user.khataz_id}</span></dd>
            <dt>Name</dt><dd>{user.name}</dd>
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Currency</dt><dd>{user.default_currency}</dd>
            <dt>Time zone</dt><dd>{user.timezone}</dd>
            {user.country && <><dt>Country</dt><dd>{user.country}</dd></>}
            <dt>PayPal</dt><dd>{user.paypal_verified_email
              ? <span className="verified-line">{user.paypal_verified_email} <span className="tick">✓</span></span>
              : user.paypal_email || <span className="muted">not connected</span>}</dd>
            {user.created_at && <><dt>Member since</dt><dd>{dateOnly(user.created_at, user.timezone)}</dd></>}
          </dl>
          <Link to="/settings" className="btn btn-outline" style={{ marginTop: 20 }}>Edit details</Link>
        </div>
      </div>

      <PayPalSettings tz={user.timezone} />
    </>
  );
}
