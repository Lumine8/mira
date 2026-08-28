const SERVER_KEY = "mira-server-base";

declare global {
  interface Window {
    Capacitor?: { isNativePlatform?: () => boolean };
  }
}

/** True when running inside the Capacitor Android wrapper (vs a browser
 *  served by the backend same-origin). */
export function isNative(): boolean {
  return Boolean(window.Capacitor?.isNativePlatform?.());
}

/** The address the web app talks to. On native, the backend runs locally
 *  on the device (no PC needed). In the desktop/browser case Mira serves
 *  the bundle itself, so relative paths resolve to her. */
export function getServerBase(): string {
  if (isNative()) {
    // Backend runs locally inside the APK on port 8000
    return "http://127.0.0.1:8000";
  }
  const stored = localStorage.getItem(SERVER_KEY);
  if (stored) return stored.replace(/\/+$/, "");
  return "";
}

export function getServerConfigured(): boolean {
  return isNative() || Boolean(getServerBase());
}

export function setServerBase(url: string): void {
  const clean = url.trim().replace(/\/+$/, "");
  if (clean) localStorage.setItem(SERVER_KEY, clean);
  else localStorage.removeItem(SERVER_KEY);
}

/** The origin requests are sent to. Priority: localStorage override >
 *  build-time VITE_API_BASE (Render/cloud deploys) > empty (same origin,
 *  served by Mira desktop or local dev). */
export function apiOrigin(): string {
  const local = getServerBase();
  if (local) return local;
  const buildTime = (import.meta as any).env?.VITE_API_BASE as string | undefined;
  return buildTime ?? "";
}
