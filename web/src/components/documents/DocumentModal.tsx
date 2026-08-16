import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { downloadDocument, fetchDocument, type DocumentDetail } from "../../lib/api";
import { dateLabel, renderBlocks, splitPaper } from "../../lib/markdown";

const FORMATS = [
  { id: "md", label: "Markdown" },
  { id: "docx", label: "Word" },
  { id: "pdf", label: "PDF" },
] as const;

/** A finished paper, opened as a popup — her review rendered like a page, with
 *  the references/sources she cited, and downloads as Markdown, Word, or PDF. */
export default function DocumentModal({
  name,
  onClose,
}: {
  name: string | null;
  onClose: () => void;
}) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<"md" | "docx" | "pdf" | null>(null);

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
        if (!cancelled) setError(`the paper did not load: ${err}`);
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  useEffect(() => {
    if (!name) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [name, onClose]);

  const paper = useMemo(() => {
    if (!doc) return null;
    return splitPaper(doc.content, doc.name, doc.author);
  }, [doc]);

  const save = useCallback(
    async (format: "md" | "docx" | "pdf") => {
      if (!name) return;
      setSaving(format);
      try {
        await downloadDocument(name, format);
      } finally {
        setSaving(null);
      }
    },
    [name],
  );

  return (
    <AnimatePresence>
      {name && (
        <motion.div
          className="docpop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <button className="docpop__backdrop" type="button" aria-label="Close paper" onClick={onClose} />
          <motion.div
            className="docpop__card"
            role="dialog"
            aria-label="Paper"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 6 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="docpop__head">
              <div className="docpop__actions">
                {FORMATS.map((f) => (
                  <button
                    key={f.id}
                    className="docpop__download"
                    type="button"
                    disabled={saving !== null}
                    onClick={() => void save(f.id)}
                  >
                    {saving === f.id ? "Saving…" : `Download ${f.label}`}
                  </button>
                ))}
              </div>
              <button className="docpop__close" type="button" onClick={onClose} aria-label="Close">
                ×
              </button>
            </header>
            <div className="docpop__body">
              {error ? (
                <div className="documents__error">{error}</div>
              ) : !doc || !paper ? (
                <div className="docviewer__loading" aria-label="loading" />
              ) : (
                <article className="docpop__paper">
                  <header className="docpop__paper-head">
                    <span className="docpop__paper-kicker">Paper</span>
                    <h1 className="docpop__paper-title">{paper.title}</h1>
                    <p className="docpop__paper-byline">
                      {paper.byline} · {dateLabel(doc.modified_at)}
                    </p>
                  </header>
                  <div className="docpop__paper-body">{renderBlocks(paper.body)}</div>
                </article>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}