"use client";

import { Plus } from "lucide-react";

export function NewChatButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="flex w-full items-center justify-center gap-2 rounded bg-brand px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-teal-800"
      onClick={onClick}
      title="Mulai chat baru"
    >
      <Plus className="h-4 w-4" aria-hidden />
      New Chat
    </button>
  );
}

