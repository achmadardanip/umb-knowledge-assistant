"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import {
  getAnonymousSessionId,
  getLastActiveSession,
  getMemoryEnabled,
  getRetrievalMode,
  getSelectedProvider,
  setLastActiveSession,
  setMemoryEnabled,
  setRetrievalMode,
  setSelectedProvider
} from "../lib/localStorage";
import type { ChatMessage, ChatResponse, ChatSession, ProviderId, ProviderOption, RetrievalMode } from "../lib/types";
import { useChatMessages } from "../hooks/useChatMessages";
import { useChatSessions } from "../hooks/useChatSessions";
import { ChatInput } from "./ChatInput";
import { ChatSidebar } from "./ChatSidebar";
import { DeleteChatDialog } from "./DeleteChatDialog";
import { ExamplePrompts } from "./ExamplePrompts";
import { MessageBubble } from "./MessageBubble";
import { RenameChatDialog } from "./RenameChatDialog";
import { ThinkingSteps } from "./ThinkingSteps";

declare global {
  interface Window {
    puter?: { ai?: { chat?: (messages: unknown, opts?: unknown) => Promise<unknown> } };
  }
}

const MIN_PROGRESS_MS = 1200;

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function mergeStep(current: NonNullable<ChatMessage["visible_steps"]>, incoming: string | NonNullable<ChatMessage["visible_steps"]>[number]) {
  if (typeof incoming === "string") {
    return current.includes(incoming) ? current : [...current, incoming];
  }
  const index = current.findIndex((step) => typeof step !== "string" && step.id === incoming.id);
  if (index === -1) return [...current, incoming];
  const next = [...current];
  next[index] = incoming;
  return next;
}

export function ChatWidget() {
  const [anonymousId, setAnonymousId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [selectedProviderState, setSelectedProviderState] = useState<ProviderId>("openrouter");
  const [providerOptions, setProviderOptions] = useState<ProviderOption[]>([]);
  const [retrievalModeState, setRetrievalModeState] = useState<RetrievalMode>("indexed");
  const [memoryEnabledState, setMemoryEnabledState] = useState(true);
  const [sending, setSending] = useState(false);
  const [steps, setSteps] = useState<NonNullable<ChatMessage["visible_steps"]>>([]);
  const [error, setError] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<ChatSession | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null);

  const { sessions, refresh: refreshSessions } = useChatSessions(anonymousId);
  const { messages, setMessages, refresh: refreshMessages } = useChatMessages(activeSessionId);

  useEffect(() => {
    const anon = getAnonymousSessionId();
    setAnonymousId(anon);
    setSelectedProviderState(getSelectedProvider());
    setRetrievalModeState(getRetrievalMode());
    setMemoryEnabledState(getMemoryEnabled());
    setActiveSessionId(getLastActiveSession());
  }, []);

  useEffect(() => {
    api.providers()
      .then((payload) => {
        const visibleProviders = payload.providers.filter((provider) => provider.id !== "hermes" || provider.configured);
        setProviderOptions(visibleProviders);
        if (selectedProviderState === "hermes" && !visibleProviders.some((provider) => provider.id === "hermes")) {
          chooseProvider(payload.default_provider === "hermes" ? "openrouter" : payload.default_provider);
        }
      })
      .catch(() => undefined);
  }, [selectedProviderState]);

  useEffect(() => {
    refreshSessions()
      .then(() => setError(null))
      .catch((err) => setError(err.message));
  }, [refreshSessions]);

  useEffect(() => {
    refreshMessages()
      .then(() => setError(null))
      .catch((err) => setError(err.message));
  }, [refreshMessages]);

  const activeTitle = useMemo(() => sessions.find((session) => session.session_id === activeSessionId)?.title || "UMB Knowledge Assistant", [sessions, activeSessionId]);

  function chooseProvider(provider: ProviderId) {
    setSelectedProviderState(provider);
    setSelectedProvider(provider);
  }

  function chooseRetrievalMode(mode: RetrievalMode) {
    setRetrievalModeState(mode);
    setRetrievalMode(mode);
  }

  async function newChat() {
    setActiveSessionId(null);
    setMessages([]);
    setLastActiveSession("");
  }

  function selectSession(sessionId: string) {
    setActiveSessionId(sessionId);
    setLastActiveSession(sessionId);
  }

  async function ensureSession() {
    if (activeSessionId) return activeSessionId;
    if (!anonymousId) throw new Error("Anonymous session belum siap.");
    const created = (await api.createSession(anonymousId)) as ChatSession;
    setActiveSessionId(created.session_id);
    setLastActiveSession(created.session_id);
    await refreshSessions();
    return created.session_id;
  }

  async function runPuterChat(payload: Parameters<typeof api.chatPrepare>[0]): Promise<ChatResponse> {
    const prep = await api.chatPrepare(payload);
    if (prep.mode === "final" || !prep.prepare_id || !prep.messages) {
      return prep as ChatResponse; // terminal: clarify / blocked / cache / not_found
    }
    (prep.visible_steps || []).forEach((step) => setSteps((current) => mergeStep(current, step)));
    let text = "";
    try {
      const resp = (await window.puter!.ai!.chat!(prep.messages, { model: "gpt-4o-mini" })) as any;
      text = typeof resp === "string" ? resp : resp?.message?.content ?? resp?.text ?? String(resp ?? "");
    } catch {
      throw new Error("Puter.js gagal menghasilkan jawaban di browser. Pilih provider lain atau coba lagi.");
    }
    return api.chatFinalize({ prepare_id: prep.prepare_id, answer: text, model_used: "gpt-4o-mini" });
  }

  async function send(question: string, regenerateFromMessageId?: string | null) {
    if (!anonymousId) return;
    setError(null);
    setSending(true);
    setSteps([]);
    const startedAt = Date.now();
    const optimisticUser: ChatMessage = { id: `user-${Date.now()}`, role: "user", content: question };
    setMessages((current) => [...current, optimisticUser]);
    try {
      const sessionId = await ensureSession();
      // "puter" is a browser-side provider; the backend never sees it as a provider_override.
      const usePuter =
        selectedProviderState === "puter" && typeof window !== "undefined" && Boolean(window.puter?.ai?.chat);
      const requestPayload = {
        session_id: sessionId,
        anonymous_session_id: anonymousId,
        question,
        top_k: 5,
        provider_override: selectedProviderState === "puter" ? null : selectedProviderState,
        memory_enabled: memoryEnabledState,
        regenerate_from_message_id: regenerateFromMessageId || null,
        retrieval_mode: retrievalModeState
      };
      const result = usePuter
        ? await runPuterChat(requestPayload)
        : await api.chatStream(requestPayload, {
            onStep: (step) => {
              setSteps((current) => mergeStep(current, step));
            },
            onError: (message) => setError(message)
          });
      const elapsed = Date.now() - startedAt;
      if (elapsed < MIN_PROGRESS_MS) {
        await wait(MIN_PROGRESS_MS - elapsed);
      }
      const assistant: ChatMessage = {
        id: result.message_id,
        role: "assistant",
        content: result.answer,
        sources: result.sources,
        confidence: result.confidence,
        provider_used: result.provider_used,
        model_used: result.model_used,
        not_found: result.not_found,
        visible_steps: result.visible_steps || [],
        follow_up_questions: result.follow_up_questions || [],
        metadata: {
          memory_used: result.memory_used,
          intent: result.intent,
          retrieval_mode: result.retrieval_mode,
          language_detected: result.language_detected,
          retrieved_context_count: result.retrieved_context_count,
          prompt_context_chunk_count: result.prompt_context_chunk_count,
          indexed_context_count: result.indexed_context_count,
          web_context_count: result.web_context_count,
          agent_tool_calls: result.agent_tool_calls,
          retrieval_fallback_used: result.retrieval_fallback_used,
          retrieval_warnings: result.retrieval_warnings
        }
      };
      setMessages((current) => [...current.filter((message) => message.id !== optimisticUser.id), optimisticUser, assistant]);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal mengirim pesan.");
    } finally {
      setSteps([]);
      setSending(false);
    }
  }

  async function renameSession(session: ChatSession, title: string) {
    await api.renameSession(session.session_id, title);
    setRenameTarget(null);
    await refreshSessions();
  }

  async function deleteSession(session: ChatSession) {
    await api.deleteSession(session.session_id);
    if (session.session_id === activeSessionId) {
      setActiveSessionId(null);
      setMessages([]);
    }
    setDeleteTarget(null);
    await refreshSessions();
  }

  function toggleMemory(enabled: boolean) {
    setMemoryEnabledState(enabled);
    setMemoryEnabled(enabled);
    if (activeSessionId) {
      api.memoryToggle(activeSessionId, enabled).catch(() => undefined);
    }
  }

  return (
    <main className="flex h-dvh min-h-dvh flex-col overflow-hidden md:flex-row">
      <div className="hidden shrink-0 md:block">
        <ChatSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          selectedProvider={selectedProviderState}
          providerOptions={providerOptions}
          memoryEnabled={memoryEnabledState}
          onProviderChange={chooseProvider}
          onMemoryChange={toggleMemory}
          onNewChat={newChat}
          onSelectSession={selectSession}
          onRenameSession={setRenameTarget}
          onDeleteSession={setDeleteTarget}
        />
      </div>
      <section className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="max-h-48 shrink-0 overflow-y-auto border-b border-line md:hidden">
          <ChatSidebar
            sessions={sessions}
            activeSessionId={activeSessionId}
            selectedProvider={selectedProviderState}
            providerOptions={providerOptions}
            memoryEnabled={memoryEnabledState}
            onProviderChange={chooseProvider}
            onMemoryChange={toggleMemory}
            onNewChat={newChat}
            onSelectSession={selectSession}
            onRenameSession={setRenameTarget}
            onDeleteSession={setDeleteTarget}
          />
        </div>
        <header className="shrink-0 border-b border-line bg-white px-4 py-4">
          <div className="mx-auto max-w-4xl">
            <h1 className="text-xl font-semibold">{activeTitle}</h1>
            <p className="text-sm text-neutral-600">Asisten informasi publik berbasis sumber resmi Universitas Mercu Buana</p>
          </div>
        </header>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-5 pb-28 md:pb-5">
          <div className="mx-auto flex max-w-4xl flex-col gap-4">
            {!messages.length ? (
              <div className="mt-4 md:mt-10">
                <h2 className="mb-2 text-lg font-semibold">UMB Knowledge Assistant</h2>
                <p className="mb-5 max-w-2xl text-sm leading-6 text-neutral-700">
                  Tanyakan informasi publik UMB. Sistem akan menjawab hanya dari sumber resmi yang sudah diindeks dan menampilkan sitasi.
                </p>
                <ExamplePrompts onPick={send} />
              </div>
            ) : (
              messages.map((message, index) => {
                const previousUser = [...messages.slice(0, index)].reverse().find((item) => item.role === "user");
                return <MessageBubble key={message.id} message={message} onRegenerate={message.role === "assistant" && previousUser ? () => send(previousUser.content, message.id) : undefined} />;
              })
            )}
            {!sending &&
            messages.length > 0 &&
            messages[messages.length - 1].role === "assistant" &&
            (messages[messages.length - 1].follow_up_questions?.length ?? 0) > 0 ? (
              <div className="flex flex-wrap gap-2">
                <span className="w-full text-xs font-medium text-neutral-500">Pertanyaan lanjutan</span>
                {messages[messages.length - 1].follow_up_questions!.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => send(q)}
                    className="rounded-full border border-line bg-white px-3 py-1.5 text-sm transition hover:border-brand"
                  >
                    {q}
                  </button>
                ))}
              </div>
            ) : null}
            {sending ? <ThinkingSteps steps={steps} /> : null}
            {error ? <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div> : null}
          </div>
        </div>
        <ChatInput disabled={sending} onSend={send} retrievalMode={retrievalModeState} onRetrievalModeChange={chooseRetrievalMode} />
      </section>
      {renameTarget ? <RenameChatDialog currentTitle={renameTarget.title} onCancel={() => setRenameTarget(null)} onConfirm={(title) => renameSession(renameTarget, title)} /> : null}
      {deleteTarget ? <DeleteChatDialog title={deleteTarget.title} onCancel={() => setDeleteTarget(null)} onConfirm={() => deleteSession(deleteTarget)} /> : null}
    </main>
  );
}
