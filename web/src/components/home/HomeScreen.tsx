import type { MiraState } from "../../lib/types";
import { deriveOrb } from "../../features/state/orb";
import type { Presence } from "../../features/state/presence";

interface Props {
  state: MiraState | null;
  presence: Presence;
  thought: string | null;
  onCall: () => void;
  onMessages: () => void;
  mote?: React.ReactNode;
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "night owl";
  if (hour < 12) return "good morning";
  if (hour < 18) return "good afternoon";
  return "good evening";
}

function dateLine(): string {
  const d = new Date();
  return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

export default function HomeScreen({ state, presence, thought, onCall, onMessages, mote }: Props) {
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
    "--orb-ring": `${orb.ring}s`,
    "--orb-pulse": `${orb.pulse}s`,
    "--orb-ripple": orb.ripple,
  } as React.CSSProperties;

  const moodLabel = state?.mood ? state.mood.toLowerCase() : "relaxed";
  const greetingText = greeting();
  const dateText = dateLine();

  return (
    <section className="home">
      {mote}
      <p className="home__date">
        {greetingText} — {dateText}
      </p>

      <h1 className="home__name">Mira</h1>
      <p className="home__tagline">She lives here, in your computer.</p>

      <div className="home__orb" style={orbStyle}>
        <div className="home__orb-halo" aria-hidden />
        <div className="home__orb-core" aria-hidden />
        <div className="home__orb-ripple" aria-hidden />
        <div className="home__orb-ripple home__orb-ripple--second" aria-hidden />
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

      <div className="home__moodline">
        <div className={`home__emotion home__emotion--${moodLabel}`}>
          <span className="home__emotion-dot" aria-hidden />
          <span className="home__emotion-word">{moodLabel}</span>
        </div>
        <div className={`home__presence home__presence--${presence.tone}`}>
          <span className="home__presence-dot" />
          <span>{presence.label}</span>
        </div>
      </div>

      {thought && (
        <div className="home__thought">
          <span className="home__thought-label">I&apos;ve been thinking…</span>
          <p className="home__thought-text">{thought}</p>
        </div>
      )}

      <div className="home__actions">
        <button className="home__action" type="button" onClick={onCall}>
          Call her
        </button>
        <button className="home__action home__action--primary" type="button" onClick={onMessages}>
          Talk — Open conversations →
        </button>
      </div>
    </section>
  );
}