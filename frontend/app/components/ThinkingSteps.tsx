"use client";

import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
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
  return <Circle className="mt-0.5 h-4 w-4 text-neutral-400" aria-hidden />;
}

export function ThinkingSteps({ steps }: { steps: Array<string | AgentStep> }) {
  if (!steps.length) return null;
  const normalized = steps.map(normalizeStep);
  return (
    <div className="rounded border border-line bg-white p-3 text-sm">
      <div className="mb-2 flex items-center gap-2 font-medium">
        <Loader2 className="h-4 w-4 animate-spin text-brand" aria-hidden />
        Memproses
      </div>
      <ol className="space-y-2 text-neutral-700">
        {normalized.map((step) => (
          <li key={`${step.id}-${step.status}`} className="flex gap-2">
            <StepIcon status={step.status} />
            <span>
              <span className="block leading-5">{step.label}</span>
              {step.detail ? <span className="block text-xs text-neutral-500">{step.detail}</span> : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
