import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { getOpenBusiness } from "../openBusiness";
import { money } from "../format";
import { CheckEntry } from "./QuickEntry";

const HELLO = "Hi! Ask me how to use Khataz, or tell me what to do: “Marwan took 5 kg milk for $20”, “set Marwan's balance to 80”, “undo Marwan's last entry”. Tap 🎤 to speak.";
const SR = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

function speak(text) {
  try {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  } catch { /* speaking is optional */ }
}

const cents = (v) => Math.round(Number(v) * 100);

function ActionCard({ action, onDone, onCancel }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [state, setState] = useState(null); // done | cancelled
  async function run() {
    setBusy(true); setError(null);
    try {
      if (action.kind === "update_balance") {
        const diff = cents(action.to) - cents(action.balance);
        await api(`/api/relationships/${action.relationship_id}/entries`, {
          method: "POST", body: { type: "adjustment", amount: (Math.abs(diff) / 100).toFixed(2), increase: diff > 0, description: action.reason },
        });
      } else if (action.kind === "undo_entry") {
        await api(`/api/entries/${action.entry.id}/reverse`, { method: "POST", body: { reason: action.reason } });
      } else if (action.kind === "remove_record") {
        await api(`/api/relationships/${action.relationship_id}/archive`, { method: "POST" });
      }
      setState("done"); onDone(action);
    } catch (err) { setError(err.message); }
    setBusy(false);
  }
  const title = { update_balance: "Update money", undo_entry: "Undo entry", remove_record: "Remove record" }[action.kind];
  return (
    <div className="draft-card">
      <div className="draft-line"><span>{title}</span><strong>{action.name}</strong></div>
      {action.kind === "update_balance" && <div className="small">{money(action.balance, action.currency)} → <strong>{money(action.to, action.currency)}</strong></div>}
      {action.kind === "undo_entry" && <div className="small">{action.entry.label} {money(action.entry.amount, action.currency)}{action.entry.description ? ` · ${action.entry.description}` : ""}</div>}
      {action.kind === "remove_record" && <div className="small muted">{action.business_name} · balance {money(action.balance, action.currency)}</div>}
      {error && <div className="small" style={{ color: "var(--danger)" }}>{error}</div>}
      {state === "done" ? <div className="small"><strong>Done ✓</strong></div>
        : state === "cancelled" ? <div className="small muted">Cancelled</div>
        : <div className="row" style={{ gap: 8 }}>
            <button className={`btn btn-sm ${action.kind === "update_balance" ? "btn-primary" : "btn-dark"}`} disabled={busy} onClick={run}>{busy ? "Working…" : "Confirm"}</button>
            <button className="btn btn-outline btn-sm" disabled={busy} onClick={() => { setState("cancelled"); onCancel(); }}>Cancel</button>
          </div>}
    </div>
  );
}

const shortDate = (iso) => new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });

function RecordCard({ rec, onOpen }) {
  const owed = rec.perspective === "owed_to_me";
  return (
    <div className="draft-card record-card">
      <div className="draft-line"><strong>{rec.name}</strong>{rec.local_id && <span className="mono small">#{rec.local_id}</span>}</div>
      <div className="small muted">{rec.business_name}{rec.khataz_id ? ` · @${rec.khataz_id}` : ""}</div>
      <div className="record-balance">
        <span className="small muted">{Number(rec.balance) === 0 ? "Settled" : owed ? "Owes you" : "You owe"}</span>
        <strong>{money(rec.balance, rec.currency)}</strong>
      </div>
      {rec.recent.length > 0 && (
        <div className="mini-ledger">
          {rec.recent.map((e) => (
            <div key={e.id} className={`mini-row ${e.reversed || e.status !== "active" ? "dim" : ""}`}>
              <span className="small muted">{shortDate(e.occurred_at)}</span>
              <span className="small mini-desc">{e.description || e.label}</span>
              <span className="small mono">{e.sign}{Number(e.amount).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
      {rec.waiting && <div className="small" style={{ color: "var(--warn, #b26a00)" }}>Something on this record is waiting for review.</div>}
      <button className="btn btn-primary btn-sm" onClick={() => onOpen(rec.relationship_id)}>Open record</button>
    </div>
  );
}

function ListCard({ list, onOpen }) {
  return (
    <div className="draft-card list-card">
      {list.items.map((r) => (
        <button key={r.relationship_id} type="button" className="list-row" onClick={() => onOpen(r.relationship_id)}>
          <span className="list-name"><strong>{r.name}</strong><span className="small muted">{r.local_id ? `#${r.local_id} · ` : ""}{r.business_name}</span></span>
          <span className={`small mono ${r.perspective === "owed_to_me" ? "pos" : "neg"}`}>{money(r.balance, r.currency)}</span>
        </button>
      ))}
      {list.more > 0 && <div className="small muted">and {list.more} more</div>}
    </div>
  );
}

function useVoice(onText, onError) {
  const [mode, setMode] = useState(null); // server | browser | null
  const [listening, setListening] = useState(false);
  const rec = useRef(null);
  useEffect(() => {
    api("/api/ai/status").then((s) => {
      const canRecord = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
      setMode(s.voice_server && canRecord ? "server" : SR ? "browser" : null);
    }).catch(() => setMode(SR ? "browser" : null));
  }, []);

  async function start() {
    if (mode === "browser") {
      const r = new SR();
      r.lang = navigator.language || "en-US"; r.interimResults = false; r.maxAlternatives = 1;
      r.onresult = (e) => onText(e.results[0][0].transcript);
      r.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") onError("Couldn't hear that. Check the microphone permission."); };
      r.onend = () => setListening(false);
      rec.current = r; r.start(); setListening(true);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks = [];
      mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setListening(false);
        const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        if (blob.size < 1000) return;
        const fd = new FormData();
        fd.append("file", blob, (mr.mimeType || "").includes("mp4") ? "voice.mp4" : "voice.webm");
        try {
          const { text } = await api("/api/ai/transcribe", { method: "POST", form: fd });
          text ? onText(text) : onError("I didn't catch that. Try again.");
        } catch (err) { onError(err.message); }
      };
      rec.current = mr; mr.start(); setListening(true);
      setTimeout(() => mr.state === "recording" && mr.stop(), 30000); // 30 s max
    } catch {
      onError("Allow the microphone to use voice.");
    }
  }
  function stop() { try { rec.current?.stop(); } catch { /* already stopped */ } }
  return { available: !!mode, listening, toggle: () => (listening ? stop() : start()) };
}

function DraftCard({ draft, onOpen }) {
  const rec = draft.records.find((r) => r.relationship_id === draft.relationship_id);
  const who = rec ? rec.name : draft.new_person ? `${draft.new_person} (new)` : "—";
  const cur = rec?.currency || draft.currency || "";
  return (
    <div className="draft-card">
      <div className="draft-line"><span>{draft.action === "add" ? "Add money" : "Subtract money"}</span>
        <strong>{draft.amount ? money(draft.amount, cur || "USD") : "—"}</strong></div>
      <div className="small muted">{who}{draft.description ? ` · ${draft.description}` : ""}{draft.method ? ` · ${draft.method}` : ""}</div>
      <button className="btn btn-primary btn-sm" onClick={onOpen}>Check and save</button>
    </div>
  );
}

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([{ role: "assistant", content: HELLO, hello: true }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastDraft, setLastDraft] = useState(null);
  const [checking, setChecking] = useState(null);
  const end = useRef();
  const msgsRef = useRef(msgs);
  msgsRef.current = msgs;
  const draftRef = useRef(lastDraft);
  draftRef.current = lastDraft;
  const navigate = useNavigate();

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, open]);

  const voice = useVoice((t) => send(null, t, true), (msg) => setMsgs((m) => [...m, { role: "assistant", content: msg, error: true }]));

  async function send(e, said, byVoice = false) {
    e?.preventDefault();
    const t = (said ?? text).trim();
    if (!t || busy) return;
    const next = [...msgsRef.current, { role: "user", content: t, voice: byVoice }];
    setMsgs(next); setText(""); setBusy(true);
    try {
      const strip = draftRef.current && Object.fromEntries(Object.entries(draftRef.current).filter(([k]) => !["records", "businesses", "matches"].includes(k)));
      const r = await api("/api/ai/chat", {
        method: "POST",
        body: { messages: next.filter((m) => !m.hello).map(({ role, content }) => ({ role, content })), draft: strip || null,
                business_id: getOpenBusiness() },
      });
      setLastDraft(r.draft || null);
      setMsgs([...next, { role: "assistant", content: r.reply, draft: r.ready ? r.draft : null, action: r.action || null,
                          record: r.record || null, list: r.records_list || null }]);
      if (byVoice) speak(r.reply);
    } catch (err) {
      setMsgs([...next, { role: "assistant", content: err.message, error: true }]);
    }
    setBusy(false);
  }

  function actionDone(a) {
    const said = { update_balance: `Done. ${a.name}'s balance is now ${a.to} ${a.currency}.`,
                   undo_entry: `Done. The last entry on ${a.name}'s record was undone.`,
                   remove_record: `Done. ${a.name}'s record was removed.` }[a.kind];
    setMsgs((m) => [...m, { role: "assistant", content: said }]);
    window.dispatchEvent(new Event("khataz:changed"));
    navigate(a.kind === "remove_record" ? "/" : `/records/${a.relationship_id}`);
  }

  function saved(relId, draft) {
    setChecking(null); setLastDraft(null);
    const who = draft.records.find((r) => r.relationship_id === relId)?.name || draft.new_person || "the record";
    setMsgs((m) => [...m, { role: "assistant", content: `Saved to ${who}.` }]);
    navigate(`/records/${relId}`);
  }

  return (
    <>
      {open && (
        <div className="assistant-panel" role="dialog" aria-label="Khataz assistant">
          <div className="assistant-head">
            <strong>Khataz assistant</strong>
            <button className="icon-btn" aria-label="Close" onClick={() => setOpen(false)}>×</button>
          </div>
          <div className="assistant-body">
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.role}${m.error ? " error" : ""}`}>
                {m.content}
                {m.draft && <DraftCard draft={m.draft} onOpen={() => setChecking(m.draft)} />}
                {m.record && <RecordCard rec={m.record} onOpen={(id) => navigate(`/records/${id}`)} />}
                {m.list && m.list.items.length > 0 && <ListCard list={m.list} onOpen={(id) => navigate(`/records/${id}`)} />}
                {m.action && <ActionCard action={m.action} onDone={actionDone}
                                         onCancel={() => setMsgs((x) => [...x, { role: "assistant", content: "Done. Nothing was changed." }])} />}
              </div>
            ))}
            {busy && <div className="bubble assistant typing"><span /><span /><span /></div>}
            <div ref={end} />
          </div>
          <form className="assistant-input" onSubmit={send}>
            {voice.available && (
              <button type="button" className={`mic-btn ${voice.listening ? "on" : ""}`} onClick={voice.toggle}
                      aria-label={voice.listening ? "Stop recording" : "Speak"} title={voice.listening ? "Tap to stop" : "Speak"}>
                {voice.listening ? "■" : "🎤"}
              </button>
            )}
            <input autoFocus value={text} onChange={(e) => setText(e.target.value)} maxLength={2000}
                   placeholder={voice.listening ? "Listening… tap ■ when done" : "Ask or type an entry…"} />
            <button className="btn btn-primary btn-sm" disabled={busy || !text.trim()}>Send</button>
          </form>
        </div>
      )}
      <button className="assistant-fab" aria-label="Khataz assistant" onClick={() => setOpen((o) => !o)}>
        {open ? "×" : "✦"}
      </button>
      {checking && <CheckEntry draft={checking} onClose={() => setChecking(null)} onSaved={(id) => saved(id, checking)} />}
    </>
  );
}
