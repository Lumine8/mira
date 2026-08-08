export type Speaker = "user" | "mira";

export interface Message {
  id: number;
  speaker: Speaker;
  content: string;
  image?: string | null;
  source: string;
  created_at: string;
}

export interface ConversationSummary {
  id: number;
  kind: string;
  summary: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
}

export interface StartConversationResponse {
  conversation_id: number;
  ws_url: string;
}

export type WsEvent =
  | { type: "state"; state: string }
  | { type: "stream_token"; content: string }
  | { type: "message"; speaker: Speaker; content: string }
  | { type: "pending_change"; change: PendingChange }
  | { type: "self_message"; content: string; conversation_id: number }
  | { type: "browse_activity"; url: string; status: string; change_id: number }
  | { type: "error"; message: string }
  | { type: "pong" };

export interface PendingChange {
  id: number;
  kind: string;
  summary: string;
  payload: Record<string, unknown>;
  status: string;
  result?: string | null;
  created_at?: string;
}

export interface ConnectionState {
  connected: boolean;
  thinking: boolean;
}

export interface Health {
  status: string;
  db: string;
  ollama: string;
  provider: string;
  ollama_model?: string | null;
}

export interface MiraState {
  mood: string;
  energy: number;
  self_understanding: string | null;
  things_she_is_curious_about: string[];
  last_conversation_summary: string | null;
  pending_message: string | null;
  pending_message_conversation_id: number | null;
  carried_thoughts: string[];
  last_reflection_at: string | null;
  updated_at: string;
}

export interface Relationship {
  trust: number;
  humor: number;
  comfort: number;
  nicknames: string[];
  how_comfortable_we_are: string;
  topics_we_discuss: Record<string, number>;
}

export interface MemoryItem {
  id: number;
  type: string;
  content: string;
  valence: string | null;
  source_conversation_id: number | null;
  created_at: string;
}

export interface Want {
  id: number;
  content: string;
  source: string;
  intensity: number;
  tension: number;
  status: string;
  related_conversation_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface Question {
  id: number;
  question: string;
  source: string;
  origin: string | null;
  importance: number;
  status: string;
  related_conversation_id: number | null;
  asked_at: string | null;
  answered_at: string | null;
  last_revisited: string | null;
  created_at: string;
  updated_at: string;
}

export interface MiraMemory {
  state: MiraState;
  relationship: Relationship;
  memories: MemoryItem[];
}

export interface MoodRecord {
  id: number;
  mood: string;
  energy: number;
  source: string;
  note: string | null;
  created_at: string;
}
