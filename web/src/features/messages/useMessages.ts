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

export interface DocumentNote {
  name: string;
  author: "founder" | "mira";
  conversationId: number;
}

export function useMessages(accountKey?: string | null) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [active, setActive] = useState<ActiveThread | null>(null);
  const [thinking, setThinking] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [activity, setActivity] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingChanges, setPendingChanges] = useState<PendingChange[]>([]);
  const [changeHistory, setChangeHistory] = useState<PendingChange[]>([]);
  const [currentRequest, setCurrentRequest] = useState<PendingChange | null>(null);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const [consentError, setConsentError] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocumentNote[]>([]);
  const [creatingDocs, setCreatingDocs] = useState<number[]>([]);
  const socketRef = useRef<MiraSocket | null>(null);
  const activeRef = useRef<ActiveThread | null>(null);
  const spokenRef = useRef<string | null>(null);
  const streamingRef = useRef("");

  /** Remember that a document exists for a conversation (a research paper she
   *  just wrote), so its chip stays available even after switching away and
   *  back — and never duplicates. */
  const noteDocument = useCallback((d: DocumentNote) => {
    setDocs((prev) =>
      prev.some((x) => x.name === d.name && x.conversationId === d.conversationId)
        ? prev
        : [...prev, d],
    );
  }, []);

  /** A conversation's research has started being written up — the chat shows
   *  the paper forming until document_created lands. */
  const noteCreating = useCallback((conversationId: number) => {
    setCreatingDocs((prev) =>
      prev.includes(conversationId) ? prev : [...prev, conversationId],
    );
  }, []);

  /** The paper is finished and openable — the forming state gives way to the
   *  chip that opens it. */
  const clearCreating = useCallback((conversationId: number) => {
    setCreatingDocs((prev) => prev.filter((id) => id !== conversationId));
  }, []);

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
    // A different account signed in (or guest mode toggled): nothing the
    // previous account saw may leak over — its threads, its open socket, its
    // pending requests, its documents. Start clean and reload under the new
    // identity. The key is the account (user id / guest), so it only changes
    // on an actual switch, not on re-renders.
    socketRef.current?.close();
    socketRef.current = null;
    activeRef.current = null;
    setConversations([]);
    setActive(null);
    setPendingChanges([]);
    setChangeHistory([]);
    setCurrentRequest(null);
    setResolvingId(null);
    setConsentError(null);
    setDocs([]);
    setCreatingDocs([]);
    setStreaming("");
    streamingRef.current = "";
    setThinking(false);
    setActivity(null);
    setConnected(false);
    setError(null);

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
  }, [reconcilePending, accountKey]);

  const openConversation = useCallback(async (id: number) => {
    socketRef.current?.close();
    setStreaming("");
    streamingRef.current = "";
    setThinking(false);
    setActivity(null);
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
    streamingRef.current = "";
    setThinking(false);
    setActivity(null);
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

  /** Re-sync the open thread from the server. Called when the socket drops and
   *  reconnects, or when a reply that finished while we were away is done. A
   *  reply still streaming on a live socket is left alone. */
  const refreshActive = useCallback(async () => {
    const thread = activeRef.current;
    if (!thread || streamingRef.current) return;
    try {
      const detail = await fetchConversation(thread.id);
      if (activeRef.current?.id !== thread.id) return;
      const next = { id: thread.id, kind: detail.kind, messages: detail.messages };
      activeRef.current = next;
      setActive(next);
    } catch {
      // transient failure; the socket or a later event will resync
    }
  }, []);

  const connectSocket = useCallback((id: number) => {
    const socket = new MiraSocket(wsUrlFor(id), {
      onOpen: () => setConnected(true),
      onReconnect: () => void refreshActive(),
      onClose: () => setConnected(false),
      onEvent: (event) => {
        switch (event.type) {
          case "state":
            setThinking(event.state === "thinking");
            break;
          case "stream_token":
            setStreaming((prev) => {
              const next = prev + event.content;
              streamingRef.current = next;
              return next;
            });
            break;
          case "activity":
            setActivity(event.label);
            setThinking(true);
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
              streamingRef.current = "";
              setActivity(null);
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
  }, [mergePending, refreshActive, speakReply]);

  const send = useCallback(
    (content: string) => {
      const text = content.trim();
      if (!text || !active) return;
      setActivity(null);
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
      setResolvingId(id);
      setConsentError(null);
      try {
        if (approve) {
          await approveChange(id);
        } else {
          await denyChange(id);
        }
        setPendingChanges((prev) => prev.filter((c) => c.id !== id));
        setCurrentRequest((cur) => (cur?.id === id ? null : cur));
        void fetchChangeHistory().then(setChangeHistory).catch(() => undefined);
      } catch (err) {
        // The change may already be resolved elsewhere (approved via the API
        // or in another tab) — re-pull the pending list so the popup reflects
        // the server's truth. If it is still genuinely pending, the request
        // failed for a real reason: tell the user instead of leaving the
        // button silently dead.
        const act = approve ? "approve" : "deny";
        const detail = err instanceof Error ? err.message : String(err);
        try {
          const fresh = await fetchPending();
          reconcilePending(fresh);
          const still = fresh.find((c) => c.id === id)?.status;
          if (still === "pending") {
            setConsentError(`could not ${act}: ${detail}`);
            setError(`could not ${act}: ${detail}`);
          }
        } catch {
          setConsentError(approve ? "could not approve request" : "could not deny request");
          setError(approve ? "could not approve request" : "could not deny request");
        }
      } finally {
        setResolvingId(null);
      }
    },
    [reconcilePending],
  );

  const dismissRequest = useCallback(() => {
    setConsentError(null);
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
    streamingRef.current = "";
    setThinking(false);
    setActivity(null);
  }, []);

  const removeConversation = useCallback(
    async (id: number) => {
      if (active?.id === id) {
        socketRef.current?.close();
        activeRef.current = null;
        setActive(null);
        setStreaming("");
        streamingRef.current = "";
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
    activity,
    connected,
    error,
    pendingChanges,
    changeHistory,
    currentRequest,
    resolvingId,
    consentError,
    openConversation,
    startNew,
    focus,
    leaveThread,
    removeConversation,
    send,
    sendImage,
    refreshActive,
    docs,
    noteDocument,
    creatingDocs,
    noteCreating,
    clearCreating,
    resolveChange,
    dismissRequest,
    injectSelf,
  };
}
