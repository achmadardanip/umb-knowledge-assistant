"use client";

import { useCallback, useState } from "react";
import { api } from "../lib/api";
import type { ChatMessage } from "../lib/types";

export function useChatMessages(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    setLoading(true);
    try {
      const payload = (await api.messages(sessionId)) as { messages: ChatMessage[] };
      setMessages(payload.messages);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  return { messages, setMessages, loading, refresh };
}

