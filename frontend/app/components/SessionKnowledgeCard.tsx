"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../lib/api";

// Phase 20 P20.3 — read-only, collapsible "Current Context" card showing what the
// assistant currently remembers in this session (faculty / program / topic / age).
function fmtAge(seconds?: number): string {
  if (!seconds || seconds < 60) return `${seconds ?? 0}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function SessionKnowledgeCard({ sessionId }: { sessionId?: string | null }) {
  const [open, setOpen] = React.useState(true);
  const { data } = useQuery({
    queryKey: ["session-context", sessionId],
    queryFn: () => api.sessionContext(sessionId as string),
    enabled: !!sessionId,
    refetchInterval: 8000,
  });

  const d = (data || {}) as Record<string, unknown>;
  if (!sessionId || !d.available) return null;

  const rows: Array<[string, unknown]> = [
    ["Faculty", d.faculty_short || d.faculty],
    ["Program", d.program],
    ["Dean", d.dean],
    ["Kaprodi", d.kaprodi],
    ["Topic", d.topic],
    ["Session Age", fmtAge(d.session_age_seconds as number)],
  ];
  const visible = rows.filter(([, v]) => v != null && v !== "");
  if (visible.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card text-card-foreground">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium text-muted-foreground"
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5">
          <Brain className="h-3.5 w-3.5 text-primary" /> Current Context
        </span>
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <dl className="space-y-1 px-3 pb-3">
          {visible.map(([k, v]) => (
            <div key={k} className="flex items-center justify-between gap-2 text-xs">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="truncate font-medium text-foreground" title={String(v)}>{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
