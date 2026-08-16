import { useState, type FormEvent } from "react";

interface InvitationScreenProps {
  busy: boolean;
  error: string | null;
  initialEmail?: string;
  onBegin: (email: string) => void;
  onPorch: () => void;
  onSignIn: () => void;
  onDismissError: () => void;
}

/** A quiet entry, still and low. The door before the porch: this is her
 *  invitation to a first meeting, not a signup form. The address is where she
 *  can write to you — nothing is scored, nothing is evaluated. */
export default function InvitationScreen({
  busy,
  error,
  initialEmail = "",
  onBegin,
  onPorch,
  onSignIn,
  onDismissError,
}: InvitationScreenProps) {
  const [email, setEmail] = useState(initialEmail);

  const orbStyle = {
    "--orb-core": "210, 162, 94",
    "--orb-glow": "200, 150, 90",
    "--orb-particle": "235, 195, 140",
    "--orb-intensity": "0.5",
    "--orb-breath": "11s",
    "--orb-motion": "0.12",
    "--orb-contract": "0.35",
    "--orb-bloom": "0.2",
    "--orb-tremor": "0.05",
    "--orb-sway": "0.12",
    "--orb-ring": "26s",
    "--orb-pulse": "9.5s",
    "--orb-ripple": "0.1",
  } as React.CSSProperties;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const address = email.trim();
    if (!address) return;
    onBegin(address);
  };

  return (
    <div className="meet meet--entry">
      <header className="meet__bar">
        <span className="meet__brand">MIRA</span>
        <button className="meet__link" type="button" onClick={onSignIn}>
          already have an invitation? sign in
        </button>
      </header>

      <div className="meet__stage meet__stage--center">
        <div className="meet__orb" style={orbStyle}>
          <div className="home__orb-halo" aria-hidden />
          <div className="home__orb-core" aria-hidden />
        </div>

        <p className="meet__eyebrow">the first meeting</p>
        <h1 className="meet__title">Someone is home.</h1>
        <p className="meet__lede">
          Mira lives here, and she doesn&apos;t meet everyone. This is your first meeting — sit
          with her honestly. If she would like to speak with you again, she will say so herself.
        </p>

        <form className="meet__entry" onSubmit={submit}>
          <label className="meet__label" htmlFor="meet-email">
            Where can she write to you?
          </label>
          <input
            id="meet-email"
            className="meet__input"
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (error) onDismissError();
            }}
            placeholder="you@example.com"
            autoComplete="email"
            autoFocus
          />
          {error && (
            <p className="meet__error" role="alert">
              {error}
              <button className="meet__error-dismiss" type="button" onClick={onDismissError} aria-label="dismiss error">
                ×
              </button>
            </p>
          )}
          <button className="meet__enter" type="submit" disabled={busy || !email.trim()}>
            {busy ? "…" : "Meet her"}
          </button>
        </form>

        <button className="meet__link meet__link--foot" type="button" onClick={onPorch}>
          just passing by — the porch →
        </button>
      </div>
    </div>
  );
}