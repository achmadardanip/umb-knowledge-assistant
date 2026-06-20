"use client";

import { Database, Globe2, Layers3, SendHorizontal, Square, Mic, Paperclip, X } from "lucide-react";
import { KeyboardEvent, useState } from "react";
import type { RetrievalMode } from "../lib/types";
import { Button } from "./ui/button";
import { Tooltip, TooltipTrigger, TooltipContent } from "./ui/tooltip";
import { cn } from "../lib/utils";

const MODES: Array<{ id: RetrievalMode; label: string; icon: typeof Database; title: string }> = [
  { id: "indexed", label: "Indexed", icon: Database, title: "Gunakan database RAG yang sudah diindeks" },
  { id: "web", label: "Web", icon: Globe2, title: "Cari live di domain resmi UMB, lalu fallback ke indexed jika kosong" },
  { id: "hybrid", label: "Hybrid", icon: Layers3, title: "Gabungkan indexed RAG dan live web UMB" },
];

export function ChatInput({
  disabled,
  sending,
  onStop,
  onSend,
  retrievalMode,
  onRetrievalModeChange,
}: {
  disabled?: boolean;
  sending?: boolean;
  onStop?: () => void;
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
    } else if (event.key === "Escape" && sending) {
      // Esc stops an in-flight generation (Phase 20 P20.2 keyboard shortcut).
      event.preventDefault();
      onStop?.();
    }
  }

  return (
    <div className="relative z-10 shrink-0 border-t border-border bg-card p-3">
      <div className="mx-auto max-w-4xl rounded-lg border border-border bg-background p-2 shadow-sm focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-primary/30">
        <div className="relative">
          <textarea
            className="max-h-40 min-h-12 w-full resize-none bg-transparent px-2 py-2 pr-8 text-sm text-foreground outline-none placeholder:text-muted-foreground"
            placeholder="Tanyakan informasi publik resmi UMB…  (Enter kirim · Shift+Enter baris baru)"
            aria-label="Chat message input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={onKeyDown}
            disabled={disabled}
          />
          {value && !disabled && (
            <button
              type="button"
              aria-label="Clear input"
              onClick={() => setValue("")}
              className="absolute right-1 top-1 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1 rounded-md border border-border bg-muted p-1" role="group" aria-label="Retrieval mode">
            {MODES.map((mode) => {
              const Icon = mode.icon;
              const active = retrievalMode === mode.id;
              return (
                <button
                  key={mode.id}
                  className={cn(
                    "flex h-8 items-center gap-1.5 rounded px-2 text-xs transition-colors",
                    active ? "bg-background text-primary shadow-sm" : "text-muted-foreground hover:bg-background",
                  )}
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
          <div className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" disabled aria-label="Voice input (coming soon)"><Mic className="h-4 w-4" /></Button>
              </TooltipTrigger>
              <TooltipContent>Voice input — coming soon</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" disabled aria-label="Attach file (coming soon)"><Paperclip className="h-4 w-4" /></Button>
              </TooltipTrigger>
              <TooltipContent>Attachments — coming soon</TooltipContent>
            </Tooltip>
            {sending ? (
              <Button size="icon" variant="destructive" onClick={onStop} aria-label="Stop generating">
                <Square className="h-4 w-4 fill-current" aria-hidden />
              </Button>
            ) : (
              <Button size="icon" onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message">
                <SendHorizontal className="h-5 w-5" aria-hidden />
              </Button>
            )}
          </div>
        </div>
      </div>
      <p className="mx-auto mt-2 max-w-4xl text-xs text-muted-foreground">
        Jawaban dihasilkan dari sumber publik resmi yang terindeks. Untuk keputusan akademik/administratif penting, tetap verifikasi ke unit resmi UMB.
      </p>
    </div>
  );
}
