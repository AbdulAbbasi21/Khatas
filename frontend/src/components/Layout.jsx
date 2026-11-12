import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { PayPalLiveChip } from "./PayPalLive";
import Assistant from "./Assistant";
import { useAuth } from "../auth";
import { Avatar, Logo } from "./ui";

function HeaderSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [q, setQ] = useState("");
  useEffect(() => { if (location.pathname === "/search") setQ(params.get("q") || ""); }, [location.pathname, params]);
  return (
    <form className="top-search" role="search"
          onSubmit={(e) => { e.preventDefault(); if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`); }}>
      <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, #your ID or @Khataz ID" aria-label="Search people" />
    </form>
  );
}

/** Profile picture button -> a small menu: Profile, Log out. */
function ProfileMenu({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const box = useRef();
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);       // close after navigating
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div className="profile-menu" ref={box}>
      <button type="button" className="profile-btn" aria-haspopup="menu" aria-expanded={open}
              aria-label="Account menu" title={`@${user.khataz_id}`} onClick={() => setOpen((o) => !o)}>
        <Avatar khatazId={user.khataz_id} hasAvatar={user.has_avatar} version={user.avatar_version} name={user.name} size={36} />
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <div className="name">{user.name}</div>
            <div className="kid">@{user.khataz_id}</div>
          </div>
          <Link role="menuitem" className="menu-item" to="/profile">Profile</Link>
          <button role="menuitem" type="button" className="menu-item menu-danger" onClick={onLogout}>Log out</button>
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { user, signOut } = useAuth();
  const [counts, setCounts] = useState(null);
  const location = useLocation();

  useEffect(() => {
    const load = () => api("/api/dashboard").then((d) => setCounts(d.counts)).catch(() => {});
    load();
    const timer = setInterval(load, 30000); // pick up the other side's actions
    window.addEventListener("khataz:changed", load);
    return () => { clearInterval(timer); window.removeEventListener("khataz:changed", load); };
  }, [location.pathname]);

  const [chatUnread, setChatUnread] = useState(0);
  useEffect(() => {
    const load = () => api("/api/chats/unread").then((r) => setChatUnread(r.unread)).catch(() => {});
    load();
    const timer = setInterval(load, 8000);
    window.addEventListener("khataz:chat-read", load);
    return () => { clearInterval(timer); window.removeEventListener("khataz:chat-read", load); };
  }, [location.pathname]);

  const waiting = counts
    ? counts.to_confirm + counts.to_review + counts.open_disputes + counts.entries_to_accept + (counts.entries_to_confirm || 0) + counts.invites
    : 0;

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" aria-label="Khataz home"><Logo /></Link>
          <nav className="nav">
            <NavLink to="/" end>Dashboard</NavLink>
            <NavLink to="/review">Review{waiting > 0 && <span className="count">{waiting}</span>}</NavLink>
            <NavLink to="/chats">Chats{chatUnread > 0 && <span className="count">{chatUnread}</span>}</NavLink>
            <NavLink to="/notifications">Notifications{counts?.unread > 0 && <span className="count">{counts.unread}</span>}</NavLink>
          </nav>
          <PayPalLiveChip />
          <HeaderSearch />
          <div className="user-menu">
            <ProfileMenu user={user} onLogout={signOut} />
          </div>
        </div>
      </header>
      <main className="page"><Outlet /></main>
      {!location.pathname.startsWith("/chats") && <Assistant />}
      <nav className="bottom-nav" aria-label="Main">
        <NavLink to="/" end><span aria-hidden="true">⌂</span>Home</NavLink>
        <NavLink to="/review"><span aria-hidden="true">✓</span>Review{waiting > 0 && <span className="count">{waiting}</span>}</NavLink>
        <NavLink to="/chats"><span aria-hidden="true">✉</span>Chats{chatUnread > 0 && <span className="count">{chatUnread}</span>}</NavLink>
        <NavLink to="/notifications"><span aria-hidden="true">●</span>Alerts{counts?.unread > 0 && <span className="count">{counts.unread}</span>}</NavLink>
        <NavLink to="/profile"><span aria-hidden="true">☺</span>Profile</NavLink>
      </nav>
    </>
  );
}
