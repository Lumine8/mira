import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";

import type { ConversationSummary, Message } from "../../lib/types";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";
import Composer from "./Composer";

export interface MessagesView {
  conversations: ConversationSummary[];
  active: { id: number; kind: string; messages: Message[] } | null;
  thinking: boolean;
  streaming: string;
  connected: boolean;
  error: string | null;
  onHome: () => void;
  openConversation: (id: number) => void;
  startNew: () => void;
  leaveThread: () => void;
  removeConversation: (id: number) => void;
  send: (content: string) => void;
  sendImage: (image: string, caption: string) => void;
}

function dayKey(iso: string): string {
  return new Date(iso).toDateString();
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  const sameYear = d.getFullYear() === today.getFullYear();
  return d.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Contiguous runs of the same speaker become timestamp groups, iMessage-style. */
function groupBySpeaker(messages: Message[]): Message[][] {
  const groups: Message[][] = [];
  for (const m of messages) {
    const g = groups[groups.length - 1];
    if (g && g[g.length - 1].speaker === m.speaker) g.push(m);
    else groups.push([m]);
  }
  return groups;
}

export default function MessagesScreen(view: MessagesView) {
  const { conversations, active, thinking, streaming, connected, error } = view;
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [active?.messages.length, streaming, thinking]);

  if (!active) {
    return (
      <div className="threads">
        <button className="threads__home" type="button" onClick={view.onHome}>
          ← Home
        </button>
        <button className="threads__new" onClick={() => void view.startNew()}>
          New conversation
        </button>
        {conversations.length === 0 && <div className="threads__empty">Nothing yet. Say hello.</div>}
        {conversations.map((c) => (
          <div key={c.id} className="thread">
            <button className="thread__open" onClick={() => void view.openConversation(c.id)}>
              <span className="thread__kind">
                {c.kind === "call" ? "Call" : c.kind === "self" ? "She spoke" : "Text"}
              </span>
              <span className="thread__time">
                {new Date(c.started_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
              </span>
            </button>
            <button
              className="thread__delete"
              title="Delete this conversation (Mira keeps her memories)"
              onClick={() => void view.removeConversation(c.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    );
  }

  const groups = groupBySpeaker(active.messages);
  let renderedDay = "";

  return (
    <motion.section
      className="messages"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 14 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      <header className="messages__header">
        <button className="messages__back" onClick={view.onHome}>
          ← Home
        </button>
        <h2>
          {active.kind === "call" ? "call — she speaks" : `conversation ${active.id}`}
        </h2>
        <button className="messages__new" onClick={() => void view.startNew()} title="Start a fresh conversation">
          New
        </button>
      </header>

      {error && <div className="messages__error">{error}</div>}

      <div className="thread-view">
        <div className="thread-view__scroll" ref={scrollRef}>
          {groups.map((group, gi) => {
            const groupDay = dayKey(group[0].created_at);
            const showDayChip = groupDay !== renderedDay;
            renderedDay = groupDay;
            return (
              <div key={`g-${gi}`}>
                {showDayChip && <div className="thread-view__date">{dayLabel(group[0].created_at)}</div>}
                {group.map((m) => (
                  <MessageBubble key={m.id} message={m} />
                ))}
                <div className="thread-view__time">{timeLabel(group[group.length - 1].created_at)}</div>
              </div>
            );
          })}
          <AnimatePresence>{thinking && !streaming && <TypingIndicator />}</AnimatePresence>
          {streaming && <div className="bubble bubble--mira bubble--streaming">{streaming}</div>}
        </div>
        <Composer disabled={!connected || thinking} onSend={view.send} onSendImage={view.sendImage} />
      </div>
    </motion.section>
  );
}
