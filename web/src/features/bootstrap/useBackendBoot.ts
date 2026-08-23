import { useEffect, useState } from "react";
import { isNative } from "../lib/server";

type BootState = "idle" | "starting" | "ready" | "error";

/**
 * On native (Capacitor), starts the embedded Python backend and polls
 * until it responds.  On desktop/browser, this is a no-op (the backend
 * is already running externally).
 */
export function useBackendBoot() {
  const [state, setState] = useState<BootState>(() =>
    isNative() ? "starting" : "ready",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isNative()) return;

    let cancelled = false;
    let retries = 0;
    const MAX_RETRIES = 60; // 30 seconds max

    async function boot() {
      try {
        // Dynamically import Capacitor plugins
        const { registerPlugin } = await import("@capacitor/core");
        const PythonServer = registerPlugin<{
          start: (opts: { dataDir?: string; port?: number }) => Promise<{
            status: string;
            port?: number;
          }>;
          stop: () => Promise<{ status: string }>;
          status: () => Promise<{ running: boolean }>;
        }>("PythonServer");

        // Check if already running
        const st = await PythonServer.status();
        if (cancelled) return;
        if (st.running) {
          setState("ready");
          return;
        }

        // Start the backend
        await PythonServer.start({ port: 8000 });
        if (cancelled) return;

        // Poll until the backend is responsive
        while (retries < MAX_RETRIES && !cancelled) {
          await new Promise((r) => setTimeout(r, 500));
          retries++;
          try {
            const resp = await fetch("http://127.0.0.1:8000/mira/system", {
              signal: AbortSignal.timeout(2000),
            });
            if (resp.ok) {
              if (!cancelled) setState("ready");
              return;
            }
          } catch {
            // not ready yet
          }
        }
        if (!cancelled) {
          setError("Backend did not start in time");
          setState("error");
        }
      } catch (e: unknown) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setState("error");
        }
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return { state, error };
}
