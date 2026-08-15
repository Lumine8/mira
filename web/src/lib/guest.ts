const GUEST_KEY = "mira-guest";
const GUEST_MODE_KEY = "mira-guest-mode";

let cachedFingerprint: string | null = null;

function fingerprint(): string {
  if (cachedFingerprint) return cachedFingerprint;
  const stored = localStorage.getItem(GUEST_KEY);
  if (stored) {
    cachedFingerprint = stored;
    return stored;
  }
  const id =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  localStorage.setItem(GUEST_KEY, id);
  cachedFingerprint = id;
  return id;
}

export function guestId(): string {
  return fingerprint();
}

export function isGuestMode(): boolean {
  return localStorage.getItem(GUEST_MODE_KEY) === "1";
}

export function setGuestMode(on: boolean): void {
  if (on) localStorage.setItem(GUEST_MODE_KEY, "1");
  else localStorage.removeItem(GUEST_MODE_KEY);
}

export function clearGuestId(): void {
  localStorage.removeItem(GUEST_KEY);
  localStorage.removeItem(GUEST_MODE_KEY);
  cachedFingerprint = null;
}