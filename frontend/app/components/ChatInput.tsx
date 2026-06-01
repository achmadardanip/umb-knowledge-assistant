"use client";

import { Database, Globe2, Layers3, SendHorizontal } from "lucide-react";
import { KeyboardEvent, useState } from "react";
import type { RetrievalMode } from "../lib/types";

const MODES: Array<{ id: RetrievalMode; label: string; icon: typeof Database; title: string }> = [
  { id: "indexed", label: "Indexed", icon: Database, title: "Gunakan database RAG yang sudah diindeks" },
  { id: "web", label: "Web", icon: Globe2, title: "Cari live di domain resmi UMB, lalu fallback ke indexed jika kosong" },
  { id: "hybrid", label: "Hybrid", icon: Layers3, title: "Gabungkan indexed RAG dan live web UMB" }
];

export function ChatInput({
  disabled,
  onSend,
  retrievalMode,
  onRetrievalModeChange
}: {
  disabled?: boolean;
  onSend: (value: string) => void;
  retrievalMode: RetrievalMode;
  onRetrievalModeChange: (mode: RetrievalMode) => void;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    setValue("");
    onSend(trimmed);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="relative z-10 shrink-0 border-t border-line bg-panel p-3">
      <div className="mx-auto max-w-4xl rounded border border-line bg-white p-2 shadow-sm">
        <textarea
          className="max-h-40 min-h-12 w-full resize-none bg-transparent px-2 py-2 text-sm outline-none"
          placeholder="Tanyakan informasi publik resmi UMB..."
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
        />
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1 rounded border border-line bg-panel p-1">
            {MODES.map((mode) => {
              const Icon = mode.icon;
              const active = retrievalMode === mode.id;
              return (
                <button
                  key={mode.id}
                  className={`flex h-8 items-center gap-1.5 rounded px-2 text-xs transition ${active ? "bg-white text-brand shadow-sm" : "text-neutral-600 hover:bg-white"}`}
                  type="button"
                  title={mode.title}
                  aria-pressed={active}
                  disabled={disabled}
                  onClick={() => onRetrievalModeChange(mode.id)}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  <span>{mode.label}</span>
                </button>
              );
            })}
          </div>
          <button className="grid h-10 w-10 place-items-center rounded bg-brand text-white disabled:opacity-50" type="button" onClick={submit} disabled={disabled || !value.trim()} title="Kirim">
            <SendHorizontal className="h-5 w-5" aria-hidden />
          </button>
        </div>
      </div>
      <p className="mx-auto mt-2 max-w-4xl text-xs text-neutral-600">
        Jawaban dihasilkan berdasarkan sumber publik resmi yang berhasil diindeks. Untuk keputusan akademik/administratif penting, tetap verifikasi ke unit resmi UMB.
      </p>
    </div>
  );
}
