"use client";

import { Cpu } from "lucide-react";
import type { ProviderId } from "../lib/types";

const OPTIONS: Array<{ id: ProviderId; label: string }> = [
  { id: "openrouter", label: "OpenRouter" },
  { id: "openai", label: "OpenAI" },
  { id: "gemini", label: "Gemini" },
  { id: "anthropic", label: "Claude" }
];

export function ProviderSelector({ value, onChange }: { value: ProviderId; onChange: (provider: ProviderId) => void }) {
  return (
    <label className="flex items-center gap-2 rounded border border-line bg-white px-3 py-2 text-sm">
      <Cpu className="h-4 w-4 text-brand" aria-hidden />
      <select className="min-w-0 flex-1 bg-transparent outline-none" value={value} onChange={(event) => onChange(event.target.value as ProviderId)}>
        {OPTIONS.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

