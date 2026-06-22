"use client";

import { CheckCircle2, ChevronDown, ChevronUp, Circle, Loader2, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import type { AgentStep } from "../lib/types";

function normalizeStep(step: string | AgentStep): AgentStep {
  if (typeof step === "string") {
    return { id: step, label: step, status: "done" };
  }
  return step;
}

function StepIcon({ status }: { status: AgentStep["status"] }) {
  if (status === "running") return <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-brand" aria-hidden />;
  if (status === "done") return <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" aria-hidden />;
  if (status === "error") return <XCircle className="mt-0.5 h-4 w-4 text-red-600" aria-hidden />;
  return <Circle className="mt-0.5 h-4 w-4 text-muted-foreground" aria-hidden />;
}

function statusText(step?: AgentStep) {
  if (!step) return "Sedang berpikir";
  if (step.status === "error") return "Menyesuaikan pencarian";
  if (step.id.includes("retrieval") || step.id.includes("indexed") || step.id.includes("web") || step.id.includes("citation")) {
    return "Mencari sumber resmi";
  }
  if (step.id.includes("answer") || step.id.includes("provider") || step.id.includes("cache")) {
    return "Menyusun jawaban";
  }
  if (step.id.includes("memory") || step.id.includes("history") || step.id.includes("context") || step.id.includes("intent")) {
    return "Menganalisis konteks";
  }
  return "Memproses pertanyaan";
}

export function ThinkingSteps({ steps }: { steps: Array<string | AgentStep> }) {
  const normalized = steps.map(normalizeStep);
  const [open, setOpen] = useState(false);
  const activeStep = useMemo(() => {
    return [...normalized].reverse().find((step) => step.status === "running") || normalized[normalized.length - 1];
  }, [normalized]);

  return (
    <div className="rounded border border-line bg-card p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 font-medium text-foreground">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" aria-hidden />
          <span className="truncate">{statusText(activeStep)}</span>
        </div>
        <button
          className="inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-panel"
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? "Sembunyikan proses" : "Lihat proses"}
          {open ? <ChevronUp className="h-3.5 w-3.5" aria-hidden /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden />}
        </button>
      </div>
      {open ? (
        <ol className="mt-3 space-y-2 text-foreground">
          {normalized.length ? (
            normalized.map((step) => (
              <li key={`${step.id}-${step.status}`} className="flex gap-2">
                <StepIcon status={step.status} />
                <span>
                  <span className="block leading-5">{step.label}</span>
                  {step.detail ? <span className="block text-xs text-muted-foreground">{step.detail}</span> : null}
                </span>
              </li>
            ))
          ) : (
            <li className="text-xs text-muted-foreground">Menunggu progres dari server...</li>
          )}
        </ol>
      ) : null}
    </div>
  );
}
