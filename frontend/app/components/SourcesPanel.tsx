"use client";
import * as React from "react";
import { ExternalLink, FileText, Globe, Database, Copy, Check } from "lucide-react";
import type { Source } from "../lib/types";
import { Badge } from "./ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { Progress } from "./ui/progress";
import { Separator } from "./ui/separator";
import { cn, formatDate } from "../lib/utils";

function hostLabel(s: Source): string {
  return s.hostname || (() => { try { return new URL(s.url).hostname; } catch { return s.url; } })();
}
function pct(s: Source): number | null {
  const v = s.relevance_score ?? s.score;
  if (v == null) return null;
  return v <= 1 ? Math.round(v * 100) : Math.min(100, Math.round(v));
}
function typeIcon(t?: string) {
  if (t === "pdf") return FileText;
  if (t === "entity" || t === "graph" || t === "faq") return Database;
  return Globe;
}

// Phase 16 P16.3 — freshness colour by tier (fresh=green, aging=amber, stale=red).
function freshnessClasses(tier?: string | null): string {
  if (tier === "fresh") return "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300";
  if (tier === "aging") return "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300";
  if (tier === "stale") return "border-red-300 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300";
  return "border-border bg-muted text-muted-foreground";
}

export function SourcesPanel({ sources }: { sources?: Source[] }) {
  const [active, setActive] = React.useState<Source | null>(null);
  const [copied, setCopied] = React.useState(false);
  if (!sources?.length) return null;

  async function copyCitation(s: Source) {
    const ref = `[${s.citation_id ?? "•"}] ${s.title || hostLabel(s)} — ${s.url}`;
    try {
      await navigator.clipboard.writeText(ref);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Globe className="h-3.5 w-3.5" /> {sources.length} official source{sources.length > 1 ? "s" : ""}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((s, i) => {
          const Icon = typeIcon(s.source_type);
          return (
            <button
              key={`${s.url}-${i}`}
              onClick={() => setActive(s)}
              className="group inline-flex max-w-[260px] items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs transition-colors hover:border-primary/60 hover:bg-accent"
            >
              <span className="flex h-4 w-4 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">
                {s.citation_id ?? i + 1}
              </span>
              <Icon className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="truncate text-foreground">{s.title || hostLabel(s)}</span>
            </button>
          );
        })}
      </div>

      <Sheet open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <SheetContent side="right">
          {active && (
            <>
              <SheetHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="info">Source {active.citation_id ?? "•"}</Badge>
                  <Badge variant="outline">{hostLabel(active)}</Badge>
                  {active.source_type && <Badge variant="outline">{active.source_type}</Badge>}
                  <button
                    type="button"
                    onClick={() => copyCitation(active)}
                    title="Copy citation"
                    className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied ? "Copied" : "Cite"}
                  </button>
                </div>
                <SheetTitle className="pr-6">{active.title || hostLabel(active)}</SheetTitle>
                <SheetDescription>{hostLabel(active)}</SheetDescription>
                {active.freshness_label && (
                  <span
                    className={cn(
                      "mt-1 inline-flex w-fit items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
                      freshnessClasses(active.freshness_tier),
                    )}
                    title={active.crawl_date ? `Crawled ${formatDate(active.crawl_date)}` : undefined}
                  >
                    {active.freshness_label}
                  </span>
                )}
              </SheetHeader>
              <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
                <a
                  href={active.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 break-all text-primary hover:underline"
                >
                  <ExternalLink className="h-3.5 w-3.5 shrink-0" /> {active.url}
                </a>
                {pct(active) != null && (
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                      <span>Similarity / relevance</span><span>{pct(active)}%</span>
                    </div>
                    <Progress value={pct(active)!} />
                  </div>
                )}
                <Separator />
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                  {([
                    ["Retrieved from", hostLabel(active)],
                    ["Authority", active.authority_tier?.replace(/_/g, " ")],
                    ["Last crawl", active.crawl_date ? formatDate(active.crawl_date) : null],
                    ["Type", active.source_type],
                    ["Page", active.page_number],
                    ["Extraction", active.extraction_method],
                    ["Discovery", active.discovery_source],
                  ] as const).map(([k, v]) =>
                    v != null && v !== "" ? (
                      <div key={k}>
                        <dt className="text-muted-foreground">{k}</dt>
                        <dd className="font-medium text-foreground">{String(v)}</dd>
                      </div>
                    ) : null,
                  )}
                </dl>
                <p className="text-xs text-muted-foreground">
                  Grounded by official Universitas Mercu Buana sources. Open the link to verify.
                </p>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

export { hostLabel as sourceHostLabel };
