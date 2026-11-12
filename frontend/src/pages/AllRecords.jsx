import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Loading, useAsync } from "../components/ui";
import { money } from "../format";

ModuleRegistry.registerModules([AllCommunityModule]);

// AG Grid in Khataz colours (navy / PayPal blue / white)
const theme = themeQuartz.withParams({
  accentColor: "#0070e0",
  foregroundColor: "#111827",
  headerBackgroundColor: "#f5f7fb",
  headerTextColor: "#003087",
  headerFontWeight: 700,
  borderColor: "#e3e8ef",
  rowHoverColor: "#eef6ff",
  fontFamily: "inherit",
  fontSize: 15,
  rowHeight: 52,
  headerHeight: 46,
  wrapperBorderRadius: 12,
  browserColorScheme: "light",
});

const SIDES = { all: "Everyone", owed_to_me: "Owe me", i_owe: "I owe" };

/** Every record from the dashboard's two sections, one row per person. */
function flatten(data) {
  const rows = [];
  for (const key of ["owed_to_me", "i_owe"]) {
    for (const g of data[key].groups) {
      for (const r of g.items) {
        rows.push({ ...r, business_id: g.business_id, business_name: g.business_name, shared: !!g.shared,
                    now: Number(r.balance) === 0 ? "settled" : key, value: Number(r.amount ?? Math.abs(Number(r.balance))) });
      }
    }
  }
  return rows;
}

function NameCell({ data }) {
  const initials = data.other_party.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <span className="grid-name">
      <span className="avatar biz-avatar">{initials}</span>
      <span className="grid-name-text">{data.other_party}</span>
    </span>
  );
}

function SideCell({ data }) {
  if (data.now === "settled") return <span className="badge badge-grey">Settled</span>;
  return data.now === "owed_to_me"
    ? <span className="badge badge-blue">Owes me</span>
    : <span className="badge badge-solid">I owe</span>;
}

function StatusCell({ data }) {
  return (
    <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
      {data.pending_actions > 0 && <span className="badge badge-solid">{data.pending_actions} to do</span>}
      {Number(data.disputed) !== 0 && <span className="badge badge-danger">Disputed {money(data.disputed, data.currency)}</span>}
      {data.shared && <span className="badge badge-outline">Shared with you</span>}
    </span>
  );
}

export default function AllRecords() {
  const { data, error, loading } = useAsync(() => api("/api/dashboard"), []);
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const grid = useRef(null);
  const navigate = useNavigate();
  const biz = params.get("biz") || "all";
  const side = params.get("side") || "all";
  const setFilter = (k, v) => { const p = new URLSearchParams(params); v === "all" ? p.delete(k) : p.set(k, v); setParams(p, { replace: true }); };

  const all = useMemo(() => (data ? flatten(data) : []), [data]);
  const businesses = useMemo(() => {
    const m = new Map();
    for (const r of all) m.set(String(r.business_id), { id: String(r.business_id), name: r.business_name, count: (m.get(String(r.business_id))?.count || 0) + 1 });
    return [...m.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [all]);
  const rows = all.filter((r) => (biz === "all" || String(r.business_id) === biz)
                                 && (side === "all" || r.now === side));

  const totals = useMemo(() => {
    const t = { owed_to_me: {}, i_owe: {} };
    for (const r of rows) if (r.now !== "settled") t[r.now][r.currency] = (t[r.now][r.currency] || 0) + r.value;
    const fmt = (o) => Object.entries(o).map(([c, v]) => money(v, c)).join(" + ") || "—";
    return { owed: fmt(t.owed_to_me), owe: fmt(t.i_owe) };
  }, [rows]);

  const columns = useMemo(() => [
    { headerName: "Name", field: "other_party", flex: 2, minWidth: 230, cellRenderer: NameCell, tooltipField: "other_party", pinned: "left" },
    { headerName: "Business", field: "business_name", flex: 1, minWidth: 150 },
    { headerName: "Your ID", field: "local_id", width: 115, cellClass: "mono", valueFormatter: (p) => p.value || "—" },
    { headerName: "Khataz ID", field: "other_khataz_id", width: 140, valueFormatter: (p) => (p.value ? `@${p.value}` : "—"),
      getQuickFilterText: (p) => (p.value ? `@${p.value} ${p.value}` : "") },
    { headerName: "Now", field: "now", width: 115, cellRenderer: SideCell, getQuickFilterText: () => "" },
    { headerName: "Balance", field: "value", width: 150, type: "rightAligned", sort: "desc", cellClass: "grid-amount",
      valueFormatter: (p) => money(p.value, p.data.currency), getQuickFilterText: () => "" },
    { headerName: "Currency", field: "currency", width: 105 },
    { headerName: "Status", colId: "status", minWidth: 170, flex: 1, sortable: false, cellRenderer: StatusCell,
      getQuickFilterText: () => "" },
  ], []);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;

  const exportCsv = () => grid.current?.api.exportDataAsCsv({
    fileName: `khataz-records-${new Date().toISOString().slice(0, 10)}.csv`,
    columnKeys: ["other_party", "business_name", "local_id", "other_khataz_id", "now", "value", "currency"],
    processCellCallback: (p) => {
      const id = p.column.getColId();
      if (id === "value") return p.value.toFixed(2);
      if (id === "now") return { owed_to_me: "Owes me", i_owe: "I owe", settled: "Settled" }[p.value];
      return p.value ?? "";
    },
  });

  return (
    <>
      <div style={{ marginBottom: 14 }}><Link to="/" className="small">← Dashboard</Link></div>
      <div className="page-head">
        <div><h1>All records</h1></div>
        <div className="row records-totals">
          <span><span className="small muted">Owed to me</span> <strong className="pos">{totals.owed}</strong></span>
          <span><span className="small muted">I owe</span> <strong>{totals.owe}</strong></span>
        </div>
      </div>

      <div className="records-filters">
        <div className="chip-row" role="tablist" aria-label="Business">
          <button className={`chip ${biz === "all" ? "on" : ""}`} onClick={() => setFilter("biz", "all")}>All businesses <span>{all.length}</span></button>
          {businesses.map((b) => (
            <button key={b.id} className={`chip ${biz === b.id ? "on" : ""}`} onClick={() => setFilter("biz", b.id)}>{b.name} <span>{b.count}</span></button>
          ))}
        </div>
        <div className="row" style={{ gap: 10 }}>
          <div className="segmented">
            {Object.entries(SIDES).map(([k, label]) => (
              <button key={k} type="button" className={side === k ? "on" : ""} onClick={() => setFilter("side", k)}>{label}</button>
            ))}
          </div>
          <input className="records-search" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="Search name, your ID or @Khataz ID" aria-label="Search records" />
          <button type="button" className="btn btn-outline btn-sm" onClick={exportCsv} disabled={!rows.length}>Export CSV</button>
        </div>
      </div>

      {all.length === 0 ? (
        <div className="card card-pad empty">No records yet. Add a business and a person on the dashboard.</div>
      ) : (
        <div className="records-grid">
          <AgGridReact
            ref={grid}
            theme={theme}
            rowData={rows}
            columnDefs={columns}
            defaultColDef={{ sortable: true, resizable: true, suppressMovable: true }}
            getRowId={(p) => String(p.data.id)}
            quickFilterText={query}
            domLayout="autoHeight"
            rowClass="grid-row-link"
            onRowClicked={(e) => navigate(`/records/${e.data.id}`)}
            overlayNoRowsTemplate={'<span class="muted">No records match.</span>'}
            suppressCellFocus
          />
        </div>
      )}
    </>
  );
}
