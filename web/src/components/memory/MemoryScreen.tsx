import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";

import { fetchMemory } from "../../lib/api";
import type { MiraMemory } from "../../lib/types";

function Meter({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="meter">
      <span className="meter__label">{label}</span>
      <div className="meter__track">
        <div className="meter__fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="meter__value">{pct}%</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="memory-card">
      <h3 className="memory-card__title">{title}</h3>
      {children}
    </section>
  );
}

export default function MemoryScreen({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<MiraMemory | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await fetchMemory());
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <motion.section
      className="memory"
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 24 }}
      transition={{ duration: 0.3 }}
    >
      <header className="memory__header">
        <button className="memory__back" onClick={onBack}>
          ← Back
        </button>
        <h2>Mira&apos;s memory</h2>
      </header>

      {error && <div className="memory__error">Couldn&apos;t reach Mira&apos;s memory.</div>}

      {data && (
        <div className="memory__body">
          <Section title="Right now">
            <div className="memory-grid">
              <div className="memory-grid__cell">
                <span className="memory-grid__key">Mood</span>
                <span className="memory-grid__value">{data.state.mood}</span>
              </div>
              <div className="memory-grid__cell">
                <span className="memory-grid__key">Energy</span>
                <span className="memory-grid__value">{data.state.energy}/100</span>
              </div>
            </div>
            {data.state.self_understanding && (
              <p className="memory-quote">{data.state.self_understanding}</p>
            )}
          </Section>

          <Section title="What she&apos;s thinking about">
            {data.state.carried_thoughts.length > 0 ? (
              <ul className="memory-list">
                {data.state.carried_thoughts.map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ul>
            ) : (
              <p className="memory-empty">Nothing carried right now.</p>
            )}
            {data.state.things_she_is_curious_about.length > 0 && (
              <>
                <span className="memory-grid__key">Curious about</span>
                <p className="memory-line">{data.state.things_she_is_curious_about.join(" · ")}</p>
              </>
            )}
            {data.state.last_conversation_summary && (
              <>
                <span className="memory-grid__key">Last conversation</span>
                <p className="memory-line">{data.state.last_conversation_summary}</p>
              </>
            )}
          </Section>

          <Section title="Us">
            <Meter label="Trust" value={data.relationship.trust} />
            <Meter label="Humor" value={data.relationship.humor} />
            <Meter label="Comfort" value={data.relationship.comfort} />
            <p className="memory-line">{data.relationship.how_comfortable_we_are}</p>
          </Section>

          <Section title="Memories she carries">
            {data.memories.length === 0 ? (
              <p className="memory-empty">No memories stored yet.</p>
            ) : (
              <ul className="memory-list memory-list--memories">
                {data.memories.map((m) => (
                  <li key={m.id} className="memory-item">
                    <span className={`memory-item__tag memory-item__tag--${m.type}`}>{m.type}</span>
                    {m.valence && (
                      <span className={`memory-item__valence memory-item__valence--${m.valence}`}>
                        {m.valence}
                      </span>
                    )}
                    <span className="memory-item__time">
                      {new Date(m.created_at).toLocaleString([], {
                        dateStyle: "short",
                        timeStyle: "short",
                      })}
                    </span>
                    <p className="memory-item__content">{m.content}</p>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      )}
    </motion.section>
  );
}
