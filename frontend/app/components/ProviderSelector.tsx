"use client";

import { Cpu } from "lucide-react";
import type { ProviderId, ProviderOption } from "../lib/types";

const FALLBACK_OPTIONS: ProviderOption[] = [
  { id: "local_ollama", label: "Local Ollama", configured: true, model: "" },
  { id: "puter", label: "Puter (browser fallback)", configured: true, model: "" },
  { id: "openrouter", label: "OpenRouter", configured: true, model: "" },
  { id: "openai", label: "OpenAI", configured: true, model: "" },
  { id: "gemini", label: "Gemini", configured: true, model: "" },
  { id: "anthropic", label: "Claude", configured: true, model: "" }
];

export function ProviderSelector({
  value,
  options = FALLBACK_OPTIONS,
  onChange
}: {
  value: ProviderId;
  options?: ProviderOption[];
  onChange: (provider: ProviderId) => void;
}) {
  const visibleOptions = (options.length ? options : FALLBACK_OPTIONS).filter((option) => option.id !== "hermes" || option.configured);
  return (
    <label className="flex items-center gap-2 rounded border border-line bg-white px-3 py-2 text-sm">
      <Cpu className="h-4 w-4 text-brand" aria-hidden />
      <select className="min-w-0 flex-1 bg-transparent outline-none" value={value} onChange={(event) => onChange(event.target.value as ProviderId)}>
        {visibleOptions.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
