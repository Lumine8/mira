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

/** The address the web app talks to. In the desktop/browser case Mira serves
 *  the bundle itself, so relative paths resolve to her. In the Android app the
 *  bundle is local and Mira lives somewhere reachable — the user points the
 *  app at her once, like the single-click portable installer. */
export function getServerBase(): string {
  const stored = localStorage.getItem(SERVER_KEY);
  if (stored) return stored.replace(/\/+$/, "");
  return "";
}

export function getServerConfigured(): boolean {
  return Boolean(getServerBase());
}

export function setServerBase(url: string): void {
  const clean = url.trim().replace(/\/+$/, "");
  if (clean) localStorage.setItem(SERVER_KEY, clean);
  else localStorage.removeItem(SERVER_KEY);
}

/** The origin requests are sent to. Empty = same origin (served by Mira). */
export function apiOrigin(): string {
  return getServerBase();
}