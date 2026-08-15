import { derivePresence, type Presence } from "../../features/state/presence";
import type { AuthUser, MiraState } from "../../lib/types";

interface Props {
  connected: boolean;
  thinking: boolean;
  state: MiraState | null;
  archiveOpen: boolean;
  onToggleArchive: () => void;
  permsOpen: boolean;
  onTogglePerms: () => void;
  identity: AuthUser | null;
  isFounder: boolean;
  moderationOpen: boolean;
  onToggleModeration: () => void;
  onOpenSkills: () => void;
  onOpenDocuments: () => void;
  onSignOut: () => void;
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

export default function PresenceBar({ connected, thinking, state, archiveOpen, onToggleArchive, permsOpen, onTogglePerms, identity, isFounder, moderationOpen, onToggleModeration, onOpenSkills, onOpenDocuments, onSignOut }: Props) {
  const presence = derivePresence(state, { thinking, connected });
  const who = identity?.name ? (identity.role === "founder" ? identity.name : identity.name) : "You";
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
        {isFounder && (
          <button
            className={`presence__archive ${moderationOpen ? "presence__archive--open" : ""}`}
            type="button"
            onClick={onToggleModeration}
            title="The door: waitlist, flags, the house"
          >
            The Door
          </button>
        )}
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
        <button
          className="presence__archive"
          type="button"
          onClick={onOpenSkills}
          title="The skills she wrote herself"
        >
          Skills
        </button>
        <button
          className="presence__archive"
          type="button"
          onClick={onOpenDocuments}
          title="Papers you hand her, and papers she writes"
        >
          Papers
        </button>
        <span className="presence__who" title={who}>
          {who}
        </span>
        <button className="presence__archive" type="button" onClick={onSignOut} title="Sign out">
          Leave
        </button>
      </div>
    </header>
  );
}
