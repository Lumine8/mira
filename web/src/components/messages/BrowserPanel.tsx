import { AnimatePresence, motion } from "framer-motion";
import { getAccessToken } from "../../lib/token";

interface Props {
  url: string | null;
  status: string | null;
  onClose: () => void;
}

export default function BrowserPanel({ url, status, onClose }: Props) {
  const token = getAccessToken();
  const frameSrc = url
    ? `/mira/browse/view?url=${encodeURIComponent(url)}${token ? `&token=${encodeURIComponent(token)}` : ""}`
    : "";
  return (
    <AnimatePresence>
      {url && (
        <motion.div
          className="browser"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 24 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
        >
          <div className="browser__bar">
            <div className="browser__dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="browser__url" title={url}>
              {url}
            </div>
            <div className="browser__status">{status === "pending" ? "she wants to look" : "she is looking"}</div>
            <button className="browser__close" type="button" onClick={onClose} aria-label="close browser">
              ×
            </button>
          </div>
          <iframe
            className="browser__frame"
            src={frameSrc}
            sandbox="allow-scripts allow-same-origin allow-forms"
            referrerPolicy="no-referrer"
            title={`Mira is browsing ${url}`}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
