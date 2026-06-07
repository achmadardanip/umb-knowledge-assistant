export type ProviderId = "openrouter" | "openai" | "gemini" | "anthropic" | "hermes";
export type RetrievalMode = "indexed" | "web" | "hybrid";

export type ProviderOption = {
  id: ProviderId;
  label: string;
  configured: boolean;
  model: string;
};

export type AgentStep = {
  id: string;
  label: string;
  status: "running" | "done" | "skipped" | "error";
  detail?: string | null;
  metadata?: Record<string, unknown>;
};

export type Source = {
  citation_id?: number;
  title?: string;
  url: string;
  hostname?: string;
  source_type?: string;
  relevance_score?: number;
  score?: number;
  page_number?: number | null;
  slide_number?: number | null;
  sheet_name?: string | null;
  row_range?: string | null;
  timestamp_start?: number | null;
  timestamp_end?: number | null;
  extraction_method?: string | null;
  extraction_confidence?: number | null;
  discovery_source?: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sources?: Source[];
  confidence?: "high" | "medium" | "low" | null;
  provider_used?: string | null;
  model_used?: string | null;
  not_found?: boolean;
  visible_steps?: Array<string | AgentStep>;
  follow_up_questions?: string[];
  created_at?: string;
  metadata?: Record<string, unknown> & {
    intent?: string;
    retrieved_context_count?: number;
    prompt_context_chunk_count?: number;
    cache_hit?: boolean;
    retrieval_mode?: RetrievalMode;
    language_detected?: string;
    indexed_context_count?: number;
    web_context_count?: number;
    agent_tool_calls?: number;
    retrieval_fallback_used?: boolean;
    retrieval_warnings?: string[];
  };
};

export type ChatSession = {
  session_id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  last_message_at?: string;
  memory_enabled?: boolean;
};

export type ChatResponse = {
  session_id: string;
  message_id: string;
  answer: string;
  sources: Source[];
  confidence: "high" | "medium" | "low";
  not_found: boolean;
  provider_used: string;
  model_used: string;
  memory_used: boolean;
  chat_title: string;
  visible_steps?: AgentStep[];
  follow_up_questions?: string[];
  intent?: string;
  retrieval_mode?: RetrievalMode;
  language_detected?: string;
  retrieved_context_count?: number;
  prompt_context_chunk_count?: number;
  indexed_context_count?: number;
  web_context_count?: number;
  agent_tool_calls?: number;
  retrieval_fallback_used?: boolean;
  retrieval_warnings?: string[];
};
