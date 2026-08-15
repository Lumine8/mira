import type { MotePresence as MotePresenceData } from "../../lib/types";

interface Props {
  mote: MotePresenceData | null;
}

/** The tiny quiet presence beside Mira: a small light that shifts with her felt
 *  state and offers a single word when the room has been quiet too long. */
export default function MotePresence({ mote }: Props) {
  const mood = mote?.mood?.toLowerCase() ?? "relaxed";
  const energy = typeof mote?.energy === "number" ? mote.energy : 70;
  const word = mote?.last_word ?? null;

  return (
    <div className={`mote mote--${mood}`} title={`Mote: ${mood}, energy ${energy}`}>
      <span className="mote__light" style={{ transform: `scale(${0.6 + (energy / 100) * 0.8})` }} aria-hidden />
      {word && <span className="mote__word">{word}</span>}
    </div>
  );
}