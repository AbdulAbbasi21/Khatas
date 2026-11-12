import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { setOpenBusiness } from "../openBusiness";
import { useAuth } from "../auth";
import ClaimCard from "../components/ClaimCard";
import ClaimFlowModal from "../components/ClaimFlow";
import { Avatar, Balance, ErrorBox, Field, KhatazId, Loading, LocalId, Modal, balanceSentence, owesPhrase, useAsync } from "../components/ui";
import { ENTRY_TYPE, dateOnly, dateTime, money, timeLeft } from "../format";

const cents = (v) => Math.round(Number(String(v).replace(/,/g, "")) * 100);
const fromCents = (c) => (c / 100).toFixed(2);

/**
 * One form, three jobs, worded from the viewer's side:
 *  add      -> credit  (the debt grows: goods taken / money borrowed)
 *  subtract -> payment (paid in cash/bank) or goods (paid with goods/services)
 *  update   -> adjustment: type the correct balance, we record the difference
 */
function MoneyModal({ rel, mode, onClose, onDone }) {
  const s = rel.summary;
  const other = s.other_party;
  const owner = s.role === "owner";
  const owed = s.perspective === "owed_to_me";
  const [method, setMethod] = useState("");
  const [amount, setAmount] = useState("");
  const [target, setTarget] = useState(fromCents(cents(s.balance)));
  const [description, setDescription] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const owesLine = owesPhrase(s.perspective, other, cents(s.balance));
  const diff = mode === "update" ? cents(target || 0) - cents(s.balance) : 0;
  const text = {
    add: {
      title: "Add money",
      placeholder: owed ? "e.g. Milk, 50 litres" : "e.g. Packaging, 200 boxes",
      button: "Add money",
    },
    subtract: {
      title: "Subtract money",
      placeholder: "e.g. Part payment for October",
      button: "Subtract money",
    },
    update: {
      title: "Update money",
      placeholder: "Why? e.g. Typed 500 instead of 50",
      button: "Update balance",
    },
  }[mode];

  async function submit(e) {
    e.preventDefault();
    setError(null);
    let body;
    if (mode === "update") {
      if (!Number.isFinite(diff) || isNaN(diff)) return setError(new Error("Enter the correct balance as a number"));
      if (diff === 0) return setError(new Error("That's already the balance; nothing to change"));
      if (!description.trim()) return setError(new Error("Say why you're correcting it"));
      body = { type: "adjustment", amount: fromCents(Math.abs(diff)), increase: diff > 0, description: description.trim() };
    } else {
      if (!(cents(amount) > 0)) return setError(new Error("Enter an amount greater than zero"));
      // subtract: the payment method is saved with the entry, e.g. "Cash · Part payment"
      const note = mode === "subtract" ? [method.trim(), description.trim()].filter(Boolean).join(" · ") : description.trim();
      body = { type: mode === "add" ? "credit" : "payment", amount: fromCents(cents(amount)), description: note || null };
    }
    setBusy(true);
    try { await api(`/api/relationships/${s.id}/entries`, { method: "POST", body }); onDone(); }
    catch (err) { setError(err); setBusy(false); }
  }

  const after = mode === "update" ? cents(target || 0)
              : cents(s.balance) + (mode === "add" ? 1 : -1) * (cents(amount) || 0);

  return (
    <Modal title={text.title} onClose={onClose}
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className={`btn ${mode === "subtract" ? "btn-dark" : "btn-primary"}`} form="money-form" disabled={busy}>
                       {owner ? text.button : `Send to ${other} to confirm`}</button></>}>
      <form id="money-form" onSubmit={submit}>
        <ErrorBox error={error} />

        {mode === "update" ? (
          <div className="field-row">
            <Field label="Balance now"><input readOnly value={`${fromCents(cents(s.balance))} ${s.currency}`} /></Field>
            <Field label={`Correct balance (${s.currency})`} hint={`${owesLine}. Use a minus for the other way round.`}>
              <input autoFocus inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} />
            </Field>
          </div>
        ) : (
          <Field label={`Amount (${s.currency})`}>
            <input required autoFocus inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
          </Field>
        )}

        {mode === "subtract" && (
          <Field label="Payment method">
            <input value={method} onChange={(e) => setMethod(e.target.value)} placeholder="e.g. Cash, Bank transfer, JazzCash, Goods" />
          </Field>
        )}

        <Field label={mode === "update" ? "Reason" : mode === "subtract" ? "Note (optional)" : "What for? (optional)"}>
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder={text.placeholder} />
        </Field>

        {!isNaN(after) && (mode === "update" ? diff !== 0 : cents(amount) > 0) && (
          <div className="money-preview">
            <span>{owesLine} <s className="muted">{fromCents(Math.abs(cents(s.balance)))}</s></span>
            <span>→ <b>{owesPhrase(s.perspective, other, after)}{after !== 0 && ` ${fromCents(Math.abs(after))} ${s.currency}`}</b></span>
          </div>
        )}
      </form>
    </Modal>
  );
}

function ReasonModal({ title, label, confirm, danger, onClose, onSubmit }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  return (
    <Modal title={title} onClose={onClose}
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className={`btn ${danger ? "btn-danger" : "btn-primary"}`} disabled={!reason.trim()}
                             onClick={() => onSubmit(reason).catch(setError)}>{confirm}</button></>}>
      <ErrorBox error={error} />
      <Field label={label}><textarea autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
    </Modal>
  );
}

/** The owner's own ID for this person: change it. */
function LocalIdModal({ rel, onClose, onDone }) {
  const [value, setValue] = useState(rel.contact?.local_id || "");
  const [error, setError] = useState(null);
  async function save(e) {
    e.preventDefault();
    try {
      await api(`/api/contacts/${rel.contact.id}/local-id`, { method: "PUT", body: { local_id: value.trim().replace(/^#/, "") } });
      onDone();
    } catch (err) { setError(err); }
  }
  return (
    <Modal title={rel.contact?.local_id ? "Change your ID" : "Add your ID"} onClose={onClose}
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className="btn btn-primary" form="lid-form" disabled={!value.trim()}>Save</button></>}>
      <form id="lid-form" onSubmit={save}>
        <ErrorBox error={error} />
        <Field label={`Your ID for ${rel.summary.contact_name}`} hint={`Unique in ${rel.summary.business_name}. Only you see it. 1–30 letters, numbers, - _ or .`}>
          <div className="prefix-input"><span>#</span><input autoFocus value={value} onChange={(e) => setValue(e.target.value)} placeholder="CUST-001" maxLength={30} spellCheck="false" /></div>
        </Field>
      </form>
    </Modal>
  );
}

/** Link by Khataz ID: they get the request inside Khataz. */
function AddKhatazIdModal({ rel, onClose, onDone }) {
  const [kid, setKid] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function go(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api(`/api/relationships/${rel.summary.id}/invite`, { method: "POST", body: { khataz_id: kid.trim().replace(/^@/, "") } });
      onDone();
    } catch (err) { setError(err); setBusy(false); }
  }
  return (
    <Modal title={`Add ${rel.summary.contact_name}'s Khataz ID`} onClose={onClose}
           footer={<><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                     <button className="btn btn-primary" form="kid-form" disabled={busy || !kid.trim()}>Send link request</button></>}>
      <form id="kid-form" onSubmit={go}>
        <ErrorBox error={error} />
        <Field label="Their Khataz ID" hint="They can find it on their profile page">
          <div className="prefix-input"><span>@</span><input autoFocus value={kid} onChange={(e) => setKid(e.target.value)} placeholder="their.id" autoCapitalize="off" spellCheck="false" /></div>
        </Field>
      </form>
    </Modal>
  );
}

/** Invite by email: for people not on Khataz yet. */
function EmailInviteModal({ rel, onClose, onDone }) {
  const [email, setEmail] = useState(rel.contact?.email || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);
  async function go(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { setResult(await api(`/api/relationships/${rel.summary.id}/invite`, { method: "POST", body: { email: email.trim() } })); }
    catch (err) { setError(err); }
    setBusy(false);
  }
  const copy = async () => { try { await navigator.clipboard.writeText(result.link); setCopied(true); } catch { /* copy by hand */ } };
  return (
    <Modal title={`Invite ${rel.summary.contact_name} to Khataz`} onClose={result ? onDone : onClose}
           footer={result ? <button className="btn btn-primary" onClick={onDone}>Done</button>
                          : <><button className="btn btn-outline" onClick={onClose}>Cancel</button>
                              <button className="btn btn-primary" form="email-invite" disabled={busy || !email.trim()}>{busy ? "Sending…" : "Send email invite"}</button></>}>
      <ErrorBox error={error} />
      {!result && (
        <form id="email-invite" onSubmit={go}>
          <Field label="Their email"><input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        </form>
      )}
      {result && result.email_sent && (
        <div className="alert alert-info">
          Invite email sent to <strong>{email.trim().toLowerCase()}</strong>.
          {result.account_exists ? " They already have an account, so they'll also see it in Notifications." : " Once they sign up with this email, they can accept it."}
        </div>
      )}
      {result && !result.email_sent && (
        <div className="stack">
          <div className="alert alert-warn">
            {result.email_configured ? "The email couldn't be sent right now." : "Email sending isn't set up on the server yet."} The invite is saved, so send them this link yourself (WhatsApp, SMS…):
          </div>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input readOnly value={result.link} onFocus={(e) => e.target.select()} className="mono" />
            <button className="btn btn-outline btn-sm" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function EntryRow({ e, rel, tz, onAction }) {
  const me = rel.my_user_id;
  const owner = rel.summary.role === "owner";
  const faded = (e.status !== "active" && e.status !== "pending") || e.reversed_by_entry_id;
  const pending = e.status === "pending";
  const sign = Number(e.delta) > 0 ? "+" : "−";
  const canReverse = owner && e.status === "active" && e.type !== "reversal" && !e.reversed_by_entry_id && e.source === "manual";
  const left = timeLeft(e.cancel_until);
  const canRespond = !owner && e.status === "active" && e.type !== "reversal" && e.created_by !== me
    && !e.reversed_by_entry_id && e.confirmation === "unconfirmed" && !!left;

  return (
    <tr className={faded ? "faded" : ""}>
      <td className="small">{dateOnly(e.occurred_at, tz)}</td>
      <td>
        <div>{e.description || <span className="muted">—</span>}</div>
        <div className="row small" style={{ marginTop: 4 }}>
          <span className="badge badge-outline">{ENTRY_TYPE[e.type]}</span>
          {e.source === "claim" && <span className="badge badge-blue">PayPal</span>}
          {e.status === "disputed" && <span className="badge badge-danger">Disputed</span>}
          {e.status === "voided" && <span className="badge badge-grey">Cancelled</span>}
          {pending && <span className="badge badge-solid">{owner ? "Waiting for your confirmation" : `Waiting for ${rel.summary.other_party} to confirm`}</span>}
          {e.status === "rejected" && <span className="badge badge-danger">Rejected</span>}
          {e.reversed_by_entry_id && <span className="badge badge-grey">Reversed</span>}
          {e.confirmation === "unconfirmed" && e.status === "active" && (
            <span className="badge badge-outline" title="The other side can cancel it until then">
              {owner ? "Can be cancelled" : "Check it"}{left ? ` · ${left}` : ""}</span>)}
          {e.status === "cancelled" && <span className="badge badge-danger">Cancelled by {owner ? rel.summary.other_party : "you"}</span>}
          {e.confirmation === "auto_accepted" && <span className="badge badge-blue">Final</span>}
          {e.confirmation === "accepted" && <span className="badge badge-blue">Confirmed</span>}
          {e.confirmation === "upheld" && <span className="badge badge-blue">Kept by owner</span>}
        </div>
      </td>
      <td className="num"><span className="amount" style={pending ? { opacity: 0.55 } : undefined}>{sign}{money(Math.abs(Number(e.delta)), e.currency)}</span></td>
      <td className="num">
        <div className="row" style={{ justifyContent: "flex-end" }}>
          {owner && pending && <button className="btn btn-primary btn-sm" onClick={() => onAction("confirm", e)}>Confirm</button>}
          {owner && pending && <button className="btn btn-danger btn-sm" onClick={() => onAction("reject", e)}>Reject</button>}
          {canReverse && <button className="btn btn-ghost btn-sm" onClick={() => onAction("reverse", e)}>Reverse</button>}
          {canRespond && <button className="btn btn-primary btn-sm" onClick={() => onAction("accept", e)}>Accept</button>}
          {canRespond && <button className="btn btn-danger btn-sm" onClick={() => onAction("cancel", e)}>Cancel</button>}
        </div>
      </td>
    </tr>
  );
}

function Disputes({ rel, tz, onChange }) {
  const [error, setError] = useState(null);
  const [notes, setNotes] = useState({});
  const owner = rel.summary.role === "owner";
  if (!rel.disputes.length) return <div className="empty">No disputes.</div>;
  async function resolve(d, resolution) {
    try { await api(`/api/disputes/${d.id}/resolve`, { method: "POST", body: { resolution, note: notes[d.id] || null } }); onChange(); }
    catch (err) { setError(err); }
  }
  return (
    <div>
      {error && <div style={{ padding: "12px 20px" }}><ErrorBox error={error} /></div>}
      {rel.disputes.map((d) => {
        const entry = rel.entries.find((e) => e.id === d.entry_id);
        return (
          <div className="claim" key={d.id}>
            <div className="spread">
              <div>
                <div className="row"><strong>Entry #{d.entry_id}</strong>{entry && <span className="amount">{money(entry.amount, entry.currency)}</span>}
                  <span className={`badge ${d.status === "open" ? "badge-danger" : "badge-grey"}`}>{d.status === "open" ? "Open" : d.resolution === "kept" ? "Kept" : "Cancelled"}</span></div>
                <p className="small" style={{ marginTop: 6 }}>“{d.reason}” <span className="muted">— {rel.names[d.opened_by]}, {dateTime(d.created_at, tz)}</span></p>
                {d.resolution_note && <p className="small muted">Decision: {d.resolution_note}</p>}
              </div>
            </div>
            {owner && d.status === "open" && (
              <div className="row" style={{ marginTop: 10 }}>
                <input style={{ maxWidth: 320 }} placeholder="Note for them (optional)" value={notes[d.id] || ""} onChange={(e) => setNotes({ ...notes, [d.id]: e.target.value })} />
                <button className="btn btn-outline btn-sm" onClick={() => resolve(d, "kept")}>Keep entry</button>
                <button className="btn btn-danger btn-sm" onClick={() => resolve(d, "voided")}>Cancel entry</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const ACTION_TEXT = {
  "entry.credit": "added a credit", "entry.payment": "recorded a payment", "entry.adjustment": "added a correction",
  "entry.reversed": "reversed an entry", "entry.goods": "recorded goods / services given",
  "entry.credit.proposed": "recorded a credit (to confirm)", "entry.payment.proposed": "recorded a payment (to confirm)",
  "entry.goods.proposed": "recorded goods / services given (to confirm)", "entry.adjustment.proposed": "recorded a correction (to confirm)",
  "entry.confirmed": "confirmed an entry", "entry.rejected": "rejected an entry", "entry.accepted": "accepted an entry", "entry.disputed": "disputed an entry",
  "dispute.kept": "kept a disputed entry", "dispute.voided": "cancelled a disputed entry",
  "claim.created": "submitted a PayPal payment", "claim.allocated": "confirmed a PayPal payment",
  "claim.allocated_after_review": "applied a reviewed payment", "claim.needs_review": "flagged a payment for review",
  "claim.not_received": "said a payment didn't arrive", "claim.held": "put a payment on hold",
  "claim.rejected": "rejected a payment", "claim.reversed": "reversed a payment (refund/chargeback)",
  "contact.created": "created this record", "contact.invited": "invited the contact to Khataz",
  "contact.linked": "linked their Khataz account", "contact.invite_cancelled": "withdrew the Khataz invite", "relationship.created": "opened this ledger",
};

function History({ relId, tz }) {
  const { data, error, loading } = useAsync(() => api(`/api/relationships/${relId}/audit`), [relId]);
  if (loading) return <div className="empty"><span className="spinner" /></div>;
  if (error) return <div style={{ padding: 20 }}><ErrorBox error={error} /></div>;
  return (
    <ul className="timeline">
      {data.map((a) => (
        <li key={a.id}>
          <div><strong>{a.actor || "System"}</strong> {ACTION_TEXT[a.action] || a.action}
            {a.after?.amount && <> · <span className="amount">{a.after.amount} {a.after.currency || ""}</span></>}
            {a.after?.claimed_amount && <> · <span className="amount">{a.after.claimed_amount} {a.after.claimed_currency}</span></>}</div>
          {a.reason && <div className="small">“{a.reason}”</div>}
          <div className="small muted">{dateTime(a.created_at, tz)} · {a.entity.replace("_", " ")} #{a.entity_id}</div>
        </li>
      ))}
    </ul>
  );
}

export default function Person() {
  const { id } = useParams();
  const { user } = useAuth();
  const tz = user.timezone;
  const { data: rel, error, loading, reload } = useAsync(() => api(`/api/relationships/${id}`), [id]);
  const navigate = useNavigate();
  useEffect(() => {  // the assistant changed something: show it
    window.addEventListener("khataz:changed", reload);
    return () => window.removeEventListener("khataz:changed", reload);
  }, [reload]);
  const bizId = rel?.summary?.business_id;
  useEffect(() => { setOpenBusiness(bizId); return () => setOpenBusiness(null); }, [bizId]);
  const [tab, setTab] = useState("ledger");
  const [modal, setModal] = useState(null);
  const [actionError, setActionError] = useState(null);

  if (loading && !rel) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const s = rel.summary;
  const owner = s.role === "owner";
  const iAmDebtor = s.perspective === "i_owe";
  const canClaim = s.side === "receivable" || s.linked;
  const openClaims = rel.claims.filter((c) => c.recipient_user_id === rel.my_user_id && ["pending_confirmation", "needs_review", "held"].includes(c.state)).length;
  const openDisputes = rel.disputes.filter((d) => d.status === "open").length;
  const pendingEntries = rel.entries.filter((e) => e.status === "pending").length;
  const done = () => { setModal(null); reload(); };

  async function entryAction(kind, e) {
    setActionError(null);
    if (kind === "accept" || kind === "confirm") {
      try { await api(`/api/entries/${e.id}/${kind}`, { method: "POST" }); reload(); } catch (err) { setActionError(err); }
    } else setModal({ kind, entry: e });
  }

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <Link to={owner ? `/?biz=${s.business_id}&tab=${s.direction === "owed_to_me" ? "owed" : "owe"}` : "/"} className="small">← {owner ? s.business_name : "Dashboard"}</Link>
      </div>

      <div className={`hero-card ${s.direction === "owed_to_me" ? "owed" : "owe"}`}>
        <div>
          <div className="row">
            <Avatar khatazId={s.other_khataz_id} hasAvatar={s.other_has_avatar} version={s.other_avatar_version} name={s.other_party} size={52} />
            <h1>{s.other_party}</h1>
            <KhatazId id={s.other_khataz_id} />
            {owner && <LocalId id={s.local_id} />}
            {owner && <button className="btn btn-ghost btn-sm" onClick={() => setModal({ kind: "local-id" })}>{s.local_id ? "Edit ID" : "+ Add your ID"}</button>}
            {owner ? (s.linked ? <span className="badge badge-blue">On Khataz</span> : <span className="badge badge-grey">Not on Khataz</span>)
                   : <span className="badge badge-blue">Shared record</span>}
            {s.linked && s.other_khataz_id && <Link to={`/chats?with=${encodeURIComponent(s.other_khataz_id)}`} className="btn btn-outline btn-sm">Message</Link>}
            {owner && Number(s.balance) === 0 && Number(s.disputed) === 0 && (
              <button className="btn btn-ghost btn-sm danger-text" onClick={() => setModal({ kind: "remove" })}>Remove record</button>
            )}</div>
          <p className="muted">{owner ? `${s.business_name} · ` : `Kept by ${s.business_name} · `}{s.side === "receivable" ? "Customer" : "Supplier"} · {s.currency}</p>
          {rel.contact && (rel.contact.phone || rel.contact.email) && <p className="small muted">{[rel.contact.email, rel.contact.phone].filter(Boolean).join(" · ")}</p>}
          {rel.pending_invite_email && (
            <div className="row small" style={{ marginTop: 6 }}>
              <span className="badge badge-outline">Invite sent to {rel.pending_invite_email}</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setModal({ kind: "undo-invite" })}>Undo invite</button>
            </div>
          )}
          {owner && !s.linked && !rel.pending_invite_email && (
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn btn-outline btn-sm" onClick={() => setModal({ kind: "add-kid" })}>Add Khataz ID</button>
              <button className="btn btn-outline btn-sm" onClick={() => setModal({ kind: "email-invite" })}>Invite to Khataz</button>
            </div>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="muted small" style={{ fontWeight: 700 }}>{balanceSentence(s)}</div>
          <Balance amount={s.balance} currency={s.currency} perspective={s.perspective} big />
          <div className="small muted">
            {money(rel.totals.credited, s.currency)} credited · {money(rel.totals.paid, s.currency)} paid or given
            {Number(rel.totals.disputed) !== 0 && <> · <span style={{ color: "var(--danger)" }}>{money(rel.totals.disputed, s.currency)} disputed</span></>}
            {Number(rel.totals.pending) !== 0 && <> · {money(Math.abs(Number(rel.totals.pending)), s.currency)} waiting for confirmation</>}
          </div>
        </div>
      </div>

      {(owner || s.linked) && (
        <div className="money-actions">
          <button type="button" className="money-tile tile-add" onClick={() => setModal({ kind: "money", mode: "add" })}>
            <span className="tile-icon" aria-hidden="true">+</span>
            <span><span className="tile-title">Add money</span></span>
          </button>
          <button type="button" className="money-tile tile-subtract" onClick={() => setModal({ kind: "money", mode: "subtract" })}>
            <span className="tile-icon" aria-hidden="true">−</span>
            <span><span className="tile-title">Subtract money</span></span>
          </button>
          <button type="button" className="money-tile tile-update" onClick={() => setModal({ kind: "money", mode: "update" })}>
            <span className="tile-icon" aria-hidden="true">✎</span>
            <span><span className="tile-title">Update money</span></span>
          </button>
          <button type="button" className="money-tile tile-paypal" disabled={!canClaim} title={canClaim ? undefined : `Link ${s.other_party} on Khataz first`} onClick={() => setModal({ kind: "claim" })}>
            <span className="tile-icon" aria-hidden="true">P</span>
            <span><span className="tile-title">{iAmDebtor ? "I paid by PayPal" : "PayPal payment"}</span></span>
          </button>
        </div>
      )}

      <div className="card" style={{ marginTop: 20 }}>
        <div className="tabs">
          <button className={tab === "ledger" ? "on" : ""} onClick={() => setTab("ledger")}>Ledger ({rel.entries.length}){owner && pendingEntries > 0 && <span className="count">{pendingEntries}</span>}</button>
          <button className={tab === "payments" ? "on" : ""} onClick={() => setTab("payments")}>PayPal payments{openClaims > 0 && <span className="count">{openClaims}</span>}</button>
          <button className={tab === "disputes" ? "on" : ""} onClick={() => setTab("disputes")}>Disputes{openDisputes > 0 && <span className="count">{openDisputes}</span>}</button>
          <button className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>History</button>
        </div>
        {actionError && <div style={{ padding: "12px 20px" }}><ErrorBox error={actionError} /></div>}

        {tab === "ledger" && (rel.entries.length === 0 ? <div className="empty">No entries yet.</div> : (
          <table className="table">
            <thead><tr><th>Date</th><th>Details</th><th className="num">Amount</th><th /></tr></thead>
            <tbody>{rel.entries.map((e) => <EntryRow key={e.id} e={e} rel={rel} tz={tz} onAction={entryAction} />)}</tbody>
          </table>
        ))}
        {tab === "payments" && (rel.claims.length === 0
          ? <div className="empty">No PayPal payments yet.{canClaim && " Use “" + (iAmDebtor ? "I paid by PayPal" : "Log PayPal payment") + "” to add one."}</div>
          : rel.claims.map((c) => <ClaimCard key={c.id} claim={c} rel={rel} tz={tz} onChange={reload} />))}
        {tab === "disputes" && <Disputes rel={rel} tz={tz} onChange={reload} />}
        {tab === "history" && <History relId={s.id} tz={tz} />}
      </div>

      {modal?.kind === "money" && <MoneyModal rel={rel} mode={modal.mode} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === "claim" && <ClaimFlowModal rel={rel} iAmDebtor={iAmDebtor} onClose={() => setModal(null)} onDone={() => { done(); setTab("payments"); }} />}
      {modal?.kind === "add-kid" && <AddKhatazIdModal rel={rel} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === "local-id" && <LocalIdModal rel={rel} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === "email-invite" && <EmailInviteModal rel={rel} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === "reverse" && (
        <ReasonModal title={`Reverse entry #${modal.entry.id}`} label="Why? (kept in the history)" confirm="Reverse entry" danger
                     onClose={() => setModal(null)}
                     onSubmit={async (reason) => { await api(`/api/entries/${modal.entry.id}/reverse`, { method: "POST", body: { reason } }); done(); }} />
      )}
      {modal?.kind === "remove" && (
        <Modal title={`Remove ${s.other_party}?`} onClose={() => setModal(null)}
               footer={<><button className="btn btn-outline" onClick={() => setModal(null)}>Keep record</button>
                         <button className="btn btn-danger" onClick={async () => {
                           try { await api(`/api/relationships/${rel.summary.id}/archive`, { method: "POST" }); navigate(`/?biz=${s.business_id}`); }
                           catch (err) { setModal(null); setActionError(err); reload(); }
                         }}>Remove record</button></>}>
          <p>The balance is zero. {s.other_party} will no longer appear in {s.business_name}. The history is kept.</p>
        </Modal>
      )}
      {modal?.kind === "undo-invite" && (
        <Modal title="Undo invite?" onClose={() => setModal(null)}
               footer={<><button className="btn btn-outline" onClick={() => setModal(null)}>Keep invite</button>
                         <button className="btn btn-danger" onClick={async () => {
                           try { await api(`/api/invites/${rel.pending_invite_id}/cancel`, { method: "POST" }); done(); }
                           catch (err) { setModal(null); setActionError(err); reload(); }
                         }}>Undo invite</button></>}>
          <p>{rel.pending_invite_email} won't be able to accept it any more, and they'll be told it was withdrawn.</p>
        </Modal>
      )}
      {modal?.kind === "reject" && (
        <ReasonModal title={`Reject ${money(modal.entry.amount, modal.entry.currency)}`} label={`Tell ${s.other_party} why`} confirm="Reject entry" danger
                     onClose={() => setModal(null)}
                     onSubmit={async (reason) => { await api(`/api/entries/${modal.entry.id}/reject`, { method: "POST", body: { reason } }); done(); }} />
      )}
      {modal?.kind === "cancel" && (
        <ReasonModal title={`Cancel ${money(modal.entry.amount, modal.entry.currency)}?`} label={`Why is it wrong? ${s.other_party} will see this.`}
                     confirm="Cancel entry" danger onClose={() => setModal(null)}
                     onSubmit={async (reason) => { await api(`/api/entries/${modal.entry.id}/cancel`, { method: "POST", body: { reason } }); done(); }} />
      )}
      {modal?.kind === "dispute" && (
        <ReasonModal title={`Dispute ${money(modal.entry.amount, modal.entry.currency)}`} label="What's wrong with this entry?" confirm="Dispute entry" danger
                     onClose={() => setModal(null)}
                     onSubmit={async (reason) => { await api(`/api/entries/${modal.entry.id}/dispute`, { method: "POST", body: { reason } }); done(); }} />
      )}
    </>
  );
}

