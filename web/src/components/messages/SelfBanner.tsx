import type { LiveSelfMessage } from "../../features/state/useMiraLive";

interface Props {
  message: LiveSelfMessage;
  onOpen: () => void;
  onDismiss: () => void;
}

export default function SelfBanner({ message, onOpen, onDismiss }: Props) {
  return (
    <div className="self-banner">
      <span className="self-banner__tag">{message.fresh ? "she just spoke" : "kept for you"}</span>
      <p className="self-banner__text">{message.content}</p>
      <div className="self-banner__actions">
        <button type="button" className="self-banner__open" onClick={onOpen}>
          Open where she said it
        </button>
        <button type="button" className="self-banner__dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
