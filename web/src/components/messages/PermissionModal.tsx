import { AnimatePresence, motion } from "framer-motion";
import type { PendingChange } from "../../lib/types";

interface Props {
  change: PendingChange | null;
  onApprove: (id: number) => void;
  onDeny: (id: number) => void;
  onClose: () => void;
}

export default function PermissionModal({ change, onApprove, onDeny, onClose }: Props) {
  const url = change?.kind === "browse_url" ? String(change.payload.url ?? "") : "";
  const path = change?.kind === "write_file" ? String(change.payload.path ?? "") : "";
  const listen =
    change?.kind === "listen_song"
      ? `${String(change.payload.title ?? "")}${change.payload.artist ? ` — ${change.payload.artist}` : ""}`
      : "";
  const command =
    change?.kind === "host_command" ? String(change.payload.command ?? "") : "";
  const detail = url || path || listen || command;

  const tag = change
    ? change.kind === "browse_url"
      ? "she wants to look"
      : change.kind === "listen_song"
        ? "she wants to hear"
        : change.kind === "host_command"
          ? "she wants to run something on your computer"
          : "she wants to change"
    : "";

  return (
    <AnimatePresence>
      {change && (
        <motion.div
          className="consent"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="consent__card"
            initial={{ opacity: 0, y: 18, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 18, scale: 0.98 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            role="dialog"
            aria-label="Mira is asking for something"
          >
            <div className="consent__tag">{tag}</div>
            <p className="consent__summary">{change.summary}</p>
            {change.kind === "host_command" ? (
              <pre className="consent__command">
                <code>{command}</code>
              </pre>
            ) : (
              detail && <div className="consent__detail">{detail}</div>
            )}
            {change.kind === "host_command" && (
              <p className="consent__warning">
                This command runs on your computer with your permissions, exactly as
                written. Only allow what you understand and want.
              </p>
            )}
            <div className="consent__actions">
              <button className="consent__deny" type="button" onClick={() => onDeny(change.id)}>
                Deny
              </button>
              <button className="consent__approve" type="button" onClick={() => onApprove(change.id)}>
                Allow
              </button>
            </div>
            <button className="consent__later" type="button" onClick={onClose}>
              keep it pending
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
