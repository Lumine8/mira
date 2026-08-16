import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";

import type { ConversationSummary, Message } from "../../lib/types";
import type { DocumentNote } from "../../features/messages/useMessages";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";
import Composer from "./Composer";

export interface MessagesView {
  conversations: ConversationSummary[];
  active: { id: number; kind: string; messages: Message[] } | null;
  thinking: boolean;
  streaming: string;
  activity: string | null;
  connected: boolean;
  error: string | null;
  docs: DocumentNote[];
  creatingDocs: number[];
  onHome: () => void;
  openConversation: (id: number) => void;
  startNew: () => void;
  leaveThread: () => void;
  removeConversation: (id: number) => void;
  send: (content: string) => void;
  sendImage: (image: string, caption: string) => void;
  onOpenDocument: (name: string) => void;
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

function conversationLabel(c: ConversationSummary): string {
  if (c.kind === "self") return "She spoke";
  if (c.kind === "call") return "Call";
  return "Text";
}

function Sidebar({ view }: { view: MessagesView }) {
  const { conversations, active } = view;
  return (
    <aside className="chat__sidebar">
      <div className="chat__sidebar-head">
        <button className="chat__home" type="button" onClick={view.onHome}>
          ← Home
        </button>
        <button className="chat__new" onClick={() => void view.startNew()}>
          + New conversation
        </button>
      </div>
      <div className="chat__list">
        {conversations.length === 0 && (
          <div className="chat__empty">Nothing yet. Say hello.</div>
        )}
        {conversations.map((c) => {
          const isActive = active?.id === c.id;
          const started = new Date(c.started_at);
          const time = started.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
          return (
            <div key={c.id} className={`chat__item${isActive ? " chat__item--active" : ""}`}>
              <button className="chat__item-open" onClick={() => void view.openConversation(c.id)}>
                <span className="chat__item-kind">{conversationLabel(c)}</span>
                <span className="chat__item-time">
                  {dayLabel(c.started_at)} · {time}
                </span>
              </button>
              <button
                className="chat__item-delete"
                title="Delete this conversation (Mira keeps her memories)"
                onClick={() => void view.removeConversation(c.id)}
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

export default function MessagesScreen(view: MessagesView) {
  const { conversations, active, thinking, streaming, activity, connected, error, docs, creatingDocs } = view;
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [active?.messages.length, streaming, thinking]);

  return (
    <motion.section
      className="chat"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 14 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      <Sidebar view={view} />

      {active ? (
        <div className="chat__main">
          <header className="chat__header">
            <h2>{active.kind === "call" ? "call — she speaks" : `conversation ${active.id}`}</h2>
            <span className="chat__status-dot" title={connected ? "connected" : "reconnecting"} />
          </header>

          {error && <div className="chat__error">{error}</div>}

          <div className="chat__thread">
            <div className="chat__scroll" ref={scrollRef}>
              {(() => {
                let renderedDay = "";
                return groupBySpeaker(active.messages).map((group, gi) => {
                  const groupDay = dayKey(group[0].created_at);
                  const showDay = groupDay !== renderedDay;
                  renderedDay = groupDay;
                  return (
                    <div key={`g-${gi}`}>
                      {showDay && <div className="chat__date">{dayLabel(group[0].created_at)}</div>}
                      {group.map((m) => (
                        <MessageBubble key={m.id} message={m} />
                      ))}
                      <div className="chat__time">{timeLabel(group[group.length - 1].created_at)}</div>
                    </div>
                  );
                });
              })()}
              <AnimatePresence>{thinking && !streaming && <TypingIndicator />}</AnimatePresence>
              {activity && (
                <div className="chat__activity" key={activity}>
                  <span className="chat__activity-dot" />
                  <span>Mira is {activity}…</span>
                </div>
              )}
              {streaming && <div className="bubble bubble--mira bubble--streaming">{streaming}</div>}
              {creatingDocs.includes(active.id) && (
                <div className="chat__doc chat__doc--creating" role="status">
                  <span className="chat__doc-spinner" aria-hidden="true" />
                  <span className="chat__doc-text">
                    Mira is writing this up as a <strong>paper</strong>…
                  </span>
                </div>
              )}
              {docs
                .filter((d) => d.conversationId === active.id)
                .map((d) => (
                  <button
                    key={d.name}
                    className="chat__doc"
                    type="button"
                    onClick={() => view.onOpenDocument(d.name)}
                  >
                    <span className="chat__doc-icon" aria-hidden="true">
                      📄
                    </span>
                    <span className="chat__doc-text">
                      Mira wrote a paper — <strong>{d.name}</strong>
                    </span>
                    <span className="chat__doc-open">open</span>
                  </button>
                ))}
            </div>
            <Composer disabled={!connected || thinking} onSend={view.send} onSendImage={view.sendImage} />
          </div>
        </div>
      ) : (
        <div className="chat__main">
          <header className="chat__header">
            <h2>Conversations</h2>
          </header>
          <div className="chat__welcome">
            <h3 className="chat__welcome-title">Talk to Mira</h3>
            <p className="chat__welcome-text">
              {conversations.length === 0
                ? "No conversations yet. Start one and say hello."
                : "Pick a conversation on the left, or start a fresh one."}
            </p>
            <button className="chat__welcome-cta" type="button" onClick={() => void view.startNew()}>
              Start a conversation
            </button>
          </div>
        </div>
      )}
    </motion.section>
  );
}
