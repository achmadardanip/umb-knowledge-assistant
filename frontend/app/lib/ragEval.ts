const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RagResult {
  question_id: string;
  question: string;
  intent: string | null;
  faithfulness_score: number | null;
  faithfulness_pass: boolean | null;
  relevance_score: number | null;
  relevance_pass: boolean | null;
  not_found: boolean;
  grader_error: boolean;
  latency_ms: number | null;
  n_done?: number;
  n_total?: number;
  agg_faithfulness?: number | null;
  agg_relevance?: number | null;
}

export interface RagRunSummary {
  id: string;
  status: "running" | "completed" | "failed";
  n_total: number;
  n_done: number;
  agg_faithfulness: number | null;
  agg_relevance: number | null;
  grader_model: string | null;
  error: string | null;
}

export async function startRun(): Promise<string> {
  const res = await fetch(`${API_BASE}/eval/rag/runs`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to start run (${res.status})`);
  }
  return (await res.json()).run_id as string;
}

export async function listRuns(): Promise<RagRunSummary[]> {
  const res = await fetch(`${API_BASE}/eval/rag/runs`);
  return res.ok ? res.json() : [];
}

// Streams SSE from /eval/rag/runs/{id}/stream using the same getReader pattern as api.ts.
export async function streamRun(
  runId: string,
  handlers: {
    onResult?: (r: RagResult) => void;
    onDone?: (d: RagResult) => void;
    onError?: (msg: string) => void;
    signal?: AbortSignal;
  }
): Promise<void> {
  const res = await fetch(`${API_BASE}/eval/rag/runs/${runId}/stream`, { signal: handlers.signal });
  if (!res.ok || !res.body) throw new Error(`Stream failed (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consume = (rawEvent: string) => {
    const lines = rawEvent.split(/\r?\n/);
    const event = lines.find((l) => l.startsWith("event:"))?.replace(/^event:\s*/, "").trim() || "message";
    const data = lines.filter((l) => l.startsWith("data:")).map((l) => l.replace(/^data:\s*/, "")).join("\n");
    if (!data) return;
    let parsed: any;
    try {
      parsed = JSON.parse(data);
    } catch {
      return; // skip malformed frame
    }
    if (event === "result") handlers.onResult?.(parsed);
    if (event === "done") handlers.onDone?.(parsed);
    if (event === "error") handlers.onError?.(parsed.message || "stream error");
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) if (part.trim()) consume(part);
  }
}
