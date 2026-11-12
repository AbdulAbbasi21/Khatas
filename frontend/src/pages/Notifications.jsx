import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading, useAsync } from "../components/ui";
import { dateTime } from "../format";

export default function Notifications() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useAsync(() => Promise.all([api("/api/notifications"), api("/api/invites")]), []);
  const [actionError, setActionError] = useState(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const [items, invites] = data;

  async function answer(inv, accept) {
    setActionError(null);
    try {
      const r = await api(`/api/invites/${inv.id}/${accept ? "accept" : "decline"}`, { method: "POST" });
      if (accept && r.relationship_ids?.length) navigate(`/records/${r.relationship_ids[0]}`);
      else reload();
    } catch (err) { setActionError(err); }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Notifications</h1></div>
        {items.some((n) => !n.read) && <button className="btn btn-outline" onClick={() => api("/api/notifications/read-all", { method: "POST" }).then(reload)}>Mark all as read</button>}
      </div>
      <ErrorBox error={actionError} />

      {invites.length > 0 && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-head"><h2>Invites</h2></div>
          <ul className="list">
            {invites.map((i) => (
              <li className="list-item" key={i.id}>
                <div>
                  <div className="name">{i.business_name} wants to share a record with you</div>
                  <div className="small muted">{i.invited_by} · as “{i.contact_name}”</div>
                </div>
                <div className="row">
                  <button className="btn btn-outline btn-sm" onClick={() => answer(i, false)}>Decline</button>
                  <button className="btn btn-primary btn-sm" onClick={() => answer(i, true)}>It's me, accept</button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <ul className="list">
          {items.length === 0 && <li className="empty">No notifications yet.</li>}
          {items.map((n) => {
            const inner = (
              <>
                <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                  {!n.read && <span className="dot blue" style={{ marginTop: 7, flex: "none" }} />}
                  <div><div style={{ fontWeight: n.read ? 400 : 600 }}>{n.message}</div>
                    <div className="small muted">{dateTime(n.created_at, user.timezone)}</div></div>
                </div>
                {n.relationship_id && <span className="small">Open →</span>}
              </>
            );
            return <li key={n.id}>{n.relationship_id
              ? <Link className="list-item" to={`/records/${n.relationship_id}`}>{inner}</Link>
              : <div className="list-item">{inner}</div>}</li>;
          })}
        </ul>
      </div>
    </>
  );
}
