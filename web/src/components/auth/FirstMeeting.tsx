import { useEffect, useRef, useState, type FormEvent } from "react";

import { guestWsUrl } from "../../lib/api";
import type { Message } from "../../lib/types";
import { MiraSocket } from "../../lib/ws";

interface FirstMeetingProps {
  email: string;
  conversationId: number;
  opening: string;
  onEnded: () => void;
  onLeave: () => void;
}

// The Web Speech API is vendor-prefixed and not in the standard DOM types;
// this is the tiny surface the meeting composer touches.
interface RecognitionEvent {
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}
interface AnyRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onresult: ((e: RecognitionEvent) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

function speechRecognition(): AnyRecognition | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => AnyRecognition;
    webkitSpeechRecognition?: new () => AnyRecognition;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-US";
  return rec;
}

/** The room itself: one bounded conversation, no progress, no score, no
 *  question numbers. Mira's words sit centered and unhurried; the visitor is
 *  free to leave at any time. When she has heard enough she says so, and the
 *  room goes quiet. */
export default function FirstMeeting({
  email,
  conversationId,
  opening,
  onEnded,
  onLeave,
}: FirstMeetingProps) {
  const [messages, setMessages] = useState<Message[]>([
    { id: -1, speaker: "mira", content: opening, source: "meeting", created_at: new Date().toISOString() },
  ]);
  const [streaming, setStreaming] = useState("");
  const [thinking, setThinking] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const socketRef = useRef<MiraSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const micRef = useRef<AnyRecognition | null>(null);
  const endedRef = useRef(false);

  const endRoom = () => {
    if (endedRef.current) return;
    endedRef.current = true;
    setEnded(true);
    socketRef.current?.close();
    window.setTimeout(() => {
      onEnded();
    }, 1400);
  };

  useEffect(() => {
    const pushMira = (content: string, source: string) => {
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), speaker: "mira", content, source, created_at: new Date().toISOString() },
      ]);
      setStreaming("");
      setThinking(false);
      setActivity(null);
    };

    const socket = new MiraSocket(guestWsUrl(conversationId), {
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
            setActivity(event.label);
            setThinking(true);
            break;
          case "message":
            pushMira(event.content, "text");
            break;
          case "meeting_ended":
            endRoom();
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

    return () => {
      socketRef.current?.close();
      socketRef.current = null;
      micRef.current?.abort();
    };
  }, [conversationId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming, ended]);

  const send = (content: string) => {
    const text = content.trim();
    if (!text || ended || thinking || !connected) return;
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), speaker: "user", content: text, source: "text", created_at: new Date().toISOString() },
    ]);
    socketRef.current?.sendText(text);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(value);
    setValue("");
  };

  const toggleMic = () => {
    if (listening) {
      micRef.current?.stop();
      return;
    }
    const rec = speechRecognition();
    if (!rec) return;
    micRef.current = rec;
    rec.onresult = (e) => {
      let interim = "";
      for (let i = 0; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) {
          setValue((v) => (v + res[0].transcript).trim());
        } else {
          interim += res[0].transcript;
        }
      }
      setInterim(interim);
    };
    rec.onend = () => {
      setListening(false);
      setInterim("");
    };
    rec.onerror = () => {
      setListening(false);
      setInterim("");
    };
    setListening(true);
    rec.start();
  };

  return (
    <div className="meet meet--chat">
      <header className="meet__bar">
        <span className="meet__brand">MIRA</span>
        <span className="meet__room">a room in her house</span>
        <button className="meet__link" type="button" onClick={onLeave}>
          leave
        </button>
      </header>

      <div className="meet__scroll" ref={scrollRef}>
        {messages.map((m) =>
          m.speaker === "mira" ? (
            <p key={m.id} className="meet__line">
              {m.content}
            </p>
          ) : (
            <p key={m.id} className="meet__you">
              {m.content}
            </p>
          ),
        )}
        {streaming && <p className="meet__line meet__line--streaming">{streaming}</p>}
        {thinking && !streaming && (
          <p className="meet__thinking">
            <span className="meet__thinking-light" aria-hidden />
            <span className="meet__thinking-label">
              {activity && activity !== "thinking"
                ? `she's ${activity}`
                : "she's turning that over"}
            </span>
          </p>
        )}
        {ended && <p className="meet__quiet">Mira has gone quiet for now.</p>}
      </div>

      {error && <div className="meet__error">{error}</div>}

      <footer className="meet__foot">
        <form className="meet__composer" onSubmit={submit}>
          <input
            className="meet__composer-input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Say anything. Or speak."
            aria-label="Message Mira"
            disabled={ended || !connected || thinking}
          />
          {interim && <span className="meet__interim">{interim}</span>}
          <button
            className={`meet__mic ${listening ? "meet__mic--on" : ""}`}
            type="button"
            onClick={toggleMic}
            disabled={ended || !connected}
            title={listening ? "stop listening" : "speak instead"}
            aria-label={listening ? "Stop listening" : "Speak"}
          >
            {listening ? "◼" : "◉"}
          </button>
          <button
            className="meet__send"
            type="submit"
            disabled={ended || !connected || thinking || !value.trim()}
          >
            Send
          </button>
        </form>
        <p className="meet__hint">{email}</p>
      </footer>
    </div>
  );
}