"use client";

import { MessageSquare, Pencil, Trash2 } from "lucide-react";
import type { ChatSession } from "../lib/types";

export function ChatHistoryItem({
  session,
  active,
  onSelect,
  onRename,
  onDelete
}: {
  session: ChatSession;
  active: boolean;
  onSelect: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={`group flex items-center gap-2 rounded px-2 py-2 text-sm ${active ? "bg-skysoft text-ink" : "hover:bg-white"}`}>
      <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={onSelect} title={session.title}>
        <MessageSquare className="h-4 w-4 shrink-0 text-brand" aria-hidden />
        <span className="truncate">{session.title}</span>
      </button>
      <button className="rounded p-1 opacity-70 hover:bg-panel hover:opacity-100" onClick={onRename} title="Ganti nama">
        <Pencil className="h-4 w-4" aria-hidden />
      </button>
      <button className="rounded p-1 opacity-70 hover:bg-panel hover:opacity-100" onClick={onDelete} title="Hapus chat">
        <Trash2 className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

