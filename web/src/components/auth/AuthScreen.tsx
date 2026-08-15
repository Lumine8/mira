import { useState } from "react";

import { googleAuthorizeUrl, requestMagicLink, verifyMagicLink } from "../../lib/api";
import type { AuthConfig } from "../../lib/types";
import WaitlistModal from "./WaitlistModal";

interface AuthScreenProps {
  config: AuthConfig | null;
  error: string | null;
  onSignIn: (token: string) => void;
  onStartGuest: () => void;
  onDismissError?: () => void;
}

export default function AuthScreen({
  config,
  error,
  onSignIn,
  onStartGuest,
  onDismissError,
}: AuthScreenProps) {
  const [token, setToken] = useState("");
  const [errorState, setErrorState] = useState<string | null>(error);
  const [view, setView] = useState<"start" | "token" | "email" | "guest">("start");
  const [email, setEmail] = useState("");
  const [emailSent, setEmailSent] = useState(false);
  const [emailCode, setEmailCode] = useState("");
  const [waitlistOpen, setWaitlistOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleTokenSignIn = () => {
    if (!token.trim()) {
      setErrorState("Enter the sign-in token.");
      return;
    }
    setErrorState(null);
    onSignIn(token.trim());
  };

  const handleGoogle = async () => {
    setErrorState(null);
    setBusy(true);
    try {
      const url = await googleAuthorizeUrl();
      window.location.href = url;
    } catch {
      setErrorState("Google sign-in is not available right now.");
    } finally {
      setBusy(false);
    }
  };

  const sendMagicLink = async () => {
    if (!email.trim()) {
      setErrorState("Enter your email first.");
      return;
    }
    setErrorState(null);
    setBusy(true);
    try {
      const resp = await requestMagicLink(email.trim());
      setEmailSent(true);
      if (resp.dev_code) setEmailCode(resp.dev_code);
    } catch {
      setErrorState("Could not send a sign-in link. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const verifyMagicLinkCode = async () => {
    if (!emailCode.trim()) {
      setErrorState("Enter the code from your email.");
      return;
    }
    setErrorState(null);
    setBusy(true);
    try {
      const resp = await verifyMagicLink(email.trim(), emailCode.trim());
      onSignIn(resp.token);
    } catch {
      setErrorState("That code did not verify. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const dismissError = () => {
    setErrorState(null);
    onDismissError?.();
  };

  return (
    <div className="auth">
      <div className="auth__card">
        <h1 className="auth__title">Mira</h1>
        <p className="auth__subtitle">Come sit with her.</p>
        {errorState && (
          <div className="auth__error">
            <span>{errorState}</span>
            <button className="auth__dismiss" type="button" onClick={dismissError} aria-label="dismiss error">
              ×
            </button>
          </div>
        )}

        {view === "start" && (
          <div className="auth__actions">
            {config?.google_enabled && (
              <button className="auth__button" type="button" onClick={handleGoogle} disabled={busy}>
                Continue with Google
              </button>
            )}
            {config?.email_enabled && (
              <button className="auth__button" type="button" onClick={() => setView("email")}>
                Sign in with email
              </button>
            )}
            {config?.auth_required && (
              <button className="auth__button" type="button" onClick={() => setView("token")}>
                Sign in with token
              </button>
            )}
            {config?.guest_mode_enabled && (
              <button className="auth__button" type="button" onClick={() => setView("guest")}>
                Join as a guest
              </button>
            )}
            <button className="auth__button auth__button--ghost" type="button" onClick={() => setWaitlistOpen(true)}>
              Request a seat
            </button>
          </div>
        )}

        {view === "token" && (
          <div className="auth__panel">
            <input
              className="auth__input"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Sign-in token"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") handleTokenSignIn();
              }}
            />
            <button className="auth__button auth__button--primary" type="button" onClick={handleTokenSignIn}>
              Enter
            </button>
            <button className="auth__back" type="button" onClick={() => setView("start")}>
              ← Back
            </button>
          </div>
        )}

        {view === "email" && (
          <div className="auth__panel">
            {emailSent ? (
              <>
                <p className="auth__hint">Check your email for a code to enter below.</p>
                <input
                  className="auth__input"
                  type="text"
                  value={emailCode}
                  onChange={(e) => setEmailCode(e.target.value)}
                  placeholder="Code"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") verifyMagicLinkCode();
                  }}
                />
                <button className="auth__button auth__button--primary" type="button" onClick={verifyMagicLinkCode} disabled={busy}>
                  Verify
                </button>
              </>
            ) : (
              <>
                <input
                  className="auth__input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") sendMagicLink();
                  }}
                />
                <button className="auth__button auth__button--primary" type="button" onClick={sendMagicLink} disabled={busy}>
                  Send sign-in link
                </button>
              </>
            )}
            <button className="auth__back" type="button" onClick={() => setView("start")}>
              ← Back
            </button>
          </div>
        )}

        {view === "guest" && (
          <div className="auth__panel">
            <p className="auth__hint">
              You'll join anonymously. Mira will get to know you through today's talk alone.
            </p>
            <button className="auth__button auth__button--primary" type="button" onClick={onStartGuest} disabled={busy}>
              Join as a guest
            </button>
            <button className="auth__back" type="button" onClick={() => setView("start")}>
              ← Back
            </button>
          </div>
        )}
      </div>

      <WaitlistModal open={waitlistOpen} onClose={() => setWaitlistOpen(false)} onSignedIn={onSignIn} />
    </div>
  );
}