"use client";
import * as React from "react";
import { Code2, ChevronRight } from "lucide-react";
import type { ChatMessage } from "../lib/types";
import { cn } from "../lib/utils";

const PROVIDER_LABELS: Record<string, string> = {
  azure_foundry: "Azure AI Foundry", local_ollama: "Local Ollama", local_lmstudio: "Local LM Studio",
  openai: "OpenAI", anthropic: "Claude", gemini: "Gemini", groq: "Groq", openrouter: "OpenRouter",
  huggingface: "Hugging Face", hermes: "Hermes", puter: "Puter",
};

/** Developer-mode collapsible showing retrieval/intent debug for an assistant message. */
export function DebugPanel({ message }: { message: ChatMessage }) {
  const [open, setOpen] = React.useState(false);
  const m = message.metadata || {};
  const providerLabel = message.provider_used ? (PROVIDER_LABELS[message.provider_used] || message.provider_used) : null;
  const latency = (m as Record<string, unknown>).latency_ms as number | undefined;
  const debug = {
    latency_ms: latency ?? null,
    intent: m.intent ?? null,
    retrieval_mode: m.retrieval_mode ?? null,
    retrieved_context_count: m.retrieved_context_count ?? null,
    indexed_context_count: m.indexed_context_count ?? null,
    web_context_count: m.web_context_count ?? null,
    agent_tool_calls: m.agent_tool_calls ?? null,
    retrieval_fallback_used: m.retrieval_fallback_used ?? null,
    cache_hit: m.cache_hit ?? null,
    confidence: message.confidence ?? null,
    sources: message.sources?.length ?? 0,
    provider_used: message.provider_used ?? null,
    model_used: message.model_used ?? null,
  };
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        <Code2 className="h-3 w-3" /> Developer mode
      </button>
      {open && (
        <div className="mt-1.5 space-y-1.5">
          <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-md border border-border bg-muted/50 p-2 text-[11px] text-foreground">
            <span><span className="text-muted-foreground">Provider:</span> {providerLabel ?? "—"}</span>
            <span><span className="text-muted-foreground">Model:</span> {message.model_used ?? "—"}</span>
            <span><span className="text-muted-foreground">Latency:</span> {latency != null ? `${latency} ms` : "—"}</span>
          </div>
          <pre className="overflow-x-auto rounded-md border border-border bg-muted/50 p-3 text-[11px] leading-relaxed text-muted-foreground">
{JSON.stringify(debug, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
