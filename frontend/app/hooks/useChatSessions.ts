"use client";

import { useCallback, useState } from "react";
import { api } from "../lib/api";
import type { ChatSession } from "../lib/types";

export function useChatSessions(anonymousSessionId: string | null) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!anonymousSessionId) return;
    setLoading(true);
    try {
      const payload = (await api.sessions(anonymousSessionId)) as { sessions: ChatSession[] };
      setSessions(payload.sessions);
    } finally {
      setLoading(false);
    }
  }, [anonymousSessionId]);

  return { sessions, setSessions, loading, refresh };
}

