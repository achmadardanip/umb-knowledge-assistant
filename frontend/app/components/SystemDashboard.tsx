"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Database, Globe, Network, Clock, BarChart3, AlertTriangle, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

// Phase 19 P19.3 — operations dashboard. Five live panels so an admin can spot
// any KB issue in seconds. Retrieval metrics come from the latest committed
// benchmark (not a live endpoint) and are shown as the validated baseline.
const RETRIEVAL_BASELINE = { official_top: 0.998, citation_failure: 0.0, follow_up: 1.0 };

function Row({ label, value, warn }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={warn ? "font-semibold text-red-600" : "font-medium text-foreground"}>{value}</span>
    </div>
  );
}

function Panel({ title, icon: Icon, children }: { title: string; icon: typeof Database; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Icon className="h-4 w-4 text-primary" /> {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">{children}</CardContent>
    </Card>
  );
}

export function SystemDashboard() {
  const opts = { refetchInterval: 30_000, staleTime: 15_000 };
  const health = useQuery({ queryKey: ["sys", "health"], queryFn: api.systemHealth, ...opts });
  const stats = useQuery({ queryKey: ["sys", "stats"], queryFn: api.systemStats, ...opts });
  const crawl = useQuery({ queryKey: ["sys", "crawl"], queryFn: api.systemCrawl, ...opts });
  const fresh = useQuery({ queryKey: ["sys", "freshness"], queryFn: api.systemFreshness, ...opts });
  const graph = useQuery({ queryKey: ["sys", "graph"], queryFn: api.systemGraph, ...opts });
  const dbq = useQuery({ queryKey: ["sys", "database"], queryFn: api.systemDatabase, ...opts });
  const alertsQ = useQuery({ queryKey: ["sys", "alerts"], queryFn: api.systemAlerts, ...opts });

  const num = (v: unknown) => (typeof v === "number" ? v.toLocaleString() : (v as React.ReactNode) ?? "—");
  const s = stats.data || {};
  const c = (crawl.data || {}) as Record<string, number>;
  const f = (fresh.data || {}) as Record<string, number | string>;
  const g = (graph.data || {}) as Record<string, number>;
  const d = (dbq.data || {}) as Record<string, number | string>;
  const healthStatus = (health.data?.status as string) || "…";

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Operations Dashboard</h1>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${healthStatus === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
          <Activity className="h-3.5 w-3.5" /> {healthStatus}
        </span>
      </div>

      {(() => {
        const provs = ((health.data?.providers as Record<string, string>) || {});
        const entries = Object.entries(provs);
        if (!entries.length) return null;
        return (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Providers:</span>
            {entries.map(([id, st]) => (
              <span key={id} className={`rounded-full border px-2 py-0.5 ${st === "healthy" ? "border-emerald-300 text-emerald-700 dark:text-emerald-300" : st === "unconfigured" ? "border-border text-muted-foreground" : "border-amber-300 text-amber-700 dark:text-amber-300"}`}>
                {id === "azure_foundry" ? "☁ azure_foundry" : id}: {st}
              </span>
            ))}
          </div>
        );
      })()}

      {(() => {
        const a = (alertsQ.data || {}) as Record<string, unknown>;
        const list = (a.active_alerts || []) as Array<{ severity: string; category: string; message: string }>;
        if (list.length === 0) {
          return (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
              <ShieldCheck className="h-4 w-4" /> No active alerts — all monitored conditions healthy.
            </div>
          );
        }
        return (
          <div className="space-y-1.5 rounded-lg border border-red-300 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
            <div className="flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-300">
              <AlertTriangle className="h-4 w-4" /> {list.length} active alert{list.length > 1 ? "s" : ""}
            </div>
            {list.map((al, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-red-700 dark:text-red-300">
                <span className="rounded bg-red-200 px-1.5 py-0.5 font-medium uppercase dark:bg-red-900">{al.severity}</span>
                <span className="text-muted-foreground">[{al.category}]</span> {al.message}
              </div>
            ))}
          </div>
        );
      })()}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Panel title="Knowledge Base" icon={Database}>
          <Row label="Chunks" value={num(s.chunks)} />
          <Row label="Sources" value={num(s.sources)} />
          <Row label="Entities" value={num(s.entities)} />
          <Row label="Faculties" value={num(s.faculties)} />
          <Row label="Programs" value={num(s.programs)} />
        </Panel>

        <Panel title="Retrieval (latest benchmark)" icon={BarChart3}>
          <Row label="official_top" value={RETRIEVAL_BASELINE.official_top} warn={RETRIEVAL_BASELINE.official_top < 0.99} />
          <Row label="citation_failure" value={RETRIEVAL_BASELINE.citation_failure} warn={RETRIEVAL_BASELINE.citation_failure > 0.01} />
          <Row label="follow_up" value={RETRIEVAL_BASELINE.follow_up} />
        </Panel>

        <Panel title="Crawl" icon={Globe}>
          <Row label="Pending URLs" value={num(c.pending_urls)} />
          <Row label="Processed URLs" value={num(c.processed_urls)} />
          <Row label="Failed URLs" value={num(c.failed_urls)} warn={(c.failed_urls || 0) > 0} />
          <Row label="Changed (7d)" value={num(c.changed_last_7d)} />
        </Panel>

        <Panel title="Freshness" icon={Clock}>
          <Row label="Verified today" value={num(f.verified_today)} />
          <Row label="Aging sources" value={num(f.aging_sources)} />
          <Row label="Stale sources" value={num(f.stale_sources)} warn={Number(f.stale_sources) > 0} />
          <Row label="Oldest source" value={f.oldest_source ? formatDate(String(f.oldest_source)) : "—"} />
        </Panel>

        <Panel title="Graph" icon={Network}>
          <Row label="Nodes" value={num(g.nodes)} />
          <Row label="Edges" value={num(g.edges)} />
          <Row label="Dangling edges" value={num(g.dangling_edges)} warn={(g.dangling_edges || 0) > 0} />
          <Row label="Duplicate entities" value={num(g.duplicate_entities)} warn={(g.duplicate_entities || 0) > 0} />
        </Panel>

        <Panel title="Database" icon={Database}>
          <Row label="Size" value={num(d.database_size)} />
          <Row label="Embeddings" value={num(d.embeddings)} />
          <Row label="Missing embeddings" value={num(d.missing_embeddings)} warn={Number(d.missing_embeddings) > 0} />
          <Row label="Orphan chunks" value={num(d.orphan_chunks)} warn={Number(d.orphan_chunks) > 0} />
        </Panel>
      </div>
    </div>
  );
}
