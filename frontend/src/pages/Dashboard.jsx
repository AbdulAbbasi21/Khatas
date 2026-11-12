import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { AddBusinessModal, AddPersonModal } from "../components/Forms";
import QuickEntry from "../components/QuickEntry";
import { setOpenBusiness } from "../openBusiness";
import { Balance, ErrorBox, Loading, LocalId, useAsync } from "../components/ui";
import { initials, money } from "../format";

const TABS = {
  owe: { label: "Money I Owe", side: "payable", perspective: "i_owe", totalLabel: "You owe", active: "btn-dark" },
  owed: { label: "Money Owed to Me", side: "receivable", perspective: "owed_to_me", totalLabel: "Owed to you", active: "btn-primary" },
};

function Totals({ totals }) {
  const entries = Object.entries(totals);
  if (!entries.length) return <div className="value">0.00</div>;
  return entries.map(([cur, v]) => <div className="value" key={cur}>{money(v, cur)}</div>);
}

function groupTotals(items) {
  const t = {};
  for (const r of items) t[r.currency] = (t[r.currency] || 0) + Number(r.amount ?? Math.abs(Number(r.balance)));
  return Object.entries(t).map(([cur, v]) => money(v, cur)).join(" · ");
}

/** The API sends two lists (owed to me / I owe), each grouped by business.
 *  The dashboard shows each business once, so merge them. */
function mergeBusinesses(data) {
  const map = new Map();
  const add = (groups, key) => {
    for (const g of groups) {
      if (g.shared && g.items.length === 0) continue;
      const id = `${g.business_id}${g.shared ? "s" : ""}`;
      if (!map.has(id)) map.set(id, { id, business_id: g.business_id, business_name: g.business_name, shared: g.shared, owe: [], owed: [] });
      map.get(id)[key].push(...g.items);
    }
  };
  add(data.owed_to_me.groups, "owed");
  add(data.i_owe.groups, "owe");
  return [...map.values()].sort((a, b) => a.shared - b.shared || a.business_name.localeCompare(b.business_name));
}

/** One business = one blue bar on the dashboard. Clicking it opens BusinessScreen. */
function BusinessBar({ b, onOpen }) {
  const people = b.owe.length + b.owed.length;
  const todo = [...b.owe, ...b.owed].reduce((n, r) => n + (r.pending_actions || 0), 0);
  return (
    <button type="button" className="card biz-head biz-bar" onClick={onOpen}>
      <span className="biz-title">
        <span className="biz-name">{b.business_name}</span>
        {b.shared && <span className="badge biz-badge">Shared with you</span>}
        {todo > 0 && <span className="badge biz-badge">{todo} to do</span>}
      </span>
      <span className="biz-meta">
        <span>{people} {people === 1 ? "person" : "people"}</span>
        {b.owed.length > 0 && <span>Owed to me <span className="biz-total">{groupTotals(b.owed)}</span></span>}
        {b.owe.length > 0 && <span>I owe <span className="biz-total">{groupTotals(b.owe)}</span></span>}
        <span className="biz-arrow" aria-hidden="true">›</span>
      </span>
    </button>
  );
}

/** Full screen on top of the dashboard: one business, with Money I Owe / Money Owed to Me. */
function BusinessScreen({ b, details, myBusinesses = [], tab, onTab, onClose, onAddBusiness }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !document.querySelector(".modal-back") && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // the dashboard behind doesn't scroll
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onClose]);

  const t = TABS[tab];
  const all = b[tab];
  const q = query.trim().toLowerCase();
  const items = q ? all.filter((r) => r.other_party.toLowerCase().includes(q)) : all;

  return (
    <div className="biz-screen-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="biz-screen" role="dialog" aria-modal="true" aria-label={b.business_name}>
        <header className="biz-screen-head">
          <button type="button" className="biz-back" onClick={onClose} aria-label="Back to dashboard">‹ Dashboard</button>
          <div className="spread" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <div className="biz-screen-kicker">Business</div>
              <h1 className="biz-screen-title">{b.business_name}</h1>
              <div className="row">
                <span className="biz-screen-sub">{b.owe.length + b.owed.length} people{details ? ` · ${details.default_currency}` : ""}{details?.category ? ` · ${details.category}` : ""}</span>
                {b.shared && <span className="badge biz-badge">Shared with you</span>}
              </div>
            </div>
            {all.length > 0 && (
              <div style={{ textAlign: "right" }}>
                <div className="biz-screen-kicker">{t.totalLabel}</div>
                <div className="biz-screen-total">{groupTotals(all)}</div>
              </div>
            )}
          </div>
        </header>

        <div className="biz-screen-tabs split-tabs" role="tablist">
          {Object.entries(TABS).map(([key, tb]) => (
            <button key={key} role="tab" aria-selected={tab === key}
                    className={`btn ${tab === key ? tb.active : "btn-outline"}`}
                    onClick={() => { setQuery(""); onTab(key); }}>
              {tb.label} <span className="tab-count">{b[key].length}</span>
            </button>
          ))}
        </div>

        <div className="biz-screen-tools">
          {all.length > 4 && <input placeholder="Search people" value={query} onChange={(e) => setQuery(e.target.value)} />}
          <div className="row" style={{ marginLeft: "auto" }}>
            <button className="btn btn-primary btn-sm" disabled={!b.shared && !details}
                    onClick={() => (b.shared && myBusinesses.length === 0 ? onAddBusiness() : setAdding(true))}>+ Add person</button>
          </div>
        </div>

        <ul className="list biz-screen-list">
          {all.length === 0 && (
            <li className="empty">
              {tab === "owe" ? "You don't owe anyone in this business." : "Nobody owes this business money yet."}
              {!b.shared && " Add a person to start."}
            </li>
          )}
          {all.length > 0 && items.length === 0 && <li className="empty">No one matches “{query}”.</li>}
          {items.map((r) => (
            <li key={r.id}>
              <Link className="list-item" to={`/records/${r.id}`}>
                <div className="row" style={{ flexWrap: "nowrap" }}>
                  <span className="avatar biz-avatar">{initials(r.other_party)}</span>
                  <div>
                    <div className="name">{r.other_party} <LocalId id={r.local_id} /></div>
                    <div className="row small muted">
                      {r.linked ? <span className="badge badge-grey">On Khataz</span> : <span>Not on Khataz</span>}
                      {Number(r.disputed) !== 0 && <span className="badge badge-danger">Disputed {money(r.disputed, r.currency)}</span>}
                      {r.pending_actions > 0 && <span className="badge badge-solid">{r.pending_actions} to do</span>}
                    </div>
                  </div>
                </div>
                <Balance amount={r.balance} currency={r.currency} perspective={r.perspective} />
              </Link>
            </li>
          ))}
        </ul>
      </div>
      {adding && (details || b.shared) && (
        <AddPersonModal business={b.shared ? undefined : details} businesses={b.shared ? myBusinesses : undefined}
                        note={b.shared ? `${b.business_name} is someone else's business, so the person is saved in one of yours.` : null}
                        side={t.side} onClose={() => setAdding(false)}
                        onCreated={(rel) => navigate(`/records/${rel.id}`)} />
      )}
    </div>
  );
}

export default function Dashboard() {
  const { data: both, error, loading, reload } = useAsync(() => Promise.all([api("/api/dashboard"), api("/api/businesses")]), []);
  const [data, myBusinesses] = both || [];
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  // Which business is open and which tab, kept in the URL so the browser Back button closes it.
  const openId = params.get("biz");
  const close = useCallback(() => {
    const next = new URLSearchParams(params); next.delete("biz"); next.delete("tab"); setParams(next, { replace: true });
  }, [params, setParams]);

  // hooks must run before the early returns below, or React crashes when loading finishes
  const businesses = data ? mergeBusinesses(data) : [];
  const openBiz = businesses.find((b) => b.id === openId);
  useEffect(() => { setOpenBusiness(openBiz?.business_id); return () => setOpenBusiness(null); }, [openBiz?.business_id]);

  if (loading && !both) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const c = data.counts;
  const waiting = c.to_confirm + c.to_review + c.open_disputes + c.entries_to_accept + (c.entries_to_confirm || 0) + c.invites;

  // default tab: whichever side has people, "Money Owed to Me" first
  const defaultTab = (b) => (b.owed.length || !b.owe.length ? "owed" : "owe");
  const tab = params.get("tab") in TABS ? params.get("tab") : openBiz ? defaultTab(openBiz) : "owed";
  const open = (b) => setParams({ biz: b.id, tab: defaultTab(b) });
  const setTab = (t) => { const next = new URLSearchParams(params); next.set("tab", t); setParams(next, { replace: true }); };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Hello, {data.user.name.split(" ")[0]}</h1>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <Link to="/all-records" className="btn btn-outline">All records</Link>
          <button className="btn btn-primary" onClick={() => setAdding(true)}>+ Add business</button>
        </div>
      </div>

      <QuickEntry onSaved={reload} />

      <div className="grid-3" style={{ marginBottom: 26 }}>
        <div className="card stat navy"><div className="label">Money owed to me</div><Totals totals={data.owed_to_me.totals} /></div>
        <div className="card stat"><div className="label">Money I owe</div><Totals totals={data.i_owe.totals} /></div>
        <Link to="/review" className="card stat blue" style={{ textDecoration: "none" }}>
          <div className="label">Waiting for you</div>
          <div className="value">{waiting}</div>
          <div className="small" style={{ color: "#d3e7fb" }}>
            {c.to_confirm + (c.entries_to_confirm || 0)} to confirm · {c.to_review + c.open_disputes} to review · {c.entries_to_accept + c.invites} to accept
          </div>
        </Link>
      </div>

      {businesses.length === 0 ? (
        <div className="card card-pad" style={{ textAlign: "center", padding: 48 }}>
          <h2>Start with your first business</h2>
          <button className="btn btn-primary" onClick={() => setAdding(true)}>+ Add business</button>
        </div>
      ) : (
        <section>
          <div className="section-title"><h2>Your businesses</h2></div>
          <div className="stack">
            {businesses.map((b) => <BusinessBar key={b.id} b={b} onOpen={() => open(b)} />)}
          </div>
        </section>
      )}

      {openBiz && <BusinessScreen b={openBiz} details={openBiz.shared ? null : myBusinesses.find((x) => x.id === openBiz.business_id)}
                                  myBusinesses={myBusinesses || []}
                                  tab={tab} onTab={setTab} onClose={close}
                                  onAddBusiness={() => { close(); setAdding(true); }} />}
      {adding && <AddBusinessModal onClose={() => setAdding(false)} onCreated={(b) => { setAdding(false); reload(); setParams({ biz: String(b.id), tab: "owed" }); }} />}
    </>
  );
}
