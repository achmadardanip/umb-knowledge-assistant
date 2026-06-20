import type { AgentStep, ChatResponse, ProviderId, ProviderOption, RetrievalMode, Source } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function apiBases() {
  const bases = [API_BASE];
  if (typeof window !== "undefined" && window.location.hostname === "localhost") {
    bases.push("http://localhost:8001");
  }
  return Array.from(new Set(bases.map((base) => base.replace(/\/$/, ""))));
}

async function fetchWithFallback(path: string, init?: RequestInit): Promise<Response> {
  let lastError: unknown = null;
  const bases = apiBases();
  const lastBase = bases[bases.length - 1];
  for (const base of bases) {
    try {
      const response = await fetch(`${base}${path}`, init);
      if (response.ok || response.status < 500 || base === lastBase) {
        return response;
      }
      lastError = new Error(`Request failed: ${response.status}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Failed to fetch");
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithFallback(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

type ChatPayload = {
  session_id?: string | null;
  anonymous_session_id: string;
  question: string;
  top_k: number;
  provider_override?: ProviderId | null;
  memory_enabled: boolean;
  regenerate_from_message_id?: string | null;
  retrieval_mode?: RetrievalMode;
  language?: string | null;
  audience?: string | null;
};

export const api = {
  providers: () =>
    apiJson<{
      default_provider: ProviderId;
      providers: ProviderOption[];
      web_search?: { enabled: boolean; provider: string; configured: boolean; strict_domain: string };
    }>("/settings/providers"),
  stats: () => apiJson<import("./types").KbStats>("/stats"),
  systemHealth: () => apiJson<Record<string, unknown>>("/system/health"),
  systemStats: () => apiJson<Record<string, number>>("/system/stats"),
  systemCrawl: () => apiJson<Record<string, unknown>>("/system/crawl"),
  systemFreshness: () => apiJson<Record<string, unknown>>("/system/freshness"),
  systemGraph: () => apiJson<Record<string, unknown>>("/system/graph"),
  systemDatabase: () => apiJson<Record<string, unknown>>("/system/database"),
  createSession: (anonymousSessionId: string) =>
    apiJson("/sessions", {
      method: "POST",
      body: JSON.stringify({ anonymous_session_id: anonymousSessionId })
    }),
  sessions: (anonymousSessionId: string) => apiJson(`/sessions?anonymous_session_id=${encodeURIComponent(anonymousSessionId)}`),
  messages: (sessionId: string) => apiJson(`/sessions/${sessionId}/messages`),
  sessionContext: (sessionId: string) => apiJson<Record<string, unknown>>(`/sessions/${sessionId}/context`),
  renameSession: (sessionId: string, title: string) =>
    apiJson(`/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify({ title })
    }),
  deleteSession: (sessionId: string) => apiJson(`/sessions/${sessionId}`, { method: "DELETE" }),
  memoryToggle: (sessionId: string, enabled: boolean) =>
    apiJson(`/sessions/${sessionId}/memory-toggle`, {
      method: "PATCH",
      body: JSON.stringify({ memory_enabled: enabled })
    }),
  chat: (payload: ChatPayload) =>
    apiJson<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  // Puter.js (browser, keyless) path: prepare builds the grounded prompt server-side,
  // the browser calls puter.ai.chat(messages), then finalize verifies the answer.
  chatPrepare: (payload: ChatPayload) =>
    apiJson<ChatResponse & { mode: "final" | "generate"; prepare_id?: string; messages?: { role: string; content: string }[] }>(
      "/chat/prepare",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  chatFinalize: (body: { prepare_id: string; answer: string; model_used?: string }) =>
    apiJson<ChatResponse>("/chat/finalize", { method: "POST", body: JSON.stringify(body) }),
  chatStream: async (
    payload: ChatPayload,
    handlers: {
      onStep?: (step: string | AgentStep) => void;
      onSources?: (sources: Source[]) => void;
      onFinal?: (result: ChatResponse) => void;
      onError?: (message: string) => void;
      signal?: AbortSignal;
    } = {}
  ): Promise<ChatResponse> => {
    const response = await fetchWithFallback("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: handlers.signal
    });
    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(errorPayload.detail || `Request failed: ${response.status}`);
    }
    if (!response.body) {
      throw new Error("Streaming response tidak tersedia.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResult: ChatResponse | null = null;

    function consumeEvent(rawEvent: string) {
      const lines = rawEvent.split(/\r?\n/);
      const eventLine = lines.find((line) => line.startsWith("event:"));
      const dataLines = lines.filter((line) => line.startsWith("data:"));
      const event = eventLine?.replace(/^event:\s*/, "").trim() || "message";
      const rawData = dataLines.map((line) => line.replace(/^data:\s*/, "")).join("\n");
      if (!rawData) return;
      const data = JSON.parse(rawData);
      if (event === "step") handlers.onStep?.(data.step ?? (data as AgentStep));
      if (event === "sources") handlers.onSources?.(data as Source[]);
      if (event === "error") {
        const message = data.detail || "Streaming chat gagal.";
        handlers.onError?.(message);
        throw new Error(message);
      }
      if (event === "final") {
        finalResult = data as ChatResponse;
        handlers.onFinal?.(finalResult);
      }
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\n\n/);
      buffer = events.pop() || "";
      for (const event of events) {
        if (event.trim()) consumeEvent(event);
      }
    }
    if (buffer.trim()) consumeEvent(buffer);
    if (!finalResult) throw new Error("Streaming selesai tanpa final response.");
    return finalResult as ChatResponse;
  },
  feedback: (messageId: string, rating: "helpful" | "not_helpful", comment?: string) =>
    apiJson<{ id: string; rating: string }>("/feedback", {
      method: "POST",
      body: JSON.stringify({ message_id: messageId, rating, comment: comment || null })
    })
};
