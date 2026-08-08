import type { PendingChange } from "../../lib/types";

interface Props {
  open: boolean;
  pending: PendingChange[];
  history: PendingChange[];
  onApprove: (id: number) => void;
  onDeny: (id: number) => void;
  onClose: () => void;
}

const KIND_LABEL: Record<string, string> = {
  browse_url: "look",
  listen_song: "hear",
  watch_video: "watch",
  write_file: "change",
  host_command: "run command",
  host_read: "read",
};

function labelFor(change: PendingChange): string {
  return KIND_LABEL[change.kind] ?? change.kind;
}

function summaryFor(change: PendingChange): string {
  if (change.kind === "browse_url") return String(change.payload.url ?? "");
  if (change.kind === "write_file") return String(change.payload.path ?? "");
  if (change.kind === "listen_song")
    return `${String(change.payload.title ?? "")}${change.payload.artist ? ` — ${change.payload.artist}` : ""}`;
  if (change.kind === "host_command") return String(change.payload.command ?? "");
  if (change.kind === "host_read") return String(change.payload.path ?? "");
  return change.summary;
}

export default function PermissionsSidebar({ open, pending, history, onApprove, onDeny, onClose }: Props) {
  return (
    <aside className={`perms ${open ? "perms--open" : ""}`} aria-hidden={!open}>
      <header className="perms__head">
        <h2>Consent</h2>
        <span className="perms__count">{pending.length} waiting</span>
        <button className="perms__close" type="button" onClick={onClose} aria-label="Close consent">
          ×
        </button>
      </header>

      {pending.length === 0 && (
        <p className="perms__empty">
          Nothing waiting on you. She asks only when she wants to act.
        </p>
      )}

      <ul className="perms__list">
        {pending.map((c) => (
          <li key={c.id} className="perms__card">
            <span className="perms__tag">she wants to {labelFor(c)}</span>
            <p className="perms__summary">{c.summary}</p>
            <p className="perms__detail">{summaryFor(c)}</p>
            <div className="perms__actions">
              <button
                className="perms__deny"
                type="button"
                onClick={() => onDeny(c.id)}
              >
                Deny
              </button>
              <button
                className="perms__approve"
                type="button"
                onClick={() => onApprove(c.id)}
              >
                Allow
              </button>
            </div>
          </li>
        ))}
      </ul>

      {history.length > 0 && (
        <section className="perms__recent">
          <h3>Recently</h3>
          <ul className="perms__recent-list">
            {history.slice(0, 8).map((c) => (
              <li key={c.id} className={`perms__recent-row perms__recent-row--${c.status}`}>
                <span className="perms__moat">{labelFor(c)}</span>
                <span className="perms__recent-status">{c.status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}