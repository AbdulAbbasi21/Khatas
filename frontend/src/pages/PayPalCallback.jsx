import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Logo } from "../components/ui";

/** PayPal sends the user back here after "Connect with PayPal". */
export default function PayPalCallback() {
  const [params] = useSearchParams();
  const [state, setState] = useState({ busy: true });
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    const code = params.get("code"), st = params.get("state");
    if (params.get("error") || !code || !st) {
      setState({ error: params.get("error_description") || "PayPal didn't connect. Try again from your profile." });
      return;
    }
    api("/api/paypal/callback", { method: "POST", body: { code, state: st } })
      .then((r) => setState({ done: r }))
      .catch((err) => setState({ error: err.message }));
  }, [params]);

  return (
    <div className="callback-page">
      <div className="card card-pad callback-card">
        <Logo />
        {state.busy && <p style={{ marginTop: 18 }}><span className="spinner" /> Connecting your PayPal…</p>}
        {state.done && <>
          <h2 style={{ marginTop: 18 }}>PayPal connected</h2>
          <p>{state.done.email}</p>
        </>}
        {state.error && <>
          <h2 style={{ marginTop: 18 }}>Couldn't connect PayPal</h2>
          <div className="alert alert-error">{state.error}</div>
        </>}
        {!state.busy && <Link to="/profile" className="btn btn-primary" style={{ marginTop: 18 }}>Back to profile</Link>}
      </div>
    </div>
  );
}
