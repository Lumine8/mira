const STORAGE_KEY = "mira-access-token";

export function getAccessToken(): string {
  return localStorage.getItem(STORAGE_KEY) || "";
}

/** Read the token from the URL (?token=) once and persist it, so a shared
 *  deploy link like https://mira.example.com?token=secret "logs in" the client
 *  without a separate auth screen. Returns the stored token. */
export function initAccessTokenFromUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = (params.get("token") || "").trim();
  if (fromUrl && fromUrl !== localStorage.getItem(STORAGE_KEY)) {
    localStorage.setItem(STORAGE_KEY, fromUrl);
    cleanUrl();
  }
  return getAccessToken();
}

export function setAccessToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token.trim());
}

export function clearAccessToken(): void {
  localStorage.removeItem(STORAGE_KEY);
}

function cleanUrl(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete("token");
  window.history.replaceState({}, document.title, url.toString());
}
