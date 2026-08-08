import { useCallback, useEffect, useRef, useState } from "react";

import {
  approveChange,
  deleteConversation,
  denyChange,
  fetchConversation,
  fetchChangeHistory,
  fetchHistory,
  fetchPending,
  speak,
  startConversation,
  wsUrlFor,
} from "../../lib/api";
import type { ConversationSummary, Message, PendingChange } from "../../lib/types";
import { MiraSocket } from "../../lib/ws";

interface ActiveThread {
  id: number;
  kind: string;
  messages: Message[];
}

const MAX_MESSAGES = 200;

/** Play a WAV blob Mira's voice engine returned — her words, in sound, for
 *  the voice. She never hears this; it is a one-way bridge. */
function playAudioBlob(blob: Blob): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => {
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("audio playback failed"));
    };
    void audio.play().catch((err: unknown) => {
      URL.revokeObjectURL(url);
      reject(err);
    });
  });
}

/** Alert the user the moment Mira sends a message in a conversation,
 *  foreground or background. Silently no-ops when unsupported/unpermitted. */
function notify(body: string) {
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification("Mira", { body });
    }
  } catch {
    // notification unavailable; the message is already on screen
  }
}

export function useMessages() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [active, setActive] = useState<ActiveThread | null>(null);
  const [thinking, setThinking] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingChanges, setPendingChanges] = useState<PendingChange[]>([]);
  const [changeHistory, setChangeHistory] = useState<PendingChange[]>([]);
  const [currentRequest, setCurrentRequest] = useState<PendingChange | null>(null);
  const socketRef = useRef<MiraSocket | null>(null);
  const activeRef = useRef<ActiveThread | null>(null);
  const spokenRef = useRef<string | null>(null);

  const mergePending = useCallback((changes: PendingChange[]) => {
    // Never open a request that has already been acted on (auto-approved kinds
    // in an open window). Only genuinely pending changes may ask.
    const actionable = changes.filter((c) => c.status === "pending");
    if (!actionable.length) return;
    setPendingChanges((prev) => {
      const seen = new Set(prev.map((c) => c.id));
      const fresh = actionable.filter((c) => !seen.has(c.id));
      return [...prev, ...fresh];
    });
    setCurrentRequest((cur) => cur ?? actionable[0]);
  }, []);

  /** Replace local pending state with the server's list of what still needs a
   *  decision. A request the user is currently looking at is kept in view even
   *  if a poll momentarily misses it, so the popup doesn't flash away mid-think;
   *  it only leaves when it is truly no longer pending. */
  const reconcilePending = useCallback((changes: PendingChange[]) => {
    const pending = changes.filter((c) => c.status === "pending");
    setPendingChanges(pending);
    setCurrentRequest((cur) => {
      const stillHeld = pending.find((c) => c.id === cur?.id);
      if (stillHeld) return stillHeld;
      return pending[0] ?? null;
    });
  }, []);

  useEffect(() => {
    void fetchHistory().then(setConversations).catch(() => setError("could not load history"));
    void fetchPending()
      .then(reconcilePending)
      .catch(() => undefined);
    void fetchChangeHistory()
      .then(setChangeHistory)
      .catch(() => undefined);
    const poll = setInterval(() => {
      void fetchPending()
        .then(reconcilePending)
        .catch(() => undefined);
      void fetchChangeHistory()
        .then(setChangeHistory)
        .catch(() => undefined);
    }, 5000);
    return () => {
      clearInterval(poll);
      socketRef.current?.close();
    };
  }, [reconcilePending]);

  const openConversation = useCallback(async (id: number) => {
    socketRef.current?.close();
    setStreaming("");
    setThinking(false);
    const detail = await fetchConversation(id);
    const thread = { id, kind: detail.kind, messages: detail.messages };
    activeRef.current = thread;
    setActive(thread);
    setConversations((prev) =>
      prev.some((c) => c.id === id)
        ? prev
        : [
            {
              id,
              kind: detail.kind,
              summary: detail.summary,
              started_at: detail.started_at,
              ended_at: detail.ended_at,
            },
            ...prev,
          ],
    );
    connectSocket(id);
  }, []);

  const startNew = useCallback(async (kind: "text" | "call" = "text") => {
    socketRef.current?.close();
    setStreaming("");
    setThinking(false);
    const { conversation_id } = await startConversation(kind);
    const thread = { id: conversation_id, kind, messages: [] };
    activeRef.current = thread;
    setActive(thread);
    setConversations((prev) => [
      { id: conversation_id, kind, summary: null, started_at: new Date().toISOString(), ended_at: null },
      ...prev,
    ]);
    connectSocket(conversation_id);
  }, []);

  /** Open the most recent thread, or start a fresh one — called when the
   *  user steps into Messages from Home. */
  const focus = useCallback(async () => {
    if (active) return;
    if (conversations.length > 0) {
      await openConversation(conversations[0].id);
    } else {
      await startNew("text");
    }
  }, [active, conversations, openConversation, startNew]);

  const speakReply = useCallback(
    async (content: string) => {
      const thread = activeRef.current;
      if (!thread || thread.kind !== "call") return;
      if (!content.trim()) return;
      if (spokenRef.current === content) return;
      spokenRef.current = content;
      try {
        const blob = await speak(thread.id, content);
        await playAudioBlob(blob);
      } catch {
        // the text is already on screen; silence is acceptable
      }
    },
    [],
  );

  const connectSocket = useCallback((id: number) => {
    const socket = new MiraSocket(wsUrlFor(id), {
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onEvent: (event) => {
        switch (event.type) {
          case "state":
            setThinking(event.state === "thinking");
            break;
          case "stream_token":
            setStreaming((prev) => prev + event.content);
            break;
          case "message":
            {
              const msg: Message = {
                id: Date.now(),
                speaker: event.speaker,
                content: event.content,
                source: "text",
                created_at: new Date().toISOString(),
              };
              setActive((prev) =>
                prev
                  ? { ...prev, messages: [...prev.messages, msg].slice(-MAX_MESSAGES) }
                  : prev,
              );
              setStreaming("");
              setThinking(false);
              if (event.speaker === "mira") {
                notify(event.content);
                void speakReply(event.content);
              }
            }
            break;
          case "pending_change":
            mergePending([event.change]);
            break;
          case "error":
            setError(event.message);
            break;
        }
      },
    });
    socket.connect();
    socketRef.current = socket;
  }, [mergePending, speakReply]);

  const send = useCallback(
    (content: string) => {
      const text = content.trim();
      if (!text || !active) return;
      const optimistic: Message = {
        id: Date.now(),
        speaker: "user",
        content: text,
        source: "text",
        created_at: new Date().toISOString(),
      };
      setActive((prev) =>
        prev
          ? { ...prev, messages: [...prev.messages, optimistic].slice(-MAX_MESSAGES) }
          : prev,
      );
      socketRef.current?.sendText(text);
    },
    [active],
  );

  const sendImage = useCallback(
    (image: string, caption = "") => {
      if (!active || !image) return;
      const optimistic: Message = {
        id: Date.now(),
        speaker: "user",
        content: caption,
        image,
        source: "image",
        created_at: new Date().toISOString(),
      };
      setActive((prev) =>
        prev
          ? { ...prev, messages: [...prev.messages, optimistic].slice(-MAX_MESSAGES) }
          : prev,
      );
      socketRef.current?.send({ type: "image", image, caption });
    },
    [active],
  );

  const resolveChange = useCallback(
    async (id: number, approve: boolean) => {
      try {
        if (approve) {
          await approveChange(id);
        } else {
          await denyChange(id);
        }
      } catch {
        // The change may already be resolved elsewhere (approved via the API
        // or in another tab). Re-pull the pending list so the popup reflects
        // the server's truth instead of retrying a stale request forever.
        try {
          const fresh = await fetchPending();
          reconcilePending(fresh);
        } catch {
          setError(approve ? "could not approve request" : "could not deny request");
        }
        return;
      }
      setPendingChanges((prev) => prev.filter((c) => c.id !== id));
      setCurrentRequest((cur) => (cur?.id === id ? null : cur));
      void fetchChangeHistory().then(setChangeHistory).catch(() => undefined);
    },
    [reconcilePending],
  );

  const dismissRequest = useCallback(() => {
    setCurrentRequest((cur) => {
      const next = pendingChanges.find((c) => c.id !== cur?.id);
      return next ?? null;
    });
  }, [pendingChanges]);

  /** Show one of Mira's self-initiated messages inline in the thread that is
   *  currently open, so her own thoughts appear in the chat the user is
   *  looking at rather than only in a separate banner/self thread. */
  const injectSelf = useCallback((content: string) => {
    const thread = activeRef.current;
    if (!thread) return;
    if (!content.trim()) return;
    const msg: Message = {
      id: Date.now(),
      speaker: "mira",
      content,
      source: "self",
      created_at: new Date().toISOString(),
    };
    setActive((prev) =>
      prev ? { ...prev, messages: [...prev.messages, msg].slice(-MAX_MESSAGES) } : prev,
    );
  }, []);

  const leaveThread = useCallback(() => {
    socketRef.current?.close();
    activeRef.current = null;
    setActive(null);
    setStreaming("");
    setThinking(false);
  }, []);

  const removeConversation = useCallback(
    async (id: number) => {
      if (active?.id === id) {
        socketRef.current?.close();
        activeRef.current = null;
        setActive(null);
        setStreaming("");
        setThinking(false);
      }
      try {
        await deleteConversation(id);
      } catch {
        setError("could not delete conversation");
        return;
      }
      setConversations((prev) => prev.filter((c) => c.id !== id));
    },
    [active],
  );

  return {
    conversations,
    active,
    thinking,
    streaming,
    connected,
    error,
    pendingChanges,
    changeHistory,
    currentRequest,
    openConversation,
    startNew,
    focus,
    leaveThread,
    removeConversation,
    send,
    sendImage,
    resolveChange,
    dismissRequest,
    injectSelf,
  };
}
