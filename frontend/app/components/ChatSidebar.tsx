"use client";

import { ShieldCheck, GraduationCap } from "lucide-react";
import type { ChatSession, ProviderId, ProviderOption } from "../lib/types";
import { ChatHistoryItem } from "./ChatHistoryItem";
import { MemoryIndicator } from "./MemoryIndicator";
import { NewChatButton } from "./NewChatButton";
import { ProviderSelector } from "./ProviderSelector";
import { KbStats } from "./KbStats";
import { Separator } from "./ui/separator";

export function ChatSidebar({
  sessions,
  activeSessionId,
  selectedProvider,
  providerOptions,
  memoryEnabled,
  onProviderChange,
  onMemoryChange,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
  showBrand = true,
}: {
  sessions: ChatSession[];
  activeSessionId: string | null;
  selectedProvider: ProviderId;
  providerOptions?: ProviderOption[];
  memoryEnabled: boolean;
  onProviderChange: (provider: ProviderId) => void;
  onMemoryChange: (enabled: boolean) => void;
  onNewChat: () => void;
  onSelectSession: (sessionId: string) => void;
  onRenameSession: (session: ChatSession) => void;
  onDeleteSession: (session: ChatSession) => void;
  showBrand?: boolean;
}) {
  return (
    <aside className="flex h-full w-full flex-col gap-3 border-r border-border bg-card p-3 md:w-80">
      {showBrand && (
        <div className="flex items-center gap-2 px-1 pt-1">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <GraduationCap className="h-5 w-5" />
          </span>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-foreground">UMB Knowledge Assistant</div>
            <div className="text-[11px] text-muted-foreground">Official Sources Only</div>
          </div>
        </div>
      )}
      <NewChatButton onClick={onNewChat} />
      <ProviderSelector value={selectedProvider} options={providerOptions} onChange={onProviderChange} />
      <MemoryIndicator enabled={memoryEnabled} onChange={onMemoryChange} />
      <KbStats />
      <Separator />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Riwayat Chat</div>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {sessions.length === 0 ? (
            <p className="px-1 text-xs text-muted-foreground">Belum ada percakapan.</p>
          ) : (
            sessions.map((session) => (
              <ChatHistoryItem
                key={session.session_id}
                session={session}
                active={session.session_id === activeSessionId}
                onSelect={() => onSelectSession(session.session_id)}
                onRename={() => onRenameSession(session)}
                onDelete={() => onDeleteSession(session)}
              />
            ))
          )}
        </div>
      </div>
      <div className="rounded-md border border-border bg-background/60 p-3 text-xs text-muted-foreground">
        <div className="mb-1 flex items-center gap-2 font-medium text-foreground">
          <ShieldCheck className="h-4 w-4 text-primary" aria-hidden />
          System Status
        </div>
        Local PostgreSQL · pgvector · GraphRAG · citations required.
      </div>
    </aside>
  );
}
