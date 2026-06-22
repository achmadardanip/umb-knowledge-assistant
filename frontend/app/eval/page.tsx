"use client";

import { useCallback, useRef, useState } from "react";
import { RagResult, startRun, streamRun } from "../lib/ragEval";

export default function EvalPage() {
  const [status, setStatus] = useState<"idle" | "running" | "completed" | "failed">("idle");
  const [rows, setRows] = useState<RagResult[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [agg, setAgg] = useState<{ f: number | null; r: number | null }>({ f: null, r: null });
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    setError(null);
    setRows([]);
    setProgress({ done: 0, total: 0 });
    setStatus("running");
    try {
      const runId = await startRun();
      abortRef.current = new AbortController();
      await streamRun(runId, {
        signal: abortRef.current.signal,
        onResult: (r) => {
          setRows((prev) => [...prev, r]);
          if (r.n_done && r.n_total) setProgress({ done: r.n_done, total: r.n_total });
          setAgg({ f: r.agg_faithfulness ?? null, r: r.agg_relevance ?? null });
        },
        onDone: (d) => {
          setAgg({ f: d.agg_faithfulness ?? null, r: d.agg_relevance ?? null });
          setStatus("completed");
        },
        onError: (msg) => {
          setError(msg);
          setStatus("failed");
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("failed");
    }
  }, []);

  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toFixed(2));
  const badge = (pass: boolean | null) =>
    pass == null ? "bg-gray-200 text-gray-700" : pass ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800";

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">RAG Evaluation</h1>
          <p className="text-sm text-muted-foreground">Faithfulness + answer-relevance · local Ollama judge · report-only</p>
        </div>
        <button
          onClick={run}
          disabled={status === "running"}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          {status === "running" ? "Running…" : "Run evaluation"}
        </button>
      </header>

      {error && <div className="rounded-md bg-red-100 text-red-800 p-3 text-sm">{error}</div>}

      <section className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border p-4">
          <div className="text-xs text-muted-foreground">Progress</div>
          <div className="text-xl font-semibold">{progress.done}/{progress.total || "—"}</div>
          <div className="mt-2 h-2 w-full rounded bg-gray-200">
            <div className="h-2 rounded bg-primary transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-xs text-muted-foreground">Faithfulness (avg)</div>
          <div className="text-xl font-semibold">{fmt(agg.f)}</div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-xs text-muted-foreground">Relevance (avg)</div>
          <div className="text-xl font-semibold">{fmt(agg.r)}</div>
        </div>
      </section>

      <section className="rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40">
            <tr className="text-left">
              <th className="p-3">Question</th>
              <th className="p-3">Intent</th>
              <th className="p-3">Faithful</th>
              <th className="p-3">Relevant</th>
              <th className="p-3">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.question_id}-${i}`} className="border-b align-top">
                <td className="p-3">{r.question}</td>
                <td className="p-3">{r.intent ?? "—"}</td>
                <td className="p-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${badge(r.faithfulness_pass)}`}>
                    {r.not_found ? "n/a" : fmt(r.faithfulness_score)}
                  </span>
                </td>
                <td className="p-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${badge(r.relevance_pass)}`}>{fmt(r.relevance_score)}</span>
                </td>
                <td className="p-3 text-xs text-muted-foreground">
                  {r.not_found ? "not_found " : ""}{r.grader_error ? "grader_error" : ""}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td className="p-4 text-muted-foreground" colSpan={5}>No results yet — start a run.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </main>
  );
}
