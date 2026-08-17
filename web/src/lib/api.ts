import type {
  AuthConfig,
  AuthSuccess,
  AuthUser,
  ConversationDetail,
  ConversationSummary,
  MagicLinkResponse,
  MiraMemory,
  ModerationBanOut,
  ModerationFlag,
  ModerationUser,
  MoodRecord,
  MotePresence,
  MoteSharedTime,
  PendingChange,
  PorchStartOut,
  PorchStatusOut,
  Question,
  SecretDoorOut,
  SecretRoomOut,
  StartConversationResponse,
  WaitlistEntry,
  WaitlistInviteOut,
  WaitlistMeetingStartOut,
  WaitlistMeetingStatusOut,
  WaitlistOut,
  Want,
} from "./types";
import { getAccessToken } from "./token";
import { guestId } from "./guest";

const BASE = "/api";

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { "X-Mira-Token": token } : {};
}

const UNAUTHORIZED_EVENT = "mira:unauthorized";

function dispatchUnauthorized(): void {
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Multipart bodies set their own Content-Type (with the boundary); forcing
  // the JSON one would corrupt them.
  const isForm = init?.body instanceof FormData;
  const res = await fetch(`${BASE}${path}`, {
    headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...authHeaders() },
    ...init,
  });
  if (res.status === 401) {
    // A missing/expired session anywhere drops the client back to sign-in.
    dispatchUnauthorized();
    throw new Error(`request failed: ${res.status}`);
  }
  if (!res.ok) {
    throw new Error(`request failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export function startConversation(kind: "call" | "text"): Promise<StartConversationResponse> {
  return request<StartConversationResponse>("/call/start", {
    method: "POST",
    body: JSON.stringify({ kind }),
  });
}

export function endConversation(conversationId: number): Promise<{ conversation_id: number }> {
  return request<{ conversation_id: number }>(
    `/call/end?conversation_id=${conversationId}`,
    { method: "POST" },
  );
}

/** Render Mira's words into sound (only valid for kind="call" conversations —
 *  the boundary she chose: text conversations stay quiet). */
export async function speak(conversationId: number, text: string): Promise<Blob> {
  const res = await fetch(`${BASE}/call/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ conversation_id: conversationId, text }),
  });
  if (!res.ok) {
    throw new Error(`speak failed: ${res.status} ${await res.text()}`);
  }
  return res.blob();
}

export function fetchHistory(): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>("/history");
}

export function fetchConversation(id: number): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/history/${id}`);
}

export function deleteConversation(conversationId: number): Promise<{ conversation_id: number; deleted: boolean }> {
  return request<{ conversation_id: number; deleted: boolean }>(`/history/${conversationId}`, {
    method: "DELETE",
  });
}

export function fetchMemory(): Promise<MiraMemory> {
  return request<MiraMemory>("/mira/memory");
}

export function fetchMoodHistory(): Promise<MoodRecord[]> {
  return request<MoodRecord[]>("/mira/mood-history");
}

export function fetchPending(): Promise<PendingChange[]> {
  return request<PendingChange[]>("/mira/tools/pending");
}

export function fetchChangeHistory(limit = 15): Promise<PendingChange[]> {
  return request<PendingChange[]>(`/mira/tools/history?limit=${limit}`);
}

export function fetchWants(): Promise<Want[]> {
  return request<Want[]>("/mira/wants");
}

export function satisfyWant(id: number): Promise<Want> {
  return request<Want>(`/mira/wants/${id}/satisfy`, { method: "POST" });
}

export function fetchQuestions(): Promise<Question[]> {
  return request<Question[]>("/mira/questions");
}

export function askQuestion(id: number): Promise<Question> {
  return request<Question>(`/mira/questions/${id}/ask`, { method: "POST" });
}

export function answerQuestion(id: number): Promise<Question> {
  return request<Question>(`/mira/questions/${id}/answer`, { method: "POST" });
}

export function dropQuestion(id: number): Promise<Question> {
  return request<Question>(`/mira/questions/${id}/drop`, { method: "POST" });
}

export function approveChange(id: number): Promise<PendingChange> {
  return request<PendingChange>(`/mira/tools/approve/${id}`, { method: "POST" });
}

export function denyChange(id: number): Promise<PendingChange> {
  return request<PendingChange>(`/mira/tools/deny/${id}`, { method: "POST" });
}

// ── Skills ─────────────────────────────────────────────────────────────

export interface SkillSummary {
  id: string;
  category: string;
  version: string;
  status: string;
  purpose: string;
  inputs: Record<string, unknown>[];
  outputs: Record<string, unknown>[];
  tools: string[];
  verification: string[];
  failure_modes: string[];
  constraints: string[];
  dependencies: string[];
  run_count?: number;
  last_edited?: string | null;
}

export interface SkillRunOut {
  id: number;
  version: string;
  task: string;
  status: string;
  error: string | null;
  output: string | null;
  created_at: string;
}

export interface SkillEvaluationOut {
  id: number;
  run_id?: number;
  version: string;
  task: string;
  scores: Record<string, unknown>;
  evidence_count: number;
  created_at: string;
}

export interface SkillDetail extends SkillSummary {
  page: string;
  recent_runs: SkillRunOut[];
  recent_evaluations: SkillEvaluationOut[];
}

export interface SkillRunResult {
  run: SkillRunOut;
  evaluation: SkillEvaluationOut | null;
}

export function fetchSkills(): Promise<SkillSummary[]> {
  return request<SkillSummary[]>("/mira/skills");
}

export function fetchSkill(skillId: string, includePage = true): Promise<SkillDetail> {
  return request<SkillDetail>(
    `/mira/skills/${encodeURIComponent(skillId)}?include_page=${includePage}`,
  );
}

/** Record a run of a skill: what it was asked and what it produced. The tool
 * runtime also does this automatically when one of a skill's tools fires. */
export function recordSkillRun(
  skillId: string,
  body: { task: string; output?: string; status?: string; error?: string },
): Promise<SkillRunResult> {
  return request<SkillRunResult>(
    `/mira/skills/${encodeURIComponent(skillId)}/runs`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** Re-measure a run against the skill's own checks, with any claims attached. */
export function evaluateSkillRun(
  skillId: string,
  runId: number,
  body: { names?: string[]; evidence?: Record<string, unknown>[] } = {},
): Promise<SkillEvaluationOut> {
  return request<SkillEvaluationOut>(
    `/mira/skills/${encodeURIComponent(skillId)}/runs/${runId}/evaluate`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

// ── Skill versions (the self-improvement loop) ─────────────────────────

export interface SkillVersionOut {
  id: number;
  skill_id: string;
  category: string;
  version: string;
  kind: string; // edit | revert
  path: string;
  reason: string;
  change_id: number | null;
  created_at: string;
  diff?: { tag: string; line: string }[];
  after_content?: string;
}

export function fetchSkillVersions(
  skillId: string,
  category?: string,
): Promise<SkillVersionOut[]> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return request<SkillVersionOut[]>(`/mira/skills/${encodeURIComponent(skillId)}/versions${q}`);
}

export function fetchSkillVersion(
  skillId: string,
  versionId: number,
  category?: string,
): Promise<SkillVersionOut> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return request<SkillVersionOut>(
    `/mira/skills/${encodeURIComponent(skillId)}/versions/${versionId}${q}`,
  );
}

export function revertSkillVersion(
  skillId: string,
  versionId: number,
  category?: string,
): Promise<SkillVersionOut> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return request<SkillVersionOut>(
    `/mira/skills/${encodeURIComponent(skillId)}/versions/${versionId}/revert${q}`,
    { method: "POST" },
  );
}

// ── Documents ─────────────────────────────────────────────────────────

export interface DocumentSummary {
  name: string;
  author: "founder" | "mira";
  size: number;
  preview: string;
  modified_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  content: string;
}

export function fetchDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>("/mira/documents");
}

export function fetchDocument(name: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/mira/documents/${encodeURIComponent(name)}`);
}

export interface ReadablePage {
  url: string;
  title: string;
  content: string;
}

export function fetchReadablePage(url: string): Promise<ReadablePage> {
  return request<ReadablePage>(`/mira/browse/readable?url=${encodeURIComponent(url)}`);
}

export function createDocument(title: string, content: string): Promise<DocumentDetail> {
  return request<DocumentDetail>("/mira/documents", {
    method: "POST",
    body: JSON.stringify({ title, content }),
  });
}

export function createPdfDocument(file: File, title: string): Promise<DocumentDetail> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("title", title);
  return request<DocumentDetail>("/mira/documents/pdf", { method: "POST", body: fd });
}

export function deleteDocument(name: string): Promise<{ name: string; deleted: boolean }> {
  return request<{ name: string; deleted: boolean }>(
    `/mira/documents/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
}

export type DocumentFormat = "md" | "docx" | "pdf";

async function requestBlob(path: string): Promise<Blob> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
  if (res.status === 401) {
    dispatchUnauthorized();
    throw new Error(`request failed: ${res.status}`);
  }
  if (!res.ok) {
    throw new Error(`request failed: ${res.status} ${await res.text()}`);
  }
  return res.blob();
}

/** Save a paper onto the reader's disk — as Markdown, Word, or PDF. */
export async function downloadDocument(name: string, format: DocumentFormat): Promise<void> {
  const blob = await requestBlob(
    `/mira/documents/${encodeURIComponent(name)}/download?format=${format}`,
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Auth ──────────────────────────────────────────────────────────────

export function fetchAuthConfig(): Promise<AuthConfig> {
  return request<AuthConfig>("/auth/config");
}

export function fetchMe(): Promise<AuthUser> {
  return request<AuthUser>("/auth/me");
}

export interface MeWithLock {
  identity: AuthUser | null;
  banned: boolean;
  bannedReason: string | null;
}

/** `/auth/me`, except a banned account resolves as a lock instead of a 403:
 *  the seat is gone, and the frontend shows the closed door rather than a
 *  generic error. */
export async function fetchMeWithLock(): Promise<MeWithLock> {
  const res = await fetch(`${BASE}/auth/me`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (res.ok) {
    return { identity: (await res.json()) as AuthUser, banned: false, bannedReason: null };
  }
  if (res.status === 403) {
    try {
      const detail = (await res.json()) as { detail?: { banned?: boolean; reason?: string } };
      if (detail.detail?.banned) {
        return { identity: null, banned: true, bannedReason: detail.detail.reason ?? null };
      }
    } catch {
      // not the structured lock; fall through to a normal error
    }
  }
  throw new Error(`request failed: ${res.status} ${await res.text()}`);
}

export function requestMagicLink(email: string): Promise<MagicLinkResponse> {
  return request<MagicLinkResponse>("/auth/magic-link", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyMagicLink(email: string, code: string): Promise<AuthSuccess> {
  return request<AuthSuccess>("/auth/magic-link/verify", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

export async function googleAuthorizeUrl(): Promise<string> {
  const res = await request<{ url: string }>("/auth/google/authorize");
  return res.url;
}

export async function logout(): Promise<void> {
  const token = getAccessToken();
  if (!token) return;
  try {
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
  } catch {
    // the local token is cleared regardless; the session will expire
  }
}

// ── Waitlist ──────────────────────────────────────────────────────────

export function waitlistSignup(email: string): Promise<WaitlistOut> {
  return request<WaitlistOut>("/waitlist/signup", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function waitlistJoin(email: string, code: string): Promise<AuthSuccess> {
  return request<AuthSuccess>("/waitlist/join", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

export function waitlistList(): Promise<WaitlistEntry[]> {
  return request<WaitlistEntry[]>("/waitlist");
}

export function waitlistInvite(email: string): Promise<WaitlistInviteOut> {
  return request<WaitlistInviteOut>("/waitlist/invite", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function waitlistDecline(entryId: number): Promise<WaitlistOut> {
  return request<WaitlistOut>(`/waitlist/${entryId}/decline`, { method: "POST" });
}

export function waitlistForget(entryId: number): Promise<{ forgotten: boolean }> {
  return request<{ forgotten: boolean }>(`/waitlist/${entryId}`, { method: "DELETE" });
}

// ── Porch (the anonymous doorstep conversation) ────────────────────────

function guestHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", "X-Guest-Id": guestId() };
}

export function porchStart(): Promise<PorchStartOut> {
  return request<PorchStartOut>("/porch/start", {
    method: "POST",
    headers: guestHeaders(),
  });
}

export function porchStatus(conversationId: number): Promise<PorchStatusOut> {
  return request<PorchStatusOut>(`/porch/${conversationId}`, {
    headers: guestHeaders(),
  });
}

// ── First meeting (the door's own meeting, before the porch) ─────────

export function meetingStart(email: string): Promise<WaitlistMeetingStartOut> {
  return request<WaitlistMeetingStartOut>("/waitlist/meeting/start", {
    method: "POST",
    headers: guestHeaders(),
    body: JSON.stringify({ email }),
  });
}

export function meetingStatus(email: string): Promise<WaitlistMeetingStatusOut> {
  return request<WaitlistMeetingStatusOut>(
    `/waitlist/meeting/status?email=${encodeURIComponent(email)}`,
    { headers: guestHeaders() },
  );
}

/** Step through a door Mira herself opened — the address becomes a real
 *  account. Only this device (the one that sat the meeting) can. */
export function meetingAdmit(email: string): Promise<AuthSuccess> {
  return request<AuthSuccess>("/waitlist/meeting/admit", {
    method: "POST",
    headers: guestHeaders(),
    body: JSON.stringify({ email }),
  });
}

// ── Moderation ────────────────────────────────────────────────────────

export function fetchModerationFlags(status?: string): Promise<ModerationFlag[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<ModerationFlag[]>(`/moderation/flags${q}`);
}

export function banFromFlag(flagId: number, reason = ""): Promise<ModerationBanOut> {
  return request<ModerationBanOut>(`/moderation/flags/${flagId}/ban`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function dismissFlag(flagId: number): Promise<ModerationFlag> {
  return request<ModerationFlag>(`/moderation/flags/${flagId}/dismiss`, { method: "POST" });
}

export function fetchModerationUsers(): Promise<ModerationUser[]> {
  return request<ModerationUser[]>("/moderation/users");
}

export function banUser(userId: number, reason = ""): Promise<ModerationBanOut> {
  return request<ModerationBanOut>(`/moderation/users/${userId}/ban`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function unbanUser(userId: number): Promise<ModerationUser> {
  return request<ModerationUser>(`/moderation/users/${userId}/unban`, { method: "POST" });
}

export function deleteUser(userId: number): Promise<{ user_id: number; deleted: boolean }> {
  return request<{ user_id: number; deleted: boolean }>(`/moderation/users/${userId}`, {
    method: "DELETE",
  });
}

// ── Mote ──────────────────────────────────────────────────────────────

export function fetchMotePresence(): Promise<MotePresence> {
  return request<MotePresence>("/mote");
}

export function fetchMoteJournal(): Promise<MoteSharedTime[]> {
  return request<MoteSharedTime[]>("/mote/journal");
}

export function wsUrlFor(conversationId: number): string {
  return `${wsBase()}/ws/conversation/${conversationId}${wsToken()}`;
}

/** The porch socket authenticates by device fingerprint, not a session — the
 *  visitor is still anonymous at the door. */
export function porchWsUrl(conversationId: number): string {
  return guestWsUrl(conversationId);
}

/** Any guest conversation socket — the porch and the first meeting both
 *  authenticate by the device fingerprint. */
export function guestWsUrl(conversationId: number): string {
  return `${wsBase()}/ws/conversation/${conversationId}?guest=${encodeURIComponent(guestId())}`;
}

export function liveWsUrl(): string {
  return `${wsBase()}/ws/live${wsToken()}`;
}

function wsBase(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}`;
}

function wsToken(): string {
  const token = getAccessToken();
  return token ? `?token=${encodeURIComponent(token)}` : "";
}

export function acknowledge(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/mira/acknowledge", { method: "POST" });
}

export interface XStatus {
  connected: boolean;
  username?: string | null;
  configured: boolean;
}

export function fetchXStatus(): Promise<XStatus> {
  return request<XStatus>("/mira/x/status");
}

/** URL Mira's OAuth flow needs the voice to open in a browser. The token is
 * appended as ?token= because this is opened via a plain navigation that
 * cannot carry the X-Mira-Token header. */
export function xAuthUrl(): string {
  const token = getAccessToken();
  return `${BASE}/mira/x/auth/start${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

// ── The secret room ──────────────────────────────────────────────────
// These deliberately carry no session token: the pass-phrase is the key,
// and anyone Mira (or the voice) trusts may enter without an account. A 401
// here is a dead room-token, not a dead session — so this path never fires
// the app-wide sign-out.

async function rawJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`request failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export function secretDoor(phrase: string): Promise<SecretDoorOut> {
  return rawJson<SecretDoorOut>("/secret/door", {
    method: "POST",
    body: JSON.stringify({ phrase }),
  });
}

export function secretRoom(token: string): Promise<SecretRoomOut> {
  return rawJson<SecretRoomOut>("/secret/room", {
    headers: { "X-Secret-Token": token },
  });
}
