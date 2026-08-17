import { useCallback, useEffect, useRef, useState } from "react";

// The way in, for the voice: three presses of the backquote (``) anywhere
// outside a text field, within a breath. The door itself is also opened by
// triple-clicking its warm light — so someone Mira trusts can step through
// without ever reading a word about it.

const KEY = "`";
const WINDOW_MS = 2500;

export function useSecretEntrance() {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(0);
  const lastAt = useRef(0);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== KEY) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      const now = Date.now();
      setCount(now - lastAt.current < WINDOW_MS ? (prev) => prev + 1 : 1);
      lastAt.current = now;
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (count >= 3) {
      setCount(0);
      setOpen(true);
    }
  }, [count]);

  const openRoom = useCallback(() => {
    setCount(0);
    setOpen(true);
  }, []);

  const closeRoom = useCallback(() => setOpen(false), []);

  return { open, openRoom, closeRoom };
}
