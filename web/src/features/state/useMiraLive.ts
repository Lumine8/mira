import { useCallback, useEffect, useRef, useState } from "react";

import { acknowledge, liveWsUrl } from "../../lib/api";
import { MiraSocket } from "../../lib/ws";

export interface LiveSelfMessage {
  content: string;
  conversationId: number | null;
  fresh: boolean;
}

export interface BrowseActivity {
  url: string;
  status: string;
  changeId: number;
}

/** Fire a browser notification for a message Mira sent, whenever it happens —
 *  in the foreground or background. Silently no-ops if notifications are
 *  unsupported or not permitted. */
function notify(body: string) {
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification("Mira", { body });
    }
  } catch {
    // notification unavailable; the banner still shows
  }
}

export function useMiraLive(pendingMessage: string | null, pendingConversationId: number | null) {
  const [live, setLive] = useState<LiveSelfMessage | null>(null);
  const [browse, setBrowse] = useState<BrowseActivity | null>(null);
  const [replyEvent, setReplyEvent] = useState<{ conversationId: number; nonce: number } | null>(null);
  const [documentEvent, setDocumentEvent] = useState<{
    name: string;
    author: "founder" | "mira";
    conversationId: number;
    nonce: number;
  } | null>(null);
  const [creatingEvent, setCreatingEvent] = useState<{ conversationId: number; nonce: number } | null>(null);
  const dismissedContent = useRef<string | null>(null);

  useEffect(() => {
    const socket = new MiraSocket(liveWsUrl(), {
      onEvent: (event) => {
        if (event.type === "self_message") {
          setLive({ content: event.content, conversationId: event.conversation_id, fresh: true });
          notify(event.content);
        } else if (event.type === "browse_activity") {
          setBrowse({ url: event.url, status: event.status, changeId: event.change_id });
        } else if (event.type === "conversation_reply") {
          setReplyEvent({ conversationId: event.conversation_id, nonce: Date.now() });
        } else if (event.type === "document_created") {
          setDocumentEvent({
            name: event.name,
            author: event.author,
            conversationId: event.conversation_id,
            nonce: Date.now(),
          });
        } else if (event.type === "document_creating") {
          setCreatingEvent({ conversationId: event.conversation_id, nonce: Date.now() });
        }
      },
    });
    socket.connect();
    return () => socket.close();
  }, []);

  // A dismissed fallback message must stay dismissed even while the 15s poll
  // still reports the stale pending_message; only a genuinely new message
  // (or none at all) changes the fallback shown.
  const message: LiveSelfMessage | null =
    live ??
    (pendingMessage && pendingMessage !== dismissedContent.current
      ? { content: pendingMessage, conversationId: pendingConversationId, fresh: false }
      : null);

  const dismiss = useCallback(async () => {
    try {
      await acknowledge();
    } catch {
      // server unreachable; the poll will resurface it
    }
    dismissedContent.current = message?.content ?? null;
    setLive(null);
  }, [message]);

  const dismissBrowse = useCallback(() => {
    setBrowse(null);
  }, []);

  return { message, dismiss, browse, dismissBrowse, replyEvent, documentEvent, creatingEvent };
}
