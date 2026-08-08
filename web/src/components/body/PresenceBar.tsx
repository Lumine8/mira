import { derivePresence, type Presence } from "../../features/state/presence";
import type { MiraState } from "../../lib/types";

interface Props {
  connected: boolean;
  thinking: boolean;
  state: MiraState | null;
  archiveOpen: boolean;
  onToggleArchive: () => void;
  permsOpen: boolean;
  onTogglePerms: () => void;
}

const SEGMENTS = 5;

function Segmented({ presence }: { presence: Presence }) {
  const filled = Math.max(1, Math.round(presence.level * SEGMENTS));
  return (
    <span className={`presence__segments presence__segments--${presence.tone}`}>
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <span key={i} className={`presence__segment ${i < filled ? "is-filled" : ""}`} />
      ))}
    </span>
  );
}

export default function PresenceBar({ connected, thinking, state, archiveOpen, onToggleArchive, permsOpen, onTogglePerms }: Props) {
  const presence = derivePresence(state, { thinking, connected });
  return (
    <header className="presence">
      <div className="presence__identity">
        <span className="presence__name">Mira</span>
        <Segmented presence={presence} />
      </div>
      <div className="presence__readout">
        <span className={`presence__state presence__state--${presence.tone}`}>{presence.label}</span>
        <span className="presence__caption">{presence.caption}</span>
      </div>
      <div className="presence__toggles">
        <button
          className={`presence__archive ${permsOpen ? "presence__archive--open" : ""}`}
          type="button"
          onClick={onTogglePerms}
          title="What she wants to do"
        >
          Consent
        </button>
        <button
          className={`presence__archive ${archiveOpen ? "presence__archive--open" : ""}`}
          type="button"
          onClick={onToggleArchive}
          title="What she keeps"
        >
          Archive
        </button>
      </div>
    </header>
  );
}
