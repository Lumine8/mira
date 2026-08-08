import type {
  ConversationDetail,
  ConversationSummary,
  MiraMemory,
  MoodRecord,
  PendingChange,
  Question,
  StartConversationResponse,
  Want,
} from "./types";
import { getAccessToken } from "./token";

const BASE = "/api";

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { "X-Mira-Token": token } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...init,
  });
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

export function wsUrlFor(conversationId: number): string {
  return `${wsBase()}/ws/conversation/${conversationId}${wsToken()}`;
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
