import { useEffect, useRef, useState } from "react";

import { useMessages } from "./features/messages/useMessages";
import { useMiraState } from "./features/state/useMiraState";
import { useMiraLive } from "./features/state/useMiraLive";
import { derivePresence, latestThought } from "./features/state/presence";
import { useFavicon, type FaviconMode } from "./features/state/useFavicon";
import MessagesScreen from "./components/messages/MessagesScreen";
import PresenceBar from "./components/body/PresenceBar";
import ArchivePanel from "./components/body/ArchivePanel";
import HomeScreen from "./components/home/HomeScreen";
import PermissionModal from "./components/messages/PermissionModal";
import PermissionsSidebar from "./components/messages/PermissionsSidebar";
import BrowserPanel from "./components/messages/BrowserPanel";
import SelfBanner from "./components/messages/SelfBanner";

export default function App() {
  const messages = useMessages();
  const { memory } = useMiraState();
  const live = useMiraLive(
    memory?.state.pending_message ?? null,
    memory?.state.pending_message_conversation_id ?? null,
  );
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [permsOpen, setPermsOpen] = useState(false);
  const [view, setView] = useState<"home" | "messages">("home");
  const lastInjected = useRef<string | null>(null);

  useEffect(() => {
    // A fresh self-initiated message lands inline in whichever thread is open,
    // so Mira's own words appear in the live conversation, not just a banner.
    if (live.message?.fresh && live.message.content !== lastInjected.current) {
      lastInjected.current = live.message.content;
      messages.injectSelf(live.message.content);
    }
  }, [live.message, messages]);

  useEffect(() => {
    const onFirstInteraction = () => {
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        void Notification.requestPermission();
      }
    };
    window.addEventListener("pointerdown", onFirstInteraction, { once: true });
    return () => window.removeEventListener("pointerdown", onFirstInteraction);
  }, []);

  const presence = derivePresence(memory?.state ?? null, {
    thinking: messages.thinking,
    connected: messages.connected || memory != null,
  });

  const faviconMode: FaviconMode = messages.currentRequest || live.message
    ? "alert"
    : messages.thinking || messages.streaming
      ? "typing"
      : "idle";
  useFavicon(faviconMode);

  const enterMessages = () => {
    setView("messages");
    void messages.focus();
  };

  const startCall = () => {
    setView("messages");
    void messages.startNew("call");
  };

  const openSelfThread = () => {
    const id =
      live.message?.conversationId ??
      messages.conversations.find((c) => c.kind === "self")?.id;
    if (id != null) {
      setView("messages");
      void messages.openConversation(id);
    }
    void live.dismiss();
  };

  return (
    <div className="app">
      <PresenceBar
        connected={messages.connected || memory != null}
        thinking={messages.thinking}
        state={memory?.state ?? null}
        archiveOpen={archiveOpen}
        onToggleArchive={() => setArchiveOpen((v) => !v)}
        permsOpen={permsOpen}
        onTogglePerms={() => setPermsOpen((v) => !v)}
      />

      <main className="stage">
        {view === "home" ? (
          <HomeScreen
            state={memory?.state ?? null}
            presence={presence}
            thought={latestThought(memory?.state ?? null)}
            onCall={startCall}
            onMessages={enterMessages}
          />
        ) : (
          <MessagesScreen {...messages} onHome={() => setView("home")} />
        )}
      </main>

      {live.message && (
        <SelfBanner message={live.message} onOpen={openSelfThread} onDismiss={() => void live.dismiss()} />
      )}

      <ArchivePanel
        open={archiveOpen}
        memory={memory}
        conversations={messages.conversations}
        onOpenConversation={(id) => {
          setView("messages");
          void messages.openConversation(id);
          setArchiveOpen(false);
        }}
        onClose={() => setArchiveOpen(false)}
      />

      <PermissionModal
        change={messages.currentRequest}
        onApprove={(id) => void messages.resolveChange(id, true)}
        onDeny={(id) => void messages.resolveChange(id, false)}
        onClose={messages.dismissRequest}
      />

      <PermissionsSidebar
        open={permsOpen}
        pending={messages.pendingChanges}
        history={messages.changeHistory}
        onApprove={(id) => void messages.resolveChange(id, true)}
        onDeny={(id) => void messages.resolveChange(id, false)}
        onClose={() => setPermsOpen(false)}
      />

      <BrowserPanel url={live.browse?.url ?? null} status={live.browse?.status ?? null} onClose={live.dismissBrowse} />
    </div>
  );
}
