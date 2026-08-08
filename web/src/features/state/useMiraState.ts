import { useCallback, useEffect, useState } from "react";
import { fetchMemory } from "../../lib/api";
import type { MiraMemory } from "../../lib/types";

export function useMiraState() {
  const [memory, setMemory] = useState<MiraMemory | null>(null);

  const refresh = useCallback(async () => {
    try {
      setMemory(await fetchMemory());
    } catch {
      setMemory(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 15000);
    return () => clearInterval(id);
  }, [refresh]);

  return { memory, refresh };
}
