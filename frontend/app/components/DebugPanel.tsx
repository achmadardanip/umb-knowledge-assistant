"use client";
import * as React from "react";
import { Code2, ChevronRight } from "lucide-react";
import type { ChatMessage } from "../lib/types";
import { cn } from "../lib/utils";

/** Developer-mode collapsible showing retrieval/intent debug for an assistant message. */
export function DebugPanel({ message }: { message: ChatMessage }) {
  const [open, setOpen] = React.useState(false);
  const m = message.metadata || {};
  const debug = {
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
        <pre className="mt-1.5 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 text-[11px] leading-relaxed text-muted-foreground">
{JSON.stringify(debug, null, 2)}
        </pre>
      )}
    </div>
  );
}
