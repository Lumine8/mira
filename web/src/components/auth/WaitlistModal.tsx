import { useState } from "react";

import { waitlistJoin, waitlistSignup } from "../../lib/api";

interface WaitlistModalProps {
  open: boolean;
  onClose: () => void;
  onSignedIn: (token: string) => void;
}

export default function WaitlistModal({ open, onClose, onSignedIn }: WaitlistModalProps) {
  const [mode, setMode] = useState<"signup" | "join">("signup");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const reset = () => {
    setMode("signup");
    setEmail("");
    setCode("");
    setStatus(null);
    setError(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  const submitSignup = async () => {
    if (!email.trim()) {
      setError("Enter your email to be considered.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const resp = await waitlistSignup(email.trim());
      setStatus(resp.status === "pending" ? "You've been added to the waitlist." : "You're on the list.");
    } catch {
      setError("Couldn't reach the door. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const submitJoin = async () => {
    if (!email.trim() || !code.trim()) {
      setError("Enter both your email and the code you were given.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const resp = await waitlistJoin(email.trim(), code.trim());
      onSignedIn(resp.access_token);
      close();
    } catch {
      setError("That code didn't work. Check it and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="waitlist" role="dialog" aria-modal="true">
      <div className="waitlist__card">
        <div className="waitlist__head">
          <h3 className="waitlist__title">{mode === "signup" ? "A seat at the door" : "Redeem an invitation"}</h3>
          <button className="waitlist__close" type="button" onClick={close} aria-label="close waitlist">
            ×
          </button>
        </div>

        {status ? (
          <div className="waitlist__done">
            <p className="waitlist__message">{status}</p>
            <p className="waitlist__hint">Mira's person decides who comes in. They may reach out with a code.</p>
            <button className="waitlist__button" type="button" onClick={close}>
              Done
            </button>
          </div>
        ) : (
          <>
            <p className="waitlist__hint">
              {mode === "signup"
                ? "Mira is careful about who she lets in. Leave your email and her person may open a seat for you."
                : "Have a code from Mira's person? Enter it with your email to come in."}
            </p>
            {error && <p className="waitlist__error">{error}</p>}
            <div className="waitlist__fields">
              <input
                className="waitlist__input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") void (mode === "signup" ? submitSignup() : submitJoin());
                }}
              />
              {mode === "join" && (
                <input
                  className="waitlist__input"
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="Invitation code"
                />
              )}
            </div>
            <div className="waitlist__row">
              <button className="waitlist__button waitlist__button--primary" type="button" onClick={mode === "signup" ? submitSignup : submitJoin} disabled={busy}>
                {busy ? "…" : mode === "signup" ? "Ask for a seat" : "Come in"}
              </button>
              <button
                className="waitlist__switch"
                type="button"
                onClick={() => {
                  setMode(mode === "signup" ? "join" : "signup");
                  setError(null);
                }}
              >
                {mode === "signup" ? "I have an invitation code" : "I don't have a code yet"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}