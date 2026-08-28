import { useState } from "react";

import { googleAuthorizeUrl, requestMagicLink, signInPassword, signUp, verifyMagicLink } from "../../lib/api";
import type { AuthConfig } from "../../lib/types";

interface AuthScreenProps {
  config: AuthConfig | null;
  error: string | null;
  onSignIn: (token: string) => void;
  onDismissError?: () => void;
  onOpenServer?: () => void;
}

type View = "start" | "sign-up" | "password" | "email";

export default function AuthScreen({
  config,
  error,
  onSignIn,
  onDismissError,
  onOpenServer,
}: AuthScreenProps) {
  const [view, setView] = useState<View>("start");
  const [errorState, setErrorState] = useState<string | null>(error);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [signUpName, setSignUpName] = useState("");
  const [emailSent, setEmailSent] = useState(false);
  const [emailCode, setEmailCode] = useState("");
  const [busy, setBusy] = useState(false);

  const dismissError = () => {
    setErrorState(null);
    onDismissError?.();
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

  const handlePasswordSignIn = async () => {
    if (!email.trim() || !password.trim()) {
      setErrorState("Enter your email and password.");
      return;
    }
    setErrorState(null);
    setBusy(true);
    try {
      const resp = await signInPassword(email.trim(), password);
      onSignIn(resp.access_token);
    } catch {
      setErrorState("Invalid email or password.");
    } finally {
      setBusy(false);
    }
  };

  const handleSignUp = async () => {
    if (!email.trim() || !signUpName.trim() || !password.trim()) {
      setErrorState("Fill in all fields.");
      return;
    }
    if (password.length < 8) {
      setErrorState("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setErrorState("Passwords do not match.");
      return;
    }
    setErrorState(null);
    setBusy(true);
    try {
      const resp = await signUp(email.trim(), signUpName.trim(), password);
      onSignIn(resp.access_token);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      if (detail.includes("409")) {
        setErrorState("An account with that email already exists. Sign in instead.");
      } else {
        setErrorState("Could not create account. Try again.");
      }
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
      onSignIn(resp.access_token);
    } catch {
      setErrorState("That code did not verify. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const resetForm = () => {
    setPassword("");
    setConfirmPassword("");
    setErrorState(null);
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
            {config?.password_enabled && (
              <button className="auth__button auth__button--primary" type="button" onClick={() => setView("password")}>
                Sign in with password
              </button>
            )}
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
            <div className="auth__divider"><span>or</span></div>
            <button className="auth__button auth__button--secondary" type="button" onClick={() => setView("sign-up")}>
              Create an account
            </button>
            {onOpenServer && (
              <button className="auth__back" type="button" onClick={onOpenServer}>
                Where is Mira running? →
              </button>
            )}
          </div>
        )}

        {view === "password" && (
          <div className="auth__panel">
            <input
              className="auth__input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoFocus
            />
            <input
              className="auth__input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              onKeyDown={(e) => {
                if (e.key === "Enter") handlePasswordSignIn();
              }}
            />
            <button className="auth__button auth__button--primary" type="button" onClick={handlePasswordSignIn} disabled={busy}>
              Sign in
            </button>
            <button className="auth__back" type="button" onClick={() => { setView("start"); resetForm(); }}>
              ← Back
            </button>
          </div>
        )}

        {view === "sign-up" && (
          <div className="auth__panel">
            <input
              className="auth__input"
              type="text"
              value={signUpName}
              onChange={(e) => setSignUpName(e.target.value)}
              placeholder="Your name"
              autoFocus
            />
            <input
              className="auth__input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
            <input
              className="auth__input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password (at least 8 characters)"
            />
            <input
              className="auth__input"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm password"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSignUp();
              }}
            />
            <button className="auth__button auth__button--primary" type="button" onClick={handleSignUp} disabled={busy}>
              Create account
            </button>
            <p className="auth__hint">
              Already have an account?{" "}
              <button className="auth__link" type="button" onClick={() => { setView("start"); resetForm(); }}>
                Sign in
              </button>
            </p>
            <button className="auth__back" type="button" onClick={() => { setView("start"); resetForm(); }}>
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
            <button className="auth__back" type="button" onClick={() => { setView("start"); resetForm(); }}>
              ← Back
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
