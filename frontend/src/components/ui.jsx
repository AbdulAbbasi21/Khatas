import { useEffect, useState } from "react";
import { apiBlobUrl } from "../api";
import { absMoney, initials } from "../format";

export function Logo({ light }) {
  return (
    <span className="brand" style={light ? { color: "#fff" } : undefined}>
      <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill={light ? "#fff" : "#003087"} />
        <path d="M10 7h4v7.5L20 7h5l-7 8 7.5 10H20.5L15.7 18 14 20v5h-4z" fill={light ? "#003087" : "#fff"} />
        <circle cx="24" cy="24" r="3" fill="#009CDE" />
      </svg>
      <span>Khata<b>z</b></span>
    </span>
  );
}

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      {children}
    </div>
  );
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="alert alert-error" role="alert">{String(error.message || error)}</div>;
}

export function Loading() {
  return <div className="center-load"><span className="spinner" /></div>;
}

/** Balance from the viewer's side: blue = owed to me, black = I owe. */
export function Balance({ amount, currency, perspective, big }) {
  const n = Number(amount);
  // below zero the money runs the other way: a customer at -10 is someone I owe 10
  const cls = n === 0 ? "zero" : (perspective === "owed_to_me") === (n > 0) ? "owed" : "owe";
  return <span className={`amount ${cls}${big ? " big-balance" : ""}`}>{absMoney(amount, currency)}</span>;
}

/** "Marwan owes you" / "You owe Marwan" / "Settled" for a balance on a record. */
export function owesPhrase(perspective, who, balanceCents) {
  if (balanceCents === 0) return "Settled";
  return (perspective === "owed_to_me") === (balanceCents > 0) ? `${who} owes you` : `You owe ${who}`;
}

export function balanceSentence(summary) {
  const n = Number(summary.balance);
  const who = summary.other_party;
  if (n === 0) return `You and ${who} are settled`;
  if (summary.perspective === "owed_to_me") return n > 0 ? `${who} owes you` : `You owe ${who}`;
  return n > 0 ? `You owe ${who}` : `${who} owes you`;
}

/** Profile picture, or initials when there is none. */
export function Avatar({ khatazId, hasAvatar, version, name, size = 36, className = "" }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!hasAvatar || !khatazId) { setUrl(null); return; }
    let made;
    apiBlobUrl(`/api/users/${encodeURIComponent(khatazId)}/avatar?v=${version || ""}`)
      .then((u) => { made = u; setUrl(u); }).catch(() => setUrl(null));
    return () => made && URL.revokeObjectURL(made);
  }, [khatazId, hasAvatar, version]);
  const style = { width: size, height: size, fontSize: Math.max(11, Math.round(size * 0.38)) };
  return url
    ? <img src={url} alt={name || khatazId} className={`avatar avatar-img ${className}`} style={style} />
    : <span className={`avatar ${className}`} style={style} aria-hidden="true">{initials(name || khatazId || "?")}</span>;
}

/** The owner's own ID for a person (only the owner sees it). */
export function LocalId({ id }) {
  return id ? <span className="uid" title="Your ID for this person">#{id}</span> : null;
}

export function KhatazId({ id, className = "" }) {
  return id ? <span className={`kid ${className}`}>@{id}</span> : null;
}

/** Screenshots need the auth header, so they're fetched as blobs. */
export function AuthImage({ src, className, alt, onClick }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let revoke;
    apiBlobUrl(src).then((u) => { revoke = u; setUrl(u); }).catch(() => setUrl(null));
    return () => revoke && URL.revokeObjectURL(revoke);
  }, [src]);
  if (!url) return <div className={className} />;
  return <img src={url} className={className} alt={alt} onClick={() => onClick?.(url)} />;
}

export function useAsync(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    fn().then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error, loading: false }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}
