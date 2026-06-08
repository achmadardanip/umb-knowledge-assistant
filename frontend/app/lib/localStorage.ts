import type { ProviderId, RetrievalMode } from "./types";

const KEYS = {
  anonymousId: "umb_anonymous_session_id",
  activeSession: "umb_last_active_session_id",
  provider: "umb_selected_provider",
  retrievalMode: "umb_selected_retrieval_mode",
  memory: "umb_memory_enabled"
};

function uuid() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `anon-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function getAnonymousSessionId() {
  const existing = window.localStorage.getItem(KEYS.anonymousId);
  if (existing) return existing;
  const created = uuid();
  window.localStorage.setItem(KEYS.anonymousId, created);
  return created;
}

export function getSelectedProvider(): ProviderId {
  return (window.localStorage.getItem(KEYS.provider) as ProviderId | null) || "puter";
}

export function setSelectedProvider(provider: ProviderId) {
  window.localStorage.setItem(KEYS.provider, provider);
}

export function getRetrievalMode(): RetrievalMode {
  const saved = window.localStorage.getItem(KEYS.retrievalMode) as RetrievalMode | null;
  if (saved === "web") {
    window.localStorage.setItem(KEYS.retrievalMode, "hybrid");
    return "hybrid";
  }
  if (saved === "hybrid" || saved === "indexed") return saved;
  return "hybrid";
}

export function setRetrievalMode(mode: RetrievalMode) {
  window.localStorage.setItem(KEYS.retrievalMode, mode);
}

export function getMemoryEnabled() {
  return window.localStorage.getItem(KEYS.memory) !== "false";
}

export function setMemoryEnabled(enabled: boolean) {
  window.localStorage.setItem(KEYS.memory, String(enabled));
}

export function getLastActiveSession() {
  return window.localStorage.getItem(KEYS.activeSession);
}

export function setLastActiveSession(sessionId: string) {
  window.localStorage.setItem(KEYS.activeSession, sessionId);
}
