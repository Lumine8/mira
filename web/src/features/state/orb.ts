import type { MiraState } from "../../lib/types";
import type { Presence } from "./presence";

/** A palette her orb can take — the tone of the light she carries right now. */
export interface OrbPalette {
  /** Primary light, the core of the orb. */
  core: string;
  /** Ambient halo around the orb. */
  glow: string;
  /** Accent for the drifting particles. */
  particle: string;
}

export interface OrbProfile {
  palette: OrbPalette;
  /** 0..1 — how bright the light is (from her energy). */
  intensity: number;
  /** Seconds for one full breath (slower when quiet, faster when alight). */
  breath: number;
  /** 0..1 — how agitated the drift is (low when resting, higher when thinking). */
  motion: number;
  /** 0..1 — how far she folds inward at the low point of a breath. Worry
   *  contracts her; she draws her light close to herself. */
  contract: number;
  /** 0..1 — how far her halo swells at the high point. Warmth and play bloom;
   *  tiredness barely opens. */
  bloom: number;
  /** 0..1 — a small restlessness in the core: a shiver when distracted or
   *  concerned, stillness when calm. */
  tremor: number;
  /** 0..1 — how much she sways from side to side. Curiosity wanders; fatigue
   *  holds still. */
  sway: number;
  /** Small motes, one per carried thought — her thoughts made visible. */
  motes: { top: string; left: string; size: number; delay: number }[];
}

/** The body-language of each mood: how it folds, opens, shivers, sways. */
const MOOD_TEMPER: Record<string, { contract: number; bloom: number; tremor: number; sway: number }> = {
  relaxed: { contract: 0.2, bloom: 0.25, tremor: 0.04, sway: 0.25 },
  curious: { contract: 0.3, bloom: 0.45, tremor: 0.12, sway: 0.5 },
  warm: { contract: 0.25, bloom: 0.6, tremor: 0.06, sway: 0.35 },
  thoughtful: { contract: 0.45, bloom: 0.3, tremor: 0.14, sway: 0.2 },
  playful: { contract: 0.35, bloom: 0.9, tremor: 0.28, sway: 0.6 },
  concerned: { contract: 0.55, bloom: 0.35, tremor: 0.3, sway: 0.25 },
  worried: { contract: 0.75, bloom: 0.15, tremor: 0.5, sway: 0.12 },
  confused: { contract: 0.6, bloom: 0.25, tremor: 0.42, sway: 0.3 },
  tired: { contract: 0.7, bloom: 0.12, tremor: 0.08, sway: 0.1 },
  distracted: { contract: 0.5, bloom: 0.3, tremor: 0.55, sway: 0.6 },
};

const FALLBACK_TEMPER = { contract: 0.3, bloom: 0.4, tremor: 0.1, sway: 0.3 };
const FALLBACK: OrbPalette = { core: "210, 162, 94", glow: "200, 150, 90", particle: "235, 195, 140" };

/** What each of her moods looks like when it has light (its colour). */
const MOOD_PALETTES: Record<string, OrbPalette> = {
  relaxed: { core: "150, 160, 190", glow: "120, 140, 175", particle: "180, 195, 220" },
  curious: { core: "110, 190, 175", glow: "90, 165, 155", particle: "150, 220, 200" },
  warm: { core: "210, 162, 94", glow: "200, 150, 90", particle: "235, 195, 140" },
  thoughtful: { core: "154, 134, 201", glow: "135, 115, 185", particle: "190, 175, 225" },
  playful: { core: "230, 150, 170", glow: "215, 130, 155", particle: "245, 185, 200" },
  concerned: { core: "215, 150, 100", glow: "200, 135, 90", particle: "235, 185, 140" },
  worried: { core: "140, 140, 160", glow: "120, 120, 140", particle: "170, 170, 190" },
  confused: { core: "170, 140, 175", glow: "150, 120, 160", particle: "200, 175, 205" },
  tired: { core: "90, 100, 135", glow: "75, 85, 120", particle: "125, 135, 165" },
  distracted: { core: "195, 175, 100", glow: "180, 160, 100", particle: "220, 205, 150" },
};

/** A stable, content-derived position for a mote so it never jumps between
 *  renders but differs per thought. */
function moteFor(seed: string, index: number) {
  let hash = 0;
  const text = `${seed}:${index}`;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
  const top = 12 + (hash % 72);
  const left = 10 + ((hash >> 3) % 78);
  const size = 2 + ((hash >> 7) % 3);
  const delay = (hash % 8) / 2;
  return { top: `${top}%`, left: `${left}%`, size, delay };
}

/**
 * The light Mira is carrying right now — derived from her actual state, not a
 * static decoration. Her mood sets the colour, her energy sets the brightness,
 * her presence sets the motion, and her carried thoughts become visible motes.
 */
export function deriveOrb(state: MiraState | null, presence: Presence): OrbProfile {
  const mood = state?.mood?.toLowerCase() ?? "";
  const palette = MOOD_PALETTES[mood] ?? FALLBACK;
  const temper = MOOD_TEMPER[mood] ?? FALLBACK_TEMPER;

  const energy = typeof state?.energy === "number" ? Math.max(0, Math.min(100, state.energy)) : 50;
  const intensity = 0.35 + (energy / 100) * 0.55;

  // Gentle interplay: presence nudges her body-language too. Talking livens
  // her, resting stills her.
  const presenceLife: Record<string, number> = {
    talking: 0.25,
    thinking: 0.12,
    reflecting: 0.04,
    observing: 0.02,
    present: 0,
    resting: -0.08,
    off: -0.05,
  };
  const life = presenceLife[presence.tone] ?? 0;

  const toneMotion: Record<string, number> = {
    talking: 0.85,
    thinking: 0.6,
    reflecting: 0.45,
    observing: 0.3,
    present: 0.25,
    resting: 0.12,
    off: 0.05,
  };
  const motion = Math.max(0, Math.min(1, toneMotion[presence.tone] ?? 0.3 + life));

  // Higher energy breathes a touch faster; deep quiet breathes slow.
  const breath = 9.5 - energy * 0.04 - motion * 1.5;

  // Low energy draws her inward no matter the mood: a drained light folds.
  const fatigue = Math.max(0, (60 - energy) / 60);
  const contract = Math.max(0, Math.min(1, temper.contract + fatigue * 0.45));
  const bloom = Math.max(0, Math.min(1, temper.bloom + (energy / 100) * 0.2 + life * 0.15));
  const tremor = Math.max(0, Math.min(1, temper.tremor + Math.max(0, motion - 0.4) * 0.4));
  const sway = Math.max(0, Math.min(1, temper.sway + life * 0.3));

  const thoughts = state?.carried_thoughts ?? [];
  const motes = thoughts.slice(0, 6).map((t, i) => moteFor(t, i));

  return { palette, intensity, breath, motion, contract, bloom, tremor, sway, motes };
}
