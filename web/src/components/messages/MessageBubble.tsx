import type { Message } from "../../lib/types";

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.speaker === "user";
  return (
    <div className={`bubble ${isUser ? "bubble--user" : "bubble--mira"}`}>
      {message.image && (
        <img className="bubble__image" src={message.image} alt="handed to Mira" loading="lazy" />
      )}
      {message.content && <div className="bubble__text">{message.content}</div>}
    </div>
  );
}
