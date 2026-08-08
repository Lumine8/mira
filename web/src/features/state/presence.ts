import type { MiraState } from "../../lib/types";

export type PresenceTone =
  | "talking"
  | "thinking"
  | "reflecting"
  | "observing"
  | "present"
  | "resting"
  | "off";

export interface Presence {
  label: string;
  level: number; // 0..1, drives the segmented fill
  tone: PresenceTone;
  caption: string;
}

/**
 * Derive Mira's *presence* from her actual inner state — not a CPU meter,
 * not an "online" badge. The UI reads how she is, not whether her process
 * is up.
 */
export function derivePresence(
  state: MiraState | null,
  opts: { thinking: boolean; connected: boolean },
): Presence {
  if (!opts.connected) {
    return { label: "Gone quiet", level: 0.05, tone: "off", caption: "She can't be reached right now." };
  }
  if (opts.thinking) {
    return { label: "Talking", level: 1, tone: "talking", caption: "She's listening — speak to her." };
  }

  const now = Date.now();
  const last = state?.last_reflection_at ? Date.parse(state.last_reflection_at) : 0;
  const mins = last ? (now - last) / 60000 : Infinity;

  if (last && mins < 25) {
    return { label: "Reflecting", level: 0.8, tone: "reflecting", caption: "Reviewing today's conversations." };
  }
  if (last && mins < 90) {
    return { label: "Observing", level: 0.4, tone: "observing", caption: "Watching the rain." };
  }
  if (typeof state?.energy === "number" && state.energy < 35 && !last) {
    return { label: "Resting", level: 0.2, tone: "resting", caption: "Sleeping lightly." };
  }
  return { label: "Present", level: 0.25, tone: "present", caption: "Reading through old thoughts." };
}

/** The thought she is carrying right now, for "I've been thinking…" */
export function latestThought(state: MiraState | null): string | null {
  if (!state) return null;
  if (state.carried_thoughts.length > 0) return state.carried_thoughts[0];
  if (state.last_conversation_summary) return state.last_conversation_summary;
  return null;
}
