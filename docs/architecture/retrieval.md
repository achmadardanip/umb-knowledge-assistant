# Retrieval Pipeline

## Purpose
Return the most relevant, **official** UMB contexts for a query, pinning deterministic
structured answers (entity/FAQ/graph) above vector results, so answers are grounded and cited.

## Flow
```
query → detect_retrieval_intent → build contextual query (history + session memory)
  → structured contexts:  FAQ  +  Entity (query_entities)  +  typed-graph relations
  → vector contexts:      HybridRetriever.search = keyword(ILIKE) + dense(pgvector HNSW) → RRF fusion
  → host-authority + topic prior; browse-index filter (_is_browse_index_url)
  → reranker (optional) → top-k → answer_generator (citations) → verification gate
```
Non-demoted structured contexts are pinned above vector; intent-demoted ones rejoin the
vector pool and compete by score.

## Key files
- `app/retrieval/intent_gate.py` — `detect_retrieval_intent`.
- `app/retrieval/hybrid_retriever.py` — keyword+dense fusion, TAHF scoring, browse filter.
- `app/retrieval/reranker.py` — cross-encoder reranking (optional).
- `app/agent/umb_agent.py` — `run_umb_agent` orchestration.
- `app/evaluation/benchmark.py` — `agent_hybrid` (production) vs `agent` (dense lower-bound).

## APIs
`/chat`, `/chat/stream` (internally call the agent). No public retrieval-only endpoint.

## Benchmarks
Production `agent_hybrid`: **official_top 0.998, citation_failure 0.0, follow_up 1.0**.
`agent` (pure dense) is a pessimistic lower bound (0.982) — always report `agent_hybrid`.

## Risks
- The dense-only path under-retrieves topical FAQ queries (mitigated by the hybrid path).
- Reranker adds latency; disabled in the fast benchmark path.

## Future improvements
- FAQ coverage expansion for the dense lower bound; learned fusion weights; cached reranking.
