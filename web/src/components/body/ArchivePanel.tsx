import { useEffect, useState } from "react";
import {
  answerQuestion,
  askQuestion,
  dropQuestion,
  // fetchMoodHistory,
  fetchQuestions,
  fetchWants,
  satisfyWant,
} from "../../lib/api";
import type {
  ConversationSummary,
  MiraMemory,
  // MoodRecord,
  Question,
  Want,
} from "../../lib/types";

interface Props {
  open: boolean;
  memory: MiraMemory | null;
  conversations: ConversationSummary[];
  onOpenConversation: (id: number) => void;
  onClose: () => void;
}

export default function ArchivePanel({
  open,
  memory,
  conversations,
  onOpenConversation,
  onClose,
}: Props) {
  const memories = memory?.memories ?? [];
  const [wants, setWants] = useState<Want[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  // const [moodHistory, setMoodHistory] = useState<MoodRecord[]>([]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetchWants()
      .then((w) => {
        if (!cancelled) setWants(w);
      })
      .catch(() => {
        if (!cancelled) setWants([]);
      });
    fetchQuestions()
      .then((q) => {
        if (!cancelled) setQuestions(q);
      })
      .catch(() => {
        if (!cancelled) setQuestions([]);
      });
    // fetchMoodHistory()
    //   .then((m) => {
    //     if (!cancelled) setMoodHistory(m);
    //   })
    //   .catch(() => {
    //     if (!cancelled) setMoodHistory([]);
    //   });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleSatisfy = (want: Want) => {
    void satisfyWant(want.id)
      .then(() => setWants((ws) => ws.filter((w) => w.id !== want.id)))
      .catch(() => {});
  };

  const resolveQuestion = (q: Question, action: "ask" | "answer" | "drop") => {
    const fn = action === "ask" ? askQuestion : action === "answer" ? answerQuestion : dropQuestion;
    void fn(q.id)
      .then(() => setQuestions((qs) => qs.filter((x) => x.id !== q.id)))
      .catch(() => {});
  };

  return (
    <aside className={`archive ${open ? "archive--open" : ""}`} aria-hidden={!open}>
      <div className="archive__head">
        <h2>What she keeps</h2>
        <button className="archive__close" type="button" onClick={onClose} aria-label="Close archive">
          ×
        </button>
      </div>

      <section className="archive__block">
        <h3>Feeling lately</h3>
        {memory ? (
          <>
            <p className="archive__mood">
              <strong>{memory.state.mood}</strong> · energy {memory.state.energy}/100
            </p>
            {/* Mood history is paused for now — kept in the code for later.
            {moodHistory.length > 1 && (
              <ul className="archive__mood-history">
                {moodHistory.slice(0, 8).map((m) => (
                  <li key={m.id} className="archive__mood-row">
                    <span className="archive__mood-cell">{m.mood}</span>
                    <span className="archive__mood-cell">energy {m.energy}</span>
                    <span className="archive__mood-time">
                      {new Date(m.created_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            */}
            {memory.state.self_understanding && (
              <p className="archive__self">{memory.state.self_understanding}</p>
            )}
            {memory.state.things_she_is_curious_about.length > 0 && (
              <p className="archive__curious">
                curious about: {memory.state.things_she_is_curious_about.slice(-3).join(", ")}
              </p>
            )}
          </>
        ) : (
          <p className="archive__muted">unreachable</p>
        )}
      </section>

      <section className="archive__block">
        <h3>What she wants right now</h3>
        {wants.length === 0 && <p className="archive__muted">nothing weighing on her right now</p>}
        {wants.map((w) => (
          <div key={w.id} className="archive__want">
            <div className="archive__want-row">
              <p className="archive__want-text">{w.content}</p>
              <button
                className="archive__want-satisfy"
                type="button"
                onClick={() => handleSatisfy(w)}
                aria-label="She satisfied this want"
                title="She satisfied this"
              >
                satisfied
              </button>
            </div>
            <div className="archive__want-bar">
              <span
                className="archive__want-fill"
                style={{
                  width: `${Math.max(4, Math.min(100, w.intensity))}%`,
                  opacity: 0.45 + (w.tension / 100) * 0.55,
                }}
              />
            </div>
            <span className="archive__want-meta">
              {w.source === "inferred" ? "noticed" : "she said"} · pull {w.intensity} · unsettled {w.tension}
            </span>
          </div>
        ))}
      </section>

      <section className="archive__block">
        <h3>Questions she's carrying</h3>
        {questions.length === 0 && <p className="archive__muted">nothing weighing on her mind right now</p>}
        {questions.map((q) => (
          <div key={q.id} className="archive__question">
            <p className="archive__question-text">{q.question}</p>
            {q.origin && <p className="archive__question-origin">from {q.origin}</p>}
            <div className="archive__question-bar">
              <span
                className="archive__question-fill"
                style={{ width: `${Math.max(4, Math.min(100, q.importance))}%` }}
              />
            </div>
            <div className="archive__question-actions">
              <button className="archive__question-btn" type="button" onClick={() => resolveQuestion(q, "ask")} title="She asked this">
                asked
              </button>
              <button className="archive__question-btn" type="button" onClick={() => resolveQuestion(q, "answer")} title="She found an answer">
                answered
              </button>
              <button className="archive__question-btn" type="button" onClick={() => resolveQuestion(q, "drop")} title="She let this go">
                let go
              </button>
              <span className="archive__question-meta">
                {q.source === "inferred" ? "noticed" : "she wrote"} · {q.importance}
              </span>
            </div>
          </div>
        ))}
      </section>

      <section className="archive__block">
        <h3>Memories</h3>
        {memories.length === 0 && <p className="archive__muted">nothing kept yet</p>}
        {memories.slice(0, 8).map((m) => (
          <div key={m.id} className="archive__memory">
            <span className={`archive__valence archive__valence--${m.valence ?? "neutral"}`}>{m.valence ?? "·"}</span>
            <p>{m.content}</p>
          </div>
        ))}
      </section>

      <section className="archive__block">
        <h3>Threads</h3>
        {conversations.length === 0 && <p className="archive__muted">no threads yet</p>}
        {conversations.slice(0, 6).map((c) => (
          <button key={c.id} className="archive__thread" type="button" onClick={() => onOpenConversation(c.id)}>
            <span className="archive__thread-kind">
              {c.kind === "call" ? "Call" : c.kind === "self" ? "She spoke" : "Text"}
            </span>
            <span className="archive__thread-time">
              {new Date(c.started_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
            </span>
          </button>
        ))}
      </section>
    </aside>
  );
}
