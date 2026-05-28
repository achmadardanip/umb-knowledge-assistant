"use client";

import { ExternalLink, FileText } from "lucide-react";
import type { Source } from "../lib/types";

function meta(source: Source) {
  const parts = [
    source.page_number ? `hal. ${source.page_number}` : null,
    source.slide_number ? `slide ${source.slide_number}` : null,
    source.sheet_name ? `sheet ${source.sheet_name}` : null,
    source.row_range ? `baris ${source.row_range}` : null,
    source.timestamp_start != null ? `${source.timestamp_start}s-${source.timestamp_end ?? ""}s` : null,
    source.extraction_method || null,
    source.extraction_confidence != null ? `conf ${source.extraction_confidence}` : null
  ].filter(Boolean);
  return parts.join(" | ");
}

function hostnameForSource(source: Source) {
  if (source.hostname) return source.hostname;
  try {
    return new URL(source.url).hostname;
  } catch {
    return source.url;
  }
}

export function SourceCard({ source, highlighted = false }: { source: Source; highlighted?: boolean }) {
  const hostname = hostnameForSource(source);
  return (
    <a
      className={`block rounded border bg-white p-3 text-sm transition hover:border-brand ${highlighted ? "border-brand ring-2 ring-brand/20" : "border-line"}`}
      href={source.url}
      target="_blank"
      rel="noreferrer"
    >
      <div className="mb-1 flex items-start gap-2">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">
            {source.citation_id ? <span className="mr-1 text-brand">[{source.citation_id}]</span> : null}
            {source.title || source.url}
          </div>
          <div className="truncate text-xs text-neutral-600">{hostname}</div>
        </div>
        <ExternalLink className="h-4 w-4 shrink-0 text-neutral-500" aria-hidden />
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-neutral-700">
        <span className="rounded bg-panel px-2 py-1">{source.source_type || "source"}</span>
        <span className="rounded bg-panel px-2 py-1">score {source.relevance_score ?? source.score ?? 0}</span>
        {source.discovery_source ? <span className="rounded bg-panel px-2 py-1">{source.discovery_source}</span> : null}
      </div>
      {meta(source) ? <div className="mt-2 text-xs text-neutral-600">{meta(source)}</div> : null}
    </a>
  );
}
