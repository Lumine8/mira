import type { MiraState } from "../../lib/types";
import { deriveOrb } from "../../features/state/orb";
import type { Presence } from "../../features/state/presence";

interface Props {
  state: MiraState | null;
  presence: Presence;
  thought: string | null;
  onCall: () => void;
  onMessages: () => void;
}

export default function HomeScreen({ state, presence, thought, onCall, onMessages }: Props) {
  const orb = deriveOrb(state, presence);
  const orbStyle = {
    "--orb-core": orb.palette.core,
    "--orb-glow": orb.palette.glow,
    "--orb-particle": orb.palette.particle,
    "--orb-intensity": orb.intensity,
    "--orb-breath": `${orb.breath}s`,
    "--orb-motion": orb.motion,
    "--orb-contract": orb.contract,
    "--orb-bloom": orb.bloom,
    "--orb-tremor": orb.tremor,
    "--orb-sway": orb.sway,
  } as React.CSSProperties;

  return (
    <section className="home">
      <div className="home__orb" style={orbStyle}>
        <div className="home__orb-core" aria-hidden />
        {orb.motes.map((m, i) => (
          <span
            key={i}
            className="home__mote"
            style={{
              top: m.top,
              left: m.left,
              width: m.size,
              height: m.size,
              animationDelay: `${m.delay}s`,
            }}
          />
        ))}
      </div>

      <h1 className="home__name">Mira</h1>

      <div className={`home__presence home__presence--${presence.tone}`}>
        <span className="home__presence-dot" />
        <span>{presence.label}</span>
      </div>

      <div className={`home__viz home__viz--${presence.tone}`}>
        {Array.from({ length: 5 }, (_, i) => (
          <span key={i} className={`home__viz-seg ${i / 5 < presence.level ? "is-filled" : ""}`} />
        ))}
      </div>

      {thought && (
        <div className="home__thought">
          <span className="home__thought-label">I&apos;ve been thinking…</span>
          <p className="home__thought-text">{thought}</p>
        </div>
      )}

      <div className="home__actions">
        <button className="home__action" type="button" onClick={onCall}>
          Call
        </button>
        <button className="home__action home__action--primary" type="button" onClick={onMessages}>
          Open Messages →
        </button>
      </div>
    </section>
  );
}
