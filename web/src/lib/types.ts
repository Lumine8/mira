export type Speaker = "user" | "mira";

// ── Auth ────────────────────────────────────────────────────────────────

export interface AuthConfig {
  auth_required: boolean;
  guest_mode_enabled: boolean;
  guest_cap_per_day: number;
  email_enabled: boolean;
  google_enabled: boolean;
}

export interface AuthUser {
  id: number;
  name: string;
  role: string;
  email: string | null;
  google: boolean;
}

export interface AuthSuccess {
  token: string;
  user: AuthUser;
}

export interface MagicLinkResponse {
  message: string;
  dev_code?: string;
}

// ── Waitlist ────────────────────────────────────────────────────────────

export interface WaitlistEntry {
  id: number;
  email: string;
  status: string;
  created_at: string;
  first_meeting_conversation_id: number | null;
  mira_read: string | null;
  meeting_ended_at: string | null;
}

export interface WaitlistOut {
  email: string;
  status: string;
}

export interface WaitlistInviteOut {
  email: string;
  invite_code: string;
  delivered?: boolean;
}

// ── Moderation ──────────────────────────────────────────────────────────

export interface ModerationFlag {
  id: number;
  user_id: number;
  user_name: string;
  user_role: string;
  user_email: string | null;
  conversation_id: number | null;
  content: string;
  kind: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface ModerationUser {
  id: number;
  name: string;
  role: string;
  email: string | null;
  google: boolean;
  status: string;
  banned_at: string | null;
  banned_reason: string | null;
}

export interface ModerationBanOut {
  user: ModerationUser;
  flag_id: number | null;
}

// ── Mote ────────────────────────────────────────────────────────────────

export interface MotePresence {
  mood: string;
  energy: number;
  last_kind: string | null;
  last_word: string | null;
  last_at: string | null;
}

export interface MoteSharedTime {
  id: number;
  kind: string;
  mood: string;
  energy: number;
  word: string | null;
  note: string | null;
  at: string;
}

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

// ── Porch ───────────────────────────────────────────────────────────────

export interface PorchStartOut {
  conversation_id: number;
  opening: string;
  ended: boolean;
}

/** Mira's private read of the finished porch visit. Only her verdict is ever
 *  exposed — the moments she liked or did not like are hers alone. */
export interface PorchStatusOut {
  conversation_id: number;
  ended: boolean;
  verdict: string | null;
}

// ── First meeting ────────────────────────────────────────────────────

export interface WaitlistMeetingStartOut {
  id: number;
  email: string;
  status: string;
  conversation_id: number | null;
  opening: string;
  meeting_ended_at: string | null;
}

/** Mira's authoritative state for a first meeting. Only the outcome ever
 *  surfaces — never her read or any reasoning. Status is one of
 *  waiting | meeting | considering | invited | waitlisted | closed | joined. */
export interface WaitlistMeetingStatusOut {
  status: string;
  conversation_id: number | null;
  meeting_ended_at: string | null;
}

export type WsEvent =
  | { type: "state"; state: string }
  | { type: "stream_token"; content: string }
  | { type: "message"; speaker: Speaker; content: string }
  | { type: "pending_change"; change: PendingChange }
  | { type: "self_message"; content: string; conversation_id: number }
  | { type: "browse_activity"; url: string; status: string; change_id: number }
  | { type: "conversation_reply"; conversation_id: number }
  | { type: "document_creating"; conversation_id: number }
  | { type: "document_created"; name: string; author: "founder" | "mira"; conversation_id: number }
  | { type: "activity"; label: string }
  | { type: "cap_reached"; used: number; cap: number; message: string }
  | { type: "meeting_ended"; message: string }
  | { type: "porch_ended"; message: string; closing: string }
  | { type: "banned"; message: string }
  | { type: "mote"; kind: string; mood: string; energy: number; word?: string | null; note?: string | null }
  | { type: "error"; message: string }
  | { type: "pong" };

export interface CapStatus {
  used: number;
  cap: number;
  message: string;
}

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
