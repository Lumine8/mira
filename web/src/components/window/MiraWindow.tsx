import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { fetchReadablePage } from "../../lib/api";

export type Artifact =
  | { kind: "creating"; conversationId: number }
  | { kind: "browse"; url: string };

function windowTitle(artifact: Artifact): string {
  if (artifact.kind === "creating") return "Mira is writing a paper";
  return "Mira is browsing";
}

/** The window Mira works in — a slide-in panel that shows whatever she is
 *  making: a paper being written, or a page she is reading (fetched as
 *  readable words, not an iframe). Finished papers open as a popup instead. */
export default function MiraWindow({
  artifact,
  onClose,
}: {
  artifact: Artifact | null;
  onClose: () => void;
}) {
  const [page, setPage] = useState<{ title: string; content: string } | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const browseUrl = artifact?.kind === "browse" ? artifact.url : null;

  useEffect(() => {
    if (!browseUrl) return;
    let cancelled = false;
    setPage(null);
    setPageError(null);
    fetchReadablePage(browseUrl)
      .then((p) => {
        if (!cancelled) setPage({ title: p.title, content: p.content });
      })
      .catch((err) => {
        if (!cancelled) setPageError(`page did not load: ${err}`);
      });
    return () => {
      cancelled = true;
    };
  }, [browseUrl]);

  return (
    <AnimatePresence>
      {artifact && (
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
            aria-label="Close window"
            onClick={onClose}
          />
          <motion.aside
            className="docviewer__panel"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            role="dialog"
            aria-label={windowTitle(artifact)}
          >
            <header className="docviewer__head">
              <div className="docviewer__title-wrap">
                <span className="docviewer__kicker">{windowTitle(artifact)}</span>
                {artifact.kind === "browse" && page && (
                  <h2 className="docviewer__title">{page.title}</h2>
                )}
                {artifact.kind === "creating" && (
                  <h2 className="docviewer__title">A paper is forming</h2>
                )}
              </div>
              <button className="docviewer__close" type="button" onClick={onClose} aria-label="Close">
                ×
              </button>
            </header>
            <div className="docviewer__body">
              {artifact.kind === "creating" && (
                <div className="docviewer__creating" role="status">
                  <span className="docviewer__creating-quill" aria-hidden="true" />
                  <p className="docviewer__creating-text">
                    Mira is writing this up as a proper literature review — the
                    search results are in front of her and she is working. The
                    finished paper will appear here the moment she hands it over.
                  </p>
                </div>
              )}

              {artifact.kind === "browse" &&
                (pageError ? (
                  <div className="documents__error">{pageError}</div>
                ) : !page ? (
                  <div className="docviewer__loading" aria-label="loading" />
                ) : (
                  <div className="docviewer__browse">
                    <a
                      className="docviewer__browse-link"
                      href={artifact.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      open the page itself ↗
                    </a>
                    <div className="docviewer__browse-body">{page.content}</div>
                  </div>
                ))}
            </div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}