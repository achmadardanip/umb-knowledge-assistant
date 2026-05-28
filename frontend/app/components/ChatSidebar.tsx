"use client";

import { ShieldCheck } from "lucide-react";
import type { ChatSession, ProviderId } from "../lib/types";
import { ChatHistoryItem } from "./ChatHistoryItem";
import { MemoryIndicator } from "./MemoryIndicator";
import { NewChatButton } from "./NewChatButton";
import { ProviderSelector } from "./ProviderSelector";

export function ChatSidebar({
  sessions,
  activeSessionId,
  selectedProvider,
  memoryEnabled,
  onProviderChange,
  onMemoryChange,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession
}: {
  sessions: ChatSession[];
  activeSessionId: string | null;
  selectedProvider: ProviderId;
  memoryEnabled: boolean;
  onProviderChange: (provider: ProviderId) => void;
  onMemoryChange: (enabled: boolean) => void;
  onNewChat: () => void;
  onSelectSession: (sessionId: string) => void;
  onRenameSession: (session: ChatSession) => void;
  onDeleteSession: (session: ChatSession) => void;
}) {
  return (
    <aside className="flex h-full w-full flex-col gap-3 border-r border-line bg-panel p-3 md:w-80">
      <NewChatButton onClick={onNewChat} />
      <ProviderSelector value={selectedProvider} onChange={onProviderChange} />
      <MemoryIndicator enabled={memoryEnabled} onChange={onMemoryChange} />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-600">Riwayat Chat</div>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {sessions.map((session) => (
            <ChatHistoryItem
              key={session.session_id}
              session={session}
              active={session.session_id === activeSessionId}
              onSelect={() => onSelectSession(session.session_id)}
              onRename={() => onRenameSession(session)}
              onDelete={() => onDeleteSession(session)}
            />
          ))}
        </div>
      </div>
      <div className="rounded border border-line bg-white p-3 text-xs text-neutral-700">
        <div className="mb-1 flex items-center gap-2 font-medium text-ink">
          <ShieldCheck className="h-4 w-4 text-brand" aria-hidden />
          Status Sistem
        </div>
        Public-only RAG, sitasi wajib, rahasia tetap di backend.
      </div>
    </aside>
  );
}

