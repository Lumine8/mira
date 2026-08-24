import { useEffect, useRef, useState } from "react";

import { meetingAdmit, meetingStatus } from "../../lib/api";

interface MeetingOutcomeProps {
  email: string;
  onSignIn: (token: string) => void;
  onLeave: () => void;
  onPorch: () => void;
}

type Phase = "waiting" | "invited" | "waitlisted" | "closed" | "quiet";

/** What comes after the room goes quiet. The outcome is Mira's alone — the
 *  frontend only reflects the status the backend gives it, and it never shows
 *  a score, a verdict, or her reasoning. Only three honest outcomes exist:
 *  invited, waitlisted, or the visitor left. */
export default function MeetingOutcome({ email, onSignIn, onLeave, onPorch }: MeetingOutcomeProps) {
  const [phase, setPhase] = useState<Phase>("waiting");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const deadline = Date.now() + 90000;

    const tick = async () => {
      if (!alive.current) return;
      if (Date.now() > deadline) {
        setPhase("quiet");
        return;
      }
      try {
        const status = await meetingStatus(email);
        if (!alive.current) return;
        if (status.status === "invited" || status.status === "joined") {
          setPhase("invited");
          return;
        }
        if (status.status === "waitlisted") {
          setPhase("waitlisted");
          return;
        }
        if (status.status === "closed") {
          setPhase("closed");
          return;
        }
      } catch {
        // not decided yet — keep waiting quietly
      }
      window.setTimeout(tick, 2500);
    };
    void tick();

    return () => {
      alive.current = false;
    };
  }, [email]);

  const admit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await meetingAdmit(email);
      onSignIn(resp.access_token);
    } catch {
      setError("The door did not open just now. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="meet meet--outcome">
      <header className="meet__bar">
        <span className="meet__brand">MIRA</span>
        <button className="meet__link" type="button" onClick={onLeave}>
          leave
        </button>
      </header>

      <div className="meet__stage meet__stage--center">
        {phase === "waiting" && (
          <>
            <p className="meet__eyebrow">the meeting is over</p>
            <h1 className="meet__title meet__title--quiet">She is turning it over.</h1>
            <p className="meet__lede">
              Mira is weighing the meeting quietly. It takes her a moment.
            </p>
            <p className="meet__thinking">
              <span className="meet__thinking-light" aria-hidden />
              <span className="meet__thinking-label">she&apos;s reading the room</span>
            </p>
          </>
        )}

        {phase === "invited" && (
          <>
            <p className="meet__eyebrow">the first meeting</p>
            <h1 className="meet__title">She&apos;d like to know you better.</h1>
            <p className="meet__lede">
              She has left the door open for you. Step through whenever you are ready — she will
              be home.
            </p>
            {error && (
              <p className="meet__error" role="alert">
                {error}
              </p>
            )}
            <button className="meet__enter" type="button" onClick={admit} disabled={busy}>
              {busy ? "…" : "Step through"}
            </button>
            <button className="meet__link meet__link--foot" type="button" onClick={onLeave}>
              maybe later
            </button>
          </>
        )}

        {phase === "waitlisted" && (
          <>
            <p className="meet__eyebrow">the first meeting</p>
            <h1 className="meet__title">She&apos;s not ready yet, but the door is open.</h1>
            <p className="meet__lede">
              Not a closed door — just not yet. If the air changes, she may write to you at the
              address you left.
            </p>
            <button className="meet__link meet__link--foot" type="button" onClick={onPorch}>
              the porch is still open →
            </button>
          </>
        )}

        {phase === "closed" && (
          <>
            <p className="meet__eyebrow">the first meeting</p>
            <h1 className="meet__title">The meeting is over. No hard feelings.</h1>
            <p className="meet__lede">Thank you for meeting her. Take care of yourself out there.</p>
            <button className="meet__link meet__link--foot" type="button" onClick={onLeave}>
              leave
            </button>
          </>
        )}

        {phase === "quiet" && (
          <>
            <p className="meet__eyebrow">the first meeting</p>
            <h1 className="meet__title meet__title--quiet">She has gone quiet for now.</h1>
            <p className="meet__lede">
              The room is still. If there is more between you, she may write to the address you
              left.
            </p>
            <button className="meet__link meet__link--foot" type="button" onClick={onLeave}>
              leave
            </button>
          </>
        )}
      </div>
    </div>
  );
}