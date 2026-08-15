import { useCallback, useEffect, useState } from "react";

import { fetchMotePresence } from "../../lib/api";
import type { MotePresence } from "../../lib/types";

/**
 * Mote — the tiny quiet presence beside Mira. Polls her felt state (mood,
 * energy) and the last sign Mote made, so the UI can breathe with it in real
 * time. Deliberately separate from the mind loop: Mote has no brain, only her
 * felt state.
 */
export function useMote(enabled: boolean) {
  const [mote, setMote] = useState<MotePresence | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      setMote(await fetchMotePresence());
    } catch {
      // server unreachable; the next poll will resurface it
    }
  }, [enabled]);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30000);
    return () => clearInterval(id);
  }, [refresh]);

  return { mote, refresh };
}