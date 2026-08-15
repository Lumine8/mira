import { useCallback, useEffect, useState } from "react";

import { fetchAuthConfig, fetchMe, logout as apiLogout } from "../../lib/api";
import { clearGuestId, isGuestMode, setGuestMode } from "../../lib/guest";
import { clearAccessToken, getAccessToken, setAccessToken } from "../../lib/token";
import type { AuthConfig, AuthUser } from "../../lib/types";

export type SessionMode = "loading" | "none" | "user" | "guest";

export interface Session {
  mode: SessionMode;
  config: AuthConfig | null;
  identity: AuthUser | null;
  /** The lock: this account was banned (no warnings, no second chances). */
  banned: boolean;
  bannedReason: string | null;
  authError: string | null;
  signInWithToken: (token: string) => void;
  startGuest: () => void;
  signOut: () => Promise<void>;
  clearAuthError: () => void;
}

const UNAUTHORIZED_EVENT = "mira:unauthorized";

export function useSession(): Session {
  const [mode, setMode] = useState<SessionMode>("loading");
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [identity, setIdentity] = useState<AuthUser | null>(null);
  const [banned, setBanned] = useState(false);
  const [bannedReason, setBannedReason] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  const loadIdentity = useCallback(() => {
    void fetchMe()
      .then((id) => {
        setBanned(false);
        setIdentity(id);
      })
      .catch(() => undefined);
  }, []);

  const signInWithToken = useCallback(
    (token: string) => {
      setAccessToken(token);
      setGuestMode(false);
      setIdentity(null);
      setBanned(false);
      setBannedReason(null);
      setAuthError(null);
      setMode("user");
      loadIdentity();
    },
    [loadIdentity],
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      let cfg: AuthConfig | null = null;
      try {
        cfg = await fetchAuthConfig();
      } catch {
        cfg = null;
      }
      if (cancelled) return;
      setConfig(cfg);

      if (getAccessToken()) {
        setMode("user");
        loadIdentity();
        return;
      }

      // No auth configured and guest mode off (local dev): the backend treats
      // everyone as the founder — go straight in, no sign-in screen.
      if (cfg && !cfg.auth_required && !cfg.guest_mode_enabled) {
        setMode("user");
        loadIdentity();
        return;
      }

      if (cfg?.guest_mode_enabled && isGuestMode()) {
        setMode("guest");
        loadIdentity();
        return;
      }

      setMode("none");
    })();

    return () => {
      cancelled = true;
    };
  }, [loadIdentity]);

  const startGuest = useCallback(() => {
    clearAccessToken();
    setGuestMode(true);
    setIdentity(null);
    setBanned(false);
    setBannedReason(null);
    setAuthError(null);
    setMode("guest");
    loadIdentity();
  }, [loadIdentity]);

  const signOut = useCallback(async () => {
    await apiLogout();
    clearAccessToken();
    setGuestMode(false);
    clearGuestId();
    setIdentity(null);
    setBanned(false);
    setBannedReason(null);
    setMode("none");
  }, []);

  const clearAuthError = useCallback(() => setAuthError(null), []);

  // A 401 anywhere (expired/revoked token) drops back to the sign-in screen.
  useEffect(() => {
    const onUnauthorized = () => {
      clearAccessToken();
      setGuestMode(false);
      setIdentity(null);
      setBanned(false);
      setMode("none");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  return {
    mode,
    config,
    identity,
    banned,
    bannedReason,
    authError,
    signInWithToken,
    startGuest,
    signOut,
    clearAuthError,
  };
}