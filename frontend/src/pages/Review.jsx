import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading, useAsync } from "../components/ui";
import { CLAIM_STATE, dateTime, money, timeLeft } from "../format";

function Group({ title, hint, items, render }) {
  return (
    <div className="card">
      <div className="card-head"><h2>{title}</h2>
        <span className={`badge ${items.length ? "badge-solid" : "badge-grey"}`}>{items.length}</span></div>
      <ul className="list">
        {items.length === 0 && <li className="empty small">Nothing waiting.</li>}
        {items.map(render)}
      </ul>
    </div>
  );
}

export default function Review() {
  const { user } = useAuth();
  const { data, error, loading } = useAsync(() => Promise.all([api("/api/review"), api("/api/invites")]), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const [r, invites] = data;
  const tz = user.timezone;

  const claimRow = ({ claim, relationship }) => (
    <li key={claim.id}>
      <Link className="list-item" to={`/records/${relationship.id}`}>
        <div>
          <div className="name">{relationship.other_party} <span className="muted small">· {relationship.business_name}</span></div>
          <div className="row small muted">
            <span className={`badge ${CLAIM_STATE[claim.state]?.cls}`}>{CLAIM_STATE[claim.state]?.label}</span>
            {claim.sender_txn_id && <span className="mono">{claim.sender_txn_id}</span>}
            <span>{dateTime(claim.created_at, tz)}</span>
          </div>
          {claim.review_reason_text.length > 0 && <div className="small" style={{ marginTop: 4 }}>{claim.review_reason_text.join(" · ")}</div>}
        </div>
        <span className="amount">{money(claim.claimed_amount, claim.claimed_currency)}</span>
      </Link>
    </li>
  );

  return (
    <>
      <div className="page-head"><div><h1>Review</h1></div></div>
      <div className="grid-2">
        <div className="stack">
          <Group title="Payments to confirm" hint="Someone says they paid you. Check your PayPal." items={r.to_confirm} render={claimRow} />
          <Group title="Payments to review" hint="Received, but something didn't match." items={r.to_review} render={claimRow} />
          <Group title="Disputes on your entries" hint="The other side disagrees with an entry." items={r.disputes} render={(d) => (
            <li key={d.id}><Link className="list-item" to={`/records/${d.relationship.id}`}>
              <div><div className="name">{d.relationship.other_party} <span className="muted small">· {d.relationship.business_name}</span></div>
                <div className="small">“{d.reason}”</div></div>
              <span className="badge badge-danger">Entry #{d.entry_id}</span>
            </Link></li>
          )} />
        </div>
        <div className="stack">
          <Group title="Entries to confirm" hint="The other side recorded something. It counts only after you confirm." items={r.entries_to_confirm} render={(e) => (
            <li key={e.id}><Link className="list-item" to={`/records/${e.relationship.id}`}>
              <div><div className="name">{e.relationship.other_party} <span className="muted small">· {e.relationship.business_name}</span></div>
                <div className="small muted">{e.type === "goods" ? "Goods / services given" : e.type} · {e.description || "no description"}</div></div>
              <span className="amount">{money(e.amount, e.currency)}</span>
            </Link></li>
          )} />
          <Group title="Entries to check" hint="Records others added about you." items={r.entries_to_accept} render={(e) => (
            <li key={e.id}><Link className="list-item" to={`/records/${e.relationship.id}`}>
              <div><div className="name">{e.relationship.business_name}</div><div className="small muted">{e.type} · {e.description || "no description"}{timeLeft(e.cancel_until) ? ` · cancel within ${timeLeft(e.cancel_until).replace(" left", "")}` : ""}</div></div>
              <span className="amount">{money(e.amount, e.currency)}</span>
            </Link></li>
          )} />
          <Group title="Invites" hint="Businesses asking you to share a record." items={invites} render={(i) => (
            <li key={i.id}><Link className="list-item" to="/notifications">
              <div><div className="name">{i.business_name}</div><div className="small muted">from {i.invited_by}, as “{i.contact_name}”</div></div>
              <span className="btn btn-primary btn-sm">Answer</span>
            </Link></li>
          )} />
          <Group title="Your payments waiting" hint="Payments you sent that the other side hasn't confirmed." items={r.my_pending_claims} render={claimRow} />
        </div>
      </div>
    </>
  );
}
