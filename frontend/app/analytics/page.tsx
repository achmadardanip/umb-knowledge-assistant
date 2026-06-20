"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ThumbsUp, ThumbsDown, MessageSquare, AlertTriangle, Quote } from "lucide-react";
import { api } from "../lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

// Phase 22 P22.4 — feedback & conversation analytics dashboard (/analytics).
function Stat({ label, value, icon: Icon }: { label: string; value: React.ReactNode; icon: typeof ThumbsUp }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className="rounded-md bg-primary/10 p-2 text-primary"><Icon className="h-5 w-5" /></div>
        <div>
          <div className="text-xl font-semibold">{value}</div>
          <div className="text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  );
}

const pct = (v: unknown) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—");

export default function AnalyticsPage() {
  const { data } = useQuery({ queryKey: ["analytics"], queryFn: api.analytics, refetchInterval: 30_000 });
  const d = (data || {}) as Record<string, unknown>;
  const tf = (d.top_failures || {}) as Record<string, unknown>;
  const repeated = (tf.repeated_unanswered_questions || []) as Array<{ question: string; count: number }>;
  const failedEntity = (tf.failed_entity_resolution || []) as Array<{ question: string; count: number }>;

  return (
    <main className="mx-auto min-h-screen max-w-5xl space-y-4 bg-background p-4 text-foreground">
      <h1 className="text-lg font-semibold">Conversation Analytics</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Total chats" value={String(d.total_chats ?? "—")} icon={MessageSquare} />
        <Stat label="Total answers" value={String(d.total_answers ?? "—")} icon={MessageSquare} />
        <Stat label="Positive rate" value={pct(d.positive_rate)} icon={ThumbsUp} />
        <Stat label="Negative rate" value={pct(d.negative_rate)} icon={ThumbsDown} />
        <Stat label="Unanswered rate" value={pct(d.unanswered_rate)} icon={AlertTriangle} />
        <Stat label="Citation usage" value={pct(d.citation_usage_rate)} icon={Quote} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Repeated Unanswered Questions</CardTitle></CardHeader>
          <CardContent className="pt-0">
            {repeated.length === 0 ? <p className="text-sm text-muted-foreground">None detected.</p> :
              repeated.map((r, i) => (
                <div key={i} className="flex justify-between gap-2 py-1 text-sm">
                  <span className="truncate text-foreground" title={r.question}>{r.question}</span>
                  <span className="font-medium text-red-600">{r.count}×</span>
                </div>
              ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Failed Entity Resolution</CardTitle></CardHeader>
          <CardContent className="pt-0">
            <div className="mb-2 text-xs text-muted-foreground">
              Repeated clarification requests: <span className="font-medium text-foreground">{String(tf.repeated_clarification_requests ?? 0)}</span>
            </div>
            {failedEntity.length === 0 ? <p className="text-sm text-muted-foreground">None detected.</p> :
              failedEntity.map((r, i) => (
                <div key={i} className="flex justify-between gap-2 py-1 text-sm">
                  <span className="truncate text-foreground" title={r.question}>{r.question}</span>
                  <span className="font-medium text-amber-600">{r.count}×</span>
                </div>
              ))}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
