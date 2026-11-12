import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { AddPersonModal } from "../components/Forms";
import { Avatar, Balance, ErrorBox, KhatazId, Loading, LocalId, useAsync } from "../components/ui";

export default function Search() {
  const [params] = useSearchParams();
  const q = (params.get("q") || "").trim();
  const navigate = useNavigate();
  const { data, error, loading } = useAsync(
    () => (q.length >= 2 ? Promise.all([api(`/api/search?q=${encodeURIComponent(q)}`), api("/api/businesses")]) : Promise.resolve(null)),
    [q]);
  const [adding, setAdding] = useState(null);

  if (q.length < 2) {
    return <div className="card card-pad empty">Type at least 2 letters in the search box above: a person's name or their @Khataz ID.</div>;
  }
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const [r, businesses] = data;

  return (
    <>
      <div className="page-head">
        <div><h1>Search</h1></div>
      </div>

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card">
          <div className="card-head"><h2>In your records</h2>
            <span className="badge badge-grey">{r.records.length}</span></div>
          <ul className="list">
            {r.records.length === 0 && <li className="empty small">No one in your records matches.</li>}
            {r.records.map((s) => (
              <li key={s.id}>
                <Link className="list-item" to={`/records/${s.id}`}>
                  <div className="row" style={{ flexWrap: "nowrap" }}>
                    <Avatar khatazId={s.other_khataz_id} hasAvatar={s.other_has_avatar} version={s.other_avatar_version} name={s.other_party} />
                    <div>
                      <div className="name">{s.other_party} <LocalId id={s.local_id} /> <KhatazId id={s.other_khataz_id} /></div>
                      <div className="small muted">{s.business_name} · {s.perspective === "owed_to_me" ? "owes you" : "you owe"}</div>
                    </div>
                  </div>
                  <Balance amount={s.balance} currency={s.currency} perspective={s.perspective} />
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <div className="card-head"><h2>On Khataz</h2>
            <span className="badge badge-grey">{r.people.length}</span></div>
          <ul className="list">
            {r.people.length === 0 && (
              <li className="empty small">{q.replace(/^@/, "").length < 3 ? "Type at least 3 characters of a Khataz ID." : "No Khataz ID starts with that. Ask them for their exact ID."}</li>
            )}
            {r.people.map((p) => (
              <li className="list-item" key={p.khataz_id}>
                <div className="row" style={{ flexWrap: "nowrap" }}>
                  <Avatar khatazId={p.khataz_id} hasAvatar={p.has_avatar} version={p.avatar_version} name={p.name} size={44} />
                  <div><div className="name">{p.name}</div><KhatazId id={p.khataz_id} /></div>
                </div>
                {p.record_ids.length > 0
                  ? <Link className="btn btn-outline btn-sm" to={`/records/${p.record_ids[0]}`}>Open record</Link>
                  : businesses.length > 0
                    ? <button className="btn btn-primary btn-sm" onClick={() => setAdding(p)}>+ Add to my records</button>
                    : <Link className="btn btn-outline btn-sm" to="/">Create a business first</Link>}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {adding && (
        <AddPersonModal businesses={businesses} initial={{ name: adding.name, khataz_id: adding.khataz_id }}
                        onClose={() => setAdding(null)} onCreated={(rel) => navigate(`/records/${rel.id}`)} />
      )}
    </>
  );
}
