"use client";

import { Brain } from "lucide-react";

export function MemoryIndicator({ enabled, onChange }: { enabled: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded border border-line bg-white px-3 py-2 text-sm">
      <span className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-mango" aria-hidden />
        Memori
      </span>
      <input
        className="h-4 w-4 accent-brand"
        type="checkbox"
        checked={enabled}
        onChange={(event) => onChange(event.target.checked)}
        title="Aktifkan memori chat aman"
      />
    </label>
  );
}

