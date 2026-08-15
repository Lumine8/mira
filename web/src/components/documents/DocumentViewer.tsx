import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { fetchDocument, type DocumentDetail } from "../../lib/api";

function authorLabel(author: "founder" | "mira"): string {
  return author === "mira" ? "by Mira" : "given to Mira";
}

/** A paper, opened in a slide-in panel — the way a research review or a
 *  handed-over document is meant to be read: beside the conversation, not in
 *  place of it. */
export default function DocumentViewer({
  name,
  onClose,
}: {
  name: string | null;
  onClose: () => void;
}) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!name) return;
    let cancelled = false;
    setDoc(null);
    setError(null);
    fetchDocument(name)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch((err) => {
        if (!cancelled) setError(`document did not load: ${err}`);
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  return (
    <AnimatePresence>
      {name && (
        <motion.div
          className="docviewer"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
        >
          <button
            className="docviewer__backdrop"
            type="button"
            aria-label="Close document"
            onClick={onClose}
          />
          <motion.aside
            className="docviewer__panel"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            role="dialog"
            aria-label={name}
          >
            <header className="docviewer__head">
              <div className="docviewer__title-wrap">
                <h2 className="docviewer__title">{doc?.name ?? name}</h2>
                {doc && (
                  <span className={`documents__author documents__author--${doc.author}`}>
                    {authorLabel(doc.author)}
                  </span>
                )}
              </div>
              <button className="docviewer__close" type="button" onClick={onClose} aria-label="Close">
                ×
              </button>
            </header>
            <div className="docviewer__body">
              {error && <div className="documents__error">{error}</div>}
              {!error && !doc && <div className="docviewer__loading" aria-label="loading" />}
              {doc && <pre className="documents__page">{doc.content}</pre>}
            </div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
