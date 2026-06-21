"use client";
import { useQuery } from "@tanstack/react-query";
import { Database, FileText, Boxes, Building2, GraduationCap, Clock } from "lucide-react";
import { api } from "../lib/api";
import type { KbStats as KbStatsT } from "../lib/types";
import { Skeleton } from "./ui/skeleton";
import { formatDate } from "../lib/utils";

function fmt(n?: number) {
  return typeof n === "number" ? n.toLocaleString("en-US") : "—";
}
// Deterministic (locale-independent) so SSR and client output match — avoids
// the React hydration mismatch that `toLocaleDateString` caused.
const fmtDate = (s?: string | null) => formatDate(s);

const ITEMS: { key: keyof KbStatsT; label: string; Icon: typeof Database }[] = [
  { key: "chunks", label: "Chunks", Icon: Database },
  { key: "sources", label: "Sources", Icon: FileText },
  { key: "entities", label: "Entities", Icon: Boxes },
  { key: "faculties", label: "Faculties", Icon: Building2 },
  { key: "programs", label: "Programs", Icon: GraduationCap },
];

export function KbStats() {
  const { data, isLoading, isError } = useQuery({ queryKey: ["kb-stats"], queryFn: api.stats });

  return (
    <section aria-label="Knowledge base statistics" className="rounded-lg border border-border bg-card p-3">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Knowledge Base</h2>
      {isError ? (
        <p className="text-xs text-muted-foreground">Stats unavailable.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            {ITEMS.map(({ key, label, Icon }) => (
              <div key={key} className="rounded-md border border-border bg-background/60 p-2">
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Icon className="h-3 w-3" /> {label}
                </div>
                {isLoading ? (
                  <Skeleton className="mt-1 h-5 w-12" />
                ) : (
                  <div className="text-sm font-semibold tabular-nums text-foreground">{fmt(data?.[key] as number)}</div>
                )}
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="h-3 w-3" /> Last updated:{" "}
            {isLoading ? <Skeleton className="inline-block h-3 w-20 align-middle" /> : fmtDate(data?.last_updated)}
          </div>
        </>
      )}
    </section>
  );
}
