"use client";

import { useState } from "react";
import { AlertCircle, Check, CheckCircle2, Copy, Loader2, MoreHorizontal, RefreshCcw, ThumbsDown, ThumbsUp, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { api } from "../lib/api";
import type { ChatMessage } from "../lib/types";
import { SourceCard } from "./SourceCard";

const MAX_VISIBLE_SOURCES = 3;

function confidenceClass(confidence?: string | null) {
  if (confidence === "high") return "bg-emerald-100 text-emerald-800";
  if (confidence === "medium") return "bg-amber-100 text-amber-800";
  return "bg-neutral-200 text-neutral-800";
}

function StepIcon({ status }: { status?: string }) {
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-brand" />;
  if (status === "error") return <AlertCircle className="h-4 w-4 text-red-600" />;
  if (status === "skipped") return <Check className="h-4 w-4 text-neutral-400" />;
  return <CheckCircle2 className="h-4 w-4 text-emerald-700" />;
}

function formatMetadata(metadata?: Record<string, unknown>) {
  if (!metadata) return "";
  const parts: string[] = [];
  const intent = metadata.intent;
  const topHosts = metadata.top_hosts;
  const sourceTypes = metadata.source_types;
  const memoryUsed = metadata.memory_used;
  if (typeof intent === "string") parts.push(`intent: ${intent}`);
  if (Array.isArray(topHosts) && topHosts.length) parts.push(`host: ${topHosts.slice(0, 3).join(", ")}`);
  if (sourceTypes && typeof sourceTypes === "object") parts.push(`tipe: ${Object.keys(sourceTypes).slice(0, 4).join(", ")}`);
  if (typeof memoryUsed === "boolean") parts.push(`memori: ${memoryUsed ? "dipakai" : "tidak"}`);
  return parts.join(" | ");
}

function StepsDrawer({ message, onClose }: { message: ChatMessage; onClose: () => void }) {
  const steps = message.visible_steps || [];
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20" role="dialog" aria-modal="true">
      <aside className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-white p-5 shadow-xl">
        <div className="mb-5 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Detail proses</h2>
            <p className="mt-1 text-xs leading-5 text-neutral-600">Panel ini hanya menampilkan progres operasional sistem, bukan penalaran privat model.</p>
          </div>
          <button className="rounded p-2 text-neutral-600 hover:bg-panel" type="button" title="Tutup" onClick={onClose}>
            <X className="h-5 w-5" />
          </button>
        </div>
        {message.metadata ? (
          <div className="mb-4 rounded border border-line bg-panel p-3 text-xs text-neutral-700">
            {message.metadata.intent ? <div>Intent: {String(message.metadata.intent)}</div> : null}
            {message.metadata.retrieval_mode ? <div>Mode retrieval: {String(message.metadata.retrieval_mode)}</div> : null}
            {message.metadata.language_detected ? <div>Bahasa: {String(message.metadata.language_detected)}</div> : null}
            {typeof message.metadata.retrieved_context_count === "number" ? <div>Konteks ditemukan: {message.metadata.retrieved_context_count}</div> : null}
            {typeof message.metadata.prompt_context_chunk_count === "number" ? <div>Chunk ke prompt: {message.metadata.prompt_context_chunk_count}</div> : null}
            {typeof message.metadata.indexed_context_count === "number" ? <div>Indexed contexts: {message.metadata.indexed_context_count}</div> : null}
            {typeof message.metadata.web_context_count === "number" ? <div>Live web contexts: {message.metadata.web_context_count}</div> : null}
            {typeof message.metadata.agent_tool_calls === "number" ? <div>Tool calls: {message.metadata.agent_tool_calls}</div> : null}
            {typeof message.metadata.retrieval_fallback_used === "boolean" ? <div>Fallback retrieval: {message.metadata.retrieval_fallback_used ? "dipakai" : "tidak"}</div> : null}
            {typeof message.metadata.cache_hit === "boolean" ? <div>Cache: {message.metadata.cache_hit ? "hit" : "miss"}</div> : null}
            {message.provider_used ? <div>Provider: {message.provider_used}</div> : null}
            {message.model_used ? <div>Model: {message.model_used}</div> : null}
          </div>
        ) : null}
        {steps.length ? (
          <ol className="space-y-3">
            {steps.map((step, index) => {
              const normalized = typeof step === "string" ? { id: `${index}`, label: step, status: "done", detail: "", metadata: {} } : step;
              const metadata = formatMetadata(normalized.metadata);
              return (
                <li key={`${normalized.id}-${index}`} className="flex gap-3 border-l border-line pl-3">
                  <StepIcon status={normalized.status} />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-ink">{normalized.label}</div>
                    {normalized.detail ? <div className="mt-1 text-xs leading-5 text-neutral-600">{normalized.detail}</div> : null}
                    {metadata ? <div className="mt-1 text-xs text-neutral-500">{metadata}</div> : null}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="rounded border border-line bg-panel p-3 text-sm text-neutral-600">Belum ada langkah operasional tersimpan untuk pesan ini.</div>
        )}
      </aside>
    </div>
  );
}

function markdownWithCitationLinks(content: unknown) {
  return String(content || "").replace(/\[(\d+)\]/g, "[$&](#citation-$1)");
}

function displayText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.answer === "string") return record.answer;
    if (typeof record.content === "string") return record.content;
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

function MarkdownAnswer({ content, onCitationClick }: { content: unknown; onCitationClick: (id: number) => void }) {
  return (
    <div className="text-sm leading-6">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li className="leading-6">{children}</li>,
          h1: ({ children }) => <h1 className="mb-2 text-lg font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 text-sm font-semibold">{children}</h3>,
          table: ({ children }) => <table className="my-2 w-full border-collapse text-left text-xs">{children}</table>,
          th: ({ children }) => <th className="border border-line bg-panel px-2 py-1 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-line px-2 py-1 align-top">{children}</td>,
          blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-brand pl-3 text-neutral-700">{children}</blockquote>,
          code: ({ children, className }) => {
            const block = Boolean(className);
            return block ? (
              <code className="block overflow-x-auto rounded bg-neutral-900 p-3 text-xs text-white">{children}</code>
            ) : (
              <code className="rounded bg-panel px-1 py-0.5 text-xs">{children}</code>
            );
          },
          a: ({ href, children }) => {
            if (href?.startsWith("#citation-")) {
              const id = Number(href.replace("#citation-", ""));
              return (
                <button
                  className="mx-0.5 inline-flex h-5 items-center rounded bg-brand/10 px-1.5 text-xs font-medium text-brand hover:bg-brand/20"
                  type="button"
                  onClick={() => onCitationClick(id)}
                >
                  {children}
                </button>
              );
            }
            return (
              <a className="text-brand underline underline-offset-2" href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          }
        }}
      >
        {markdownWithCitationLinks(content)}
      </ReactMarkdown>
    </div>
  );
}

export function MessageBubble({ message, onRegenerate }: { message: ChatMessage; onRegenerate?: () => void }) {
  const isUser = message.role === "user";
  const [menuOpen, setMenuOpen] = useState(false);
  const [stepsOpen, setStepsOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"helpful" | "not_helpful" | null>(null);
  const [highlightedCitationId, setHighlightedCitationId] = useState<number | null>(null);
  const [showAllSources, setShowAllSources] = useState(false);
  const answerText = displayText(message.content);
  const sources = message.sources || [];
  const visibleSources = showAllSources ? sources : sources.slice(0, MAX_VISIBLE_SOURCES);

  async function sendFeedback(rating: "helpful" | "not_helpful") {
    setFeedback(rating);
    try {
      await api.feedback(message.id, rating);
    } catch {
      setFeedback(null);
    }
  }

  async function copyAnswer() {
    await navigator.clipboard.writeText(answerText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  function selectCitation(id: number) {
    setHighlightedCitationId(id);
    if (id > MAX_VISIBLE_SOURCES) setShowAllSources(true);
    window.setTimeout(() => document.getElementById(`citation-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 0);
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[880px] rounded px-4 py-3 ${isUser ? "bg-brand text-white" : "bg-white text-ink border border-line"}`}>
        {isUser ? <div className="whitespace-pre-wrap text-sm leading-6">{answerText}</div> : <MarkdownAnswer content={answerText} onCitationClick={selectCitation} />}
        {!isUser && message.not_found ? (
          <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
            Belum ada jawaban resmi yang cocok. Untuk bantuan lebih lanjut, hubungi dukungan resmi UMB:{" "}
            <a href="https://mercubuana.ac.id" target="_blank" rel="noreferrer" className="font-medium underline">Situs Resmi UMB</a>
            {" • "}
            <a href="https://pmb.mercubuana.ac.id" target="_blank" rel="noreferrer" className="font-medium underline">PMB UMB</a>
          </div>
        ) : null}
        {!isUser ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            {message.confidence ? <span className={`rounded px-2 py-1 ${confidenceClass(message.confidence)}`}>{message.confidence}</span> : null}
            {message.provider_used ? <span className="rounded bg-panel px-2 py-1 text-neutral-700">{message.provider_used}</span> : null}
            {message.model_used ? <span className="rounded bg-panel px-2 py-1 text-neutral-700">{message.model_used}</span> : null}
          </div>
        ) : null}
        {!isUser ? (
          <div className="relative mt-3 flex items-center gap-1 text-neutral-600">
            <button className={`rounded p-2 hover:bg-panel ${feedback === "helpful" ? "text-brand" : ""}`} type="button" title="Jawaban membantu" onClick={() => sendFeedback("helpful")}>
              <ThumbsUp className="h-4 w-4" />
            </button>
            <button className={`rounded p-2 hover:bg-panel ${feedback === "not_helpful" ? "text-red-700" : ""}`} type="button" title="Jawaban tidak membantu" onClick={() => sendFeedback("not_helpful")}>
              <ThumbsDown className="h-4 w-4" />
            </button>
            <button className="rounded p-2 hover:bg-panel disabled:opacity-40" type="button" title="Regenerate" disabled={!onRegenerate} onClick={onRegenerate}>
              <RefreshCcw className="h-4 w-4" />
            </button>
            <button className="rounded p-2 hover:bg-panel" type="button" title={copied ? "Tersalin" : "Salin jawaban"} onClick={copyAnswer}>
              {copied ? <Check className="h-4 w-4 text-emerald-700" /> : <Copy className="h-4 w-4" />}
            </button>
            <button className="rounded p-2 hover:bg-panel" type="button" title="Opsi lainnya" onClick={() => setMenuOpen((open) => !open)}>
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuOpen ? (
              <div className="absolute left-0 top-10 z-20 w-56 rounded border border-line bg-white p-1 text-sm shadow-lg">
                <button
                  className="w-full rounded px-3 py-2 text-left hover:bg-panel"
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setStepsOpen(true);
                  }}
                >
                  Lihat detail proses
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
        {!isUser && sources.length ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {visibleSources.map((source, index) => {
              const citationId = source.citation_id ?? index + 1;
              return (
                <div key={`${source.url}-${source.page_number ?? ""}-${source.slide_number ?? ""}-${source.sheet_name ?? ""}-${index}`} id={`citation-${citationId}`}>
                  <SourceCard source={{ ...source, citation_id: citationId }} highlighted={highlightedCitationId === citationId} />
                </div>
              );
            })}
            {sources.length > MAX_VISIBLE_SOURCES ? (
              <button
                type="button"
                className="rounded border border-line bg-white px-3 py-2 text-left text-sm text-neutral-700 transition hover:border-brand md:col-span-2"
                onClick={() => setShowAllSources((value) => !value)}
              >
                {showAllSources ? "Sembunyikan sumber tambahan" : `Tampilkan ${sources.length - MAX_VISIBLE_SOURCES} sumber lainnya`}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {stepsOpen ? <StepsDrawer message={message} onClose={() => setStepsOpen(false)} /> : null}
    </div>
  );
}
