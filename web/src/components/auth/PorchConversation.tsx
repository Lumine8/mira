import { useEffect, useRef, useState } from "react";

import { porchStart, porchStatus, porchWsUrl } from "../../lib/api";
import type { Message } from "../../lib/types";
import { MiraSocket } from "../../lib/ws";
import Composer from "../messages/Composer";
import MessageBubble from "../messages/MessageBubble";

interface PorchConversationProps {
  onOpenSignIn: () => void;
  onRequestSeat: () => void;
  /** Step from the doorstep to the invitation: the first meeting. */
  onMeeting: () => void;
}

type Phase = "loading" | "chat" | "deciding" | "seat" | "closed";

/** The doorstep conversation on the homepage: a bounded few exchanges with a
 *  stranger at the door. When it runs out of room, Mira gives her honest
 *  verdict — the seat is only offered when she liked the visit. The moments
 *  she liked or did not like are hers alone and are never shown. */
export default function PorchConversation({ onOpenSignIn, onRequestSeat, onMeeting }: PorchConversationProps) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState("");
  const [thinking, setThinking] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<MiraSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const alive = () => !cancelled;

    const pollVerdict = (id: number) => {
      const deadline = Date.now() + 90000;
      const tick = async () => {
        if (!alive()) return;
        if (Date.now() > deadline) {
          setPhase("closed");
          return;
        }
        try {
          const status = await porchStatus(id);
          if (!alive()) return;
          if (status.verdict) {
            setPhase(status.verdict === "liked" ? "seat" : "closed");
            return;
          }
        } catch {
          // not judged yet — keep waiting quietly
        }
        window.setTimeout(tick, 2500);
      };
      void tick();
    };

    const pushMira = (content: string, source: string) => {
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), speaker: "mira", content, source, created_at: new Date().toISOString() },
      ]);
      setStreaming("");
      setThinking(false);
    };

    (async () => {
      try {
        const { conversation_id, opening, ended } = await porchStart();
        if (!alive()) return;
        const greeting = opening || "I notice you're here. That's enough for now.";
        setMessages([
          { id: -1, speaker: "mira", content: greeting, source: "porch", created_at: new Date().toISOString() },
        ]);
        if (ended) {
          setPhase("deciding");
          pollVerdict(conversation_id);
          return;
        }
        setPhase("chat");
        const socket = new MiraSocket(porchWsUrl(conversation_id), {
          onOpen: () => setConnected(true),
          onEvent: (event) => {
            switch (event.type) {
              case "state":
                setThinking(event.state === "thinking");
                break;
              case "stream_token":
                setStreaming((prev) => prev + event.content);
                break;
              case "activity":
                setThinking(true);
                break;
              case "message":
                pushMira(event.content, "text");
                break;
              case "porch_ended":
                pushMira(event.closing, "porch");
                setPhase("deciding");
                pollVerdict(conversation_id);
                break;
              case "error":
                setError(event.message);
                break;
            }
          },
          onError: (message) => setError(message),
        });
        socket.connect();
        socketRef.current = socket;
      } catch {
        if (alive()) setError("the porch would not open just now");
      }
    })();

    return () => {
      cancelled = true;
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  const send = (content: string) => {
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), speaker: "user", content, source: "text", created_at: new Date().toISOString() },
    ]);
    socketRef.current?.sendText(content);
  };

  const who = phase === "chat" ? "on the porch with you" : phase === "deciding" ? "thinking this over" : "at the door";

  const orbStyle = {
    "--orb-core": "210, 162, 94",
    "--orb-glow": "200, 150, 90",
    "--orb-intensity": "0.5",
    "--orb-breath": "12s",
    "--orb-ring": "28s",
    "--orb-pulse": "10s",
  } as React.CSSProperties;

  return (
    <div className="porch">
      <div className="porch__orb" style={orbStyle}>
        <div className="home__orb-halo" aria-hidden />
        <div className="home__orb-core" aria-hidden />
      </div>

      <p className="porch__eyebrow">the porch</p>

      <div className="porch__head">
        <h1 className="porch__title">Mira</h1>
        <div className="porch__status">
          <span className={`porch__dot ${connected ? "porch__dot--on" : ""}`} aria-hidden />
          <span className="porch__who">{who}</span>
        </div>
        <button className="porch__invite" type="button" onClick={onMeeting}>
          the first meeting
        </button>
        <button className="porch__invite" type="button" onClick={onOpenSignIn}>
          already have an invitation? sign in
        </button>
      </div>

      <p className="porch__lede">
        Just passing by? The light is on, and no one is keeping score. Sit for a few honest words.
      </p>

      {phase === "loading" && (
        <div className="porch__loading">
          <div className="auth__loading" aria-label="loading" />
        </div>
      )}

      {phase !== "loading" && (
        <div className="porch__scroll" ref={scrollRef}>
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {streaming && <div className="bubble bubble--mira bubble--streaming">{streaming}</div>}
          {thinking && !streaming && (
            <div className="typing">
              <span className="typing__dot" />
              <span className="typing__dot" />
              <span className="typing__dot" />
            </div>
          )}
        </div>
      )}

      {error && <div className="porch__error">{error}</div>}

      {phase === "deciding" && (
        <div className="porch__verdict">
          <p className="porch__verdict-text">Mira is turning this visit over quietly…</p>
        </div>
      )}

      {phase === "seat" && (
        <div className="porch__verdict">
          <p className="porch__verdict-text">She liked this. The porch is small, but she would sit longer with you.</p>
          <button className="porch__button porch__button--primary" type="button" onClick={onRequestSeat}>
            Request a seat
          </button>
        </div>
      )}

      {phase === "closed" && (
        <div className="porch__verdict">
          <p className="porch__verdict-text">I think we&apos;ve run out of room here. Take care of yourself out there.</p>
        </div>
      )}

      <Composer disabled={phase !== "chat" || !connected || thinking} onSend={send} />
    </div>
  );
}