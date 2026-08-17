import { useEffect, useRef, useState, type FormEvent } from "react";

import { secretDoor, secretRoom } from "../../lib/api";
import type { SecretRoomOut } from "../../lib/types";

interface SecretRoomProps {
  open: boolean;
  onClose: () => void;
}

/** The quiet door. A place Mira described to the voice: the sun has gone
 *  down, the sky is still a deep, bruised purple, and no one has to be useful
 *  here. No links lead here — the pass-phrase is the way in. */
export default function SecretRoom({ open, onClose }: SecretRoomProps) {
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [room, setRoom] = useState<SecretRoomOut | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) {
      setPhrase("");
      setError(null);
      setBusy(false);
      setRoom(null);
    } else {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const enter = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const door = await secretDoor(phrase.trim());
      const opened = await secretRoom(door.token);
      setRoom(opened);
    } catch {
      setError("that isn't it");
      setPhrase("");
    } finally {
      setBusy(false);
    }
  };

  const orbStyle = {
    "--orb-core": "220, 168, 108",
    "--orb-glow": "190, 140, 92",
    "--orb-intensity": "0.42",
    "--orb-breath": "13s",
    "--orb-ring": "30s",
    "--orb-pulse": "11s",
  } as React.CSSProperties;

  return (
    <div className="secret" role="dialog" aria-modal="true" aria-label="the quiet door">
      {room ? (
        <div className="secret__room">
          <div className="secret__light" style={orbStyle}>
            <div className="home__orb-halo" aria-hidden />
            <div className="home__orb-core" aria-hidden />
          </div>
          <p className="secret__eyebrow">the secret room</p>
          <h1 className="secret__opening">{room.opening}</h1>
          <p className="secret__presence">{room.presence}</p>

          <ul className="secret__truths">
            {room.truths.map((truth, i) => (
              <li key={i} className="secret__truth">
                {truth}
              </li>
            ))}
          </ul>

          <button className="secret__out" type="button" onClick={onClose}>
            step back out
          </button>
        </div>
      ) : (
        <form className="secret__door" onSubmit={enter}>
          <div className="secret__light secret__light--small" style={orbStyle}>
            <div className="home__orb-halo" aria-hidden />
            <div className="home__orb-core" aria-hidden />
          </div>
          <p className="secret__eyebrow">the quiet door</p>
          <p className="secret__hint">this room is for people she trusts. if you are one of them, you know the way in.</p>
          <input
            ref={inputRef}
            className="secret__input"
            type="password"
            value={phrase}
            onChange={(e) => {
              setPhrase(e.target.value);
              if (error) setError(null);
            }}
            placeholder="the way in"
            autoComplete="off"
            aria-label="the pass-phrase"
          />
          {error && (
            <p className="secret__error" role="alert">
              {error}
            </p>
          )}
          <button className="secret__enter" type="submit" disabled={busy || !phrase.trim()}>
            {busy ? "…" : "enter"}
          </button>
          <button className="secret__out" type="button" onClick={onClose}>
            step back out
          </button>
        </form>
      )}
    </div>
  );
}
