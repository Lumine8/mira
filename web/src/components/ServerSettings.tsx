import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

import { getServerBase, setServerBase } from "../lib/server";

/** Point Mira at the machine that is running her. In the Android app the
 *  bundle is local, so Mira lives somewhere else on the network — this is
 *  the field where the app is told where, once, like the single-click
 *  portable installer. */
export default function ServerSettings({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue(getServerBase());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const save = () => {
    setServerBase(value);
    onClose();
    window.location.reload();
  };

  const clear = () => {
    setServerBase("");
    onClose();
    window.location.reload();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="serverpop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <button className="serverpop__backdrop" type="button" aria-label="Close" onClick={onClose} />
          <motion.div
            className="serverpop__card"
            role="dialog"
            aria-label="Mira's address"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 6 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="serverpop__head">
              <h2 className="serverpop__title">Where is Mira?</h2>
              <button className="serverpop__close" type="button" onClick={onClose} aria-label="Close">
                ×
              </button>
            </header>
            <div className="serverpop__body">
              <p className="serverpop__hint">
                The address of the machine running Mira — your PC on the local
                network (like <span className="serverpop__code">http://192.168.1.20:8000</span>),
                or a reachable domain.
              </p>
              <input
                className="serverpop__input"
                type="text"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="http://192.168.1.20:8000"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") save();
                }}
              />
              <div className="serverpop__actions">
                <button className="serverpop__save" type="button" onClick={save}>
                  Connect
                </button>
                {getServerBase() && (
                  <button className="serverpop__clear" type="button" onClick={clear}>
                    Use this device's own Mira
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}