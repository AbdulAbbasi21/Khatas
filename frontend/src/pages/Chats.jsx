import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { dateTime } from "../format";
import { Avatar, ErrorBox, KhatazId } from "../components/ui";

const LIST_EVERY = 8000, THREAD_EVERY = 3000;

function shortTime(iso, tz) {
  const d = new Date(iso);
  const opts = { timeZone: tz || undefined };
  const today = new Date().toLocaleDateString("en-CA", opts) === d.toLocaleDateString("en-CA", opts);
  return today ? d.toLocaleTimeString([], { ...opts, hour: "numeric", minute: "2-digit" })
               : d.toLocaleDateString([], { ...opts, day: "numeric", month: "short" });
}

function NewChat({ onOpen }) {
  const [kid, setKid] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function start(e) {
    e.preventDefault(); setError(null); setBusy(true);
    try { onOpen(await api("/api/chats", { method: "POST", body: { khataz_id: kid.trim() } })); setKid(""); }
    catch (err) { setError(err); }
    setBusy(false);
  }
  return (
    <form className="new-chat" onSubmit={start}>
      <input value={kid} onChange={(e) => setKid(e.target.value)} placeholder="@Khataz ID" aria-label="Khataz ID to chat with" />
      <button className="btn btn-primary btn-sm" disabled={busy || !kid.trim()}>Chat</button>
      {error && <div className="new-chat-error"><ErrorBox error={error} /></div>}
    </form>
  );
}

function Thread({ chatId, tz, onSeen }) {
  const [chat, setChat] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [readUpTo, setReadUpTo] = useState(0);
  const [text, setText] = useState("");
  const [error, setError] = useState(null);
  const [sending, setSending] = useState(false);
  const lastId = useRef(0);
  const end = useRef();

  useEffect(() => {
    let alive = true;
    lastId.current = 0; setMsgs([]); setChat(null); setError(null);
    async function poll() {
      try {
        const r = await api(`/api/chats/${chatId}/messages?after_id=${lastId.current}`);
        if (!alive) return;
        setChat(r.chat); setReadUpTo(r.read_up_to);
        if (r.messages.length) {
          lastId.current = r.messages[r.messages.length - 1].id;
          setMsgs((m) => [...m.filter((x) => !r.messages.some((n) => n.id === x.id)), ...r.messages]);
          onSeen?.();
          window.dispatchEvent(new Event("khataz:chat-read"));
        }
      } catch (err) { if (alive) setError(err); }
    }
    poll();
    const t = setInterval(poll, THREAD_EVERY);
    return () => { alive = false; clearInterval(t); };
  }, [chatId]);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length]);

  async function send(e) {
    e.preventDefault();
    const body = text.trim();
    if (!body || sending) return;
    setSending(true); setError(null);
    try {
      const m = await api(`/api/chats/${chatId}/messages`, { method: "POST", body: { body } });
      setText("");
      setMsgs((x) => (x.some((y) => y.id === m.id) ? x : [...x, m]));
      lastId.current = Math.max(lastId.current, m.id);
      onSeen?.();
    } catch (err) { setError(err); }
    setSending(false);
  }

  if (!chat) return <div className="thread"><div className="thread-empty">{error ? <ErrorBox error={error} /> : <span className="spinner" />}</div></div>;
  const lastMine = [...msgs].reverse().find((m) => m.mine);
  return (
    <div className="thread">
      <div className="thread-head">
        <Link to="/chats" className="thread-back" aria-label="All chats">←</Link>
        <Avatar khatazId={chat.with.khataz_id} hasAvatar={chat.with.has_avatar} name={chat.with.name} size={40} />
        <div><strong>{chat.with.name}</strong><div><KhatazId id={chat.with.khataz_id} /></div></div>
      </div>
      <div className="thread-body">
        {msgs.length === 0 && <div className="thread-empty muted">Say hello to {chat.with.name.split(" ")[0]}.</div>}
        {msgs.map((m) => (
          <div key={m.id} className={`msg ${m.mine ? "mine" : "theirs"}`} title={dateTime(m.created_at, tz)}>
            <div className="msg-body">{m.body}</div>
            <div className="msg-time">{shortTime(m.created_at, tz)}{m.mine && lastMine?.id === m.id && (readUpTo >= m.id ? " · Seen" : "")}</div>
          </div>
        ))}
        <div ref={end} />
      </div>
      <ErrorBox error={error} />
      <form className="thread-input" onSubmit={send}>
        <textarea rows={1} value={text} maxLength={2000} placeholder="Message"
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(e); } }} />
        <button className="btn btn-primary" disabled={sending || !text.trim()}>Send</button>
      </form>
    </div>
  );
}

export default function Chats() {
  const { user } = useAuth();
  const { id } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [chats, setChats] = useState(null);
  const [error, setError] = useState(null);

  const load = () => api("/api/chats").then(setChats).catch(setError);
  useEffect(() => { load(); const t = setInterval(load, LIST_EVERY); return () => clearInterval(t); }, []);

  // /chats?with=marwan opens (or starts) the chat with that Khataz ID
  useEffect(() => {
    const kid = params.get("with");
    if (!kid) return;
    api("/api/chats", { method: "POST", body: { khataz_id: kid } })
      .then((c) => { load(); navigate(`/chats/${c.id}`, { replace: true }); })
      .catch(setError);
  }, [params]);

  const open = (c) => { load(); navigate(`/chats/${c.id}`); };

  return (
    <div className={`chats ${id ? "has-thread" : ""}`}>
      <aside className="chat-list card">
        <div className="chat-list-head"><h2>Chats</h2></div>
        <NewChat onOpen={open} />
        <ErrorBox error={error} />
        <div className="chat-items">
          {chats?.length === 0 && <div className="muted small" style={{ padding: 16 }}>No chats yet.</div>}
          {chats?.map((c) => (
            <Link key={c.id} to={`/chats/${c.id}`} className={`chat-item ${String(c.id) === id ? "on" : ""}`}>
              <Avatar khatazId={c.with.khataz_id} hasAvatar={c.with.has_avatar} name={c.with.name} size={42} />
              <div className="chat-item-main">
                <div className="chat-item-top"><strong>{c.with.name}</strong>{c.last && <span className="small muted">{shortTime(c.last.created_at, user.timezone)}</span>}</div>
                <div className="chat-item-last">
                  <span className="small muted">{c.last ? `${c.last.mine ? "You: " : ""}${c.last.body}` : `@${c.with.khataz_id}`}</span>
                  {c.unread > 0 && <span className="count">{c.unread}</span>}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </aside>
      <section className="chat-main card">
        {id ? <Thread key={id} chatId={id} tz={user.timezone} onSeen={load} />
            : <div className="thread-empty muted">Choose a chat, or start one with a Khataz ID.</div>}
      </section>
    </div>
  );
}
