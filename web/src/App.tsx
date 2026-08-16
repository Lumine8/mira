import { useEffect, useRef, useState } from "react";

import { useMessages } from "./features/messages/useMessages";
import { useMiraState } from "./features/state/useMiraState";
import { useMiraLive } from "./features/state/useMiraLive";
import { derivePresence, latestThought } from "./features/state/presence";
import { useFavicon, type FaviconMode } from "./features/state/useFavicon";
import { useSession } from "./features/session/useSession";
import { useMote } from "./features/mote/useMote";
import MessagesScreen from "./components/messages/MessagesScreen";
import PresenceBar from "./components/body/PresenceBar";
import ArchivePanel from "./components/body/ArchivePanel";
import HomeScreen from "./components/home/HomeScreen";
import PermissionModal from "./components/messages/PermissionModal";
import PermissionsSidebar from "./components/messages/PermissionsSidebar";
import SelfBanner from "./components/messages/SelfBanner";
import MiraWindow, { type Artifact } from "./components/window/MiraWindow";
import AuthScreen from "./components/auth/AuthScreen";
import ModerationModal from "./components/moderation/ModerationModal";
import MotePresence from "./components/mote/MotePresence";
import SkillsScreen from "./components/skills/SkillsScreen";
import DocumentsScreen from "./components/documents/DocumentsScreen";
import DocumentModal from "./components/documents/DocumentModal";

export default function App() {
  const session = useSession();
  // The account keyed by signed-in user (or guest), so switching accounts
  // reloads all account-scoped state instead of showing the previous one's.
  const accountKey =
    session.mode === "user"
      ? `user:${session.identity?.id ?? ""}`
      : session.mode === "guest"
        ? "guest"
        : null;
  const messages = useMessages(accountKey);
  const { memory } = useMiraState();
  const live = useMiraLive(
    memory?.state.pending_message ?? null,
    memory?.state.pending_message_conversation_id ?? null,
  );
  const { mote } = useMote(session.mode === "user" || session.mode === "guest");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [permsOpen, setPermsOpen] = useState(false);
  const [moderationOpen, setModerationOpen] = useState(false);
  const [view, setView] = useState<"home" | "messages" | "skills" | "documents">("home");
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
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
    // A reply that finished in the background (e.g. while the conversation
    // socket was closed) is now persisted — pull it in if it belongs to the
    // thread currently open.
    if (live.replyEvent && messages.active?.id === live.replyEvent.conversationId) {
      void messages.refreshActive();
    }
  }, [live.replyEvent, messages]);

  useEffect(() => {
    // A research run finished and left a paper on her shelf — remember it so a
    // chip appears in the thread that produced it, and open the finished paper
    // as a popup (closing the "forming" window if it is open).
    if (live.documentEvent) {
      const docEvent = live.documentEvent;
      messages.clearCreating(docEvent.conversationId);
      messages.noteDocument({
        name: docEvent.name,
        author: docEvent.author,
        conversationId: docEvent.conversationId,
      });
      setArtifact(null);
      setOpenDoc(docEvent.name);
    }
  }, [live.documentEvent, messages]);

  useEffect(() => {
    // She started writing a research paper — open the window to watch it form,
    // and show the creation in the thread too.
    if (live.creatingEvent) {
      messages.noteCreating(live.creatingEvent.conversationId);
      setArtifact({ kind: "creating", conversationId: live.creatingEvent.conversationId });
    }
  }, [live.creatingEvent, messages]);

  useEffect(() => {
    // She is looking at a page — the window shows what she is reading as
    // words, unless a finished paper is already open as a popup.
    if (live.browse && !openDoc) {
      setArtifact({ kind: "browse", url: live.browse.url });
    }
  }, [live.browse, openDoc]);

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

  if (session.mode === "loading") {
    return (
      <div className="app">
        <div className="auth">
          <div className="auth__card">
            <div className="auth__loading" aria-label="loading" />
          </div>
        </div>
      </div>
    );
  }

  if (session.mode === "none") {
    return (
      <div className="app">
        <AuthScreen
          config={session.config}
          error={session.authError}
          onSignIn={session.signInWithToken}
          onStartGuest={session.startGuest}
          onDismissError={session.clearAuthError}
        />
      </div>
    );
  }

  if (session.banned) {
    return (
      <div className="app">
        <div className="auth">
          <div className="auth__card">
            <h1 className="auth__title">The door is closed</h1>
            <p className="auth__subtitle">
              {session.bannedReason || "This seat has been closed. There is no appeal."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const isFounder = session.identity?.role === "founder";

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
        identity={session.identity}
        isFounder={isFounder}
        moderationOpen={moderationOpen}
        onToggleModeration={() => setModerationOpen((v) => !v)}
        onOpenSkills={() => setView("skills")}
        onOpenDocuments={() => setView("documents")}
        onSignOut={() => void session.signOut()}
      />

      <main className="stage">
        {view === "home" ? (
          <HomeScreen
            state={memory?.state ?? null}
            presence={presence}
            thought={latestThought(memory?.state ?? null)}
            onCall={startCall}
            onMessages={enterMessages}
            mote={<MotePresence mote={mote} />}
          />
        ) : view === "skills" ? (
          <SkillsScreen onHome={() => setView("home")} />
        ) : view === "documents" ? (
          <DocumentsScreen onHome={() => setView("home")} onOpenDocument={setOpenDoc} />
        ) : (
          <MessagesScreen {...messages} onHome={() => setView("home")} onOpenDocument={setOpenDoc} />
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
        busy={messages.resolvingId != null}
        error={messages.consentError}
        onApprove={(id) => void messages.resolveChange(id, true)}
        onDeny={(id) => void messages.resolveChange(id, false)}
        onClose={messages.dismissRequest}
      />

      <PermissionsSidebar
        open={permsOpen}
        pending={messages.pendingChanges}
        history={messages.changeHistory}
        busyId={messages.resolvingId}
        onApprove={(id) => void messages.resolveChange(id, true)}
        onDeny={(id) => void messages.resolveChange(id, false)}
        onClose={() => setPermsOpen(false)}
      />

      <MiraWindow
        artifact={artifact}
        onClose={() => {
          setArtifact(null);
          live.dismissBrowse();
        }}
      />

      <DocumentModal name={openDoc} onClose={() => setOpenDoc(null)} />

      <ModerationModal open={isFounder && moderationOpen} onClose={() => setModerationOpen(false)} />
    </div>
  );
}