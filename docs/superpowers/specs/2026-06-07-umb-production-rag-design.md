# UMB Knowledge Assistant — Production-Grade RAG: Whole-Program Design & Research Synthesis

- **Status:** Draft for review
- **Date:** 2026-06-07
- **Author:** Achmad Ardani Prasha (with Claude)
- **Scope:** Whole-program architecture + research synthesis. Decomposes into per-workstream specs (each gets its own spec → plan → build cycle).
- **Document purpose:** Academic + production grade. Citations justify each design decision; two original methods are proposed with ablation plans; the system must remain buildable.

---

## 1. Context & problem statement

The UMB Knowledge Assistant is an Indonesian-language, multimodal RAG chatbot intended to be the **single source of truth** for public information across `mercubuana.ac.id`, `*.mercubuana.ac.id`, `mercubuana.ac.id/*`, and `*.mercubuana.ac.id/*`. Answers must be grounded only in public official sources that were discovered, crawled, cleaned, indexed, and returned as cited RAG context. When no official context supports an answer, the system must abstain.

The knowledge is **dynamic** (fees, deadlines, schedules, contacts change), **multimodal** (HTML, PDF, DOCX, PPTX, spreadsheets, images/OCR, audio/video transcripts), and **adversarially exposed** (an in-scope host can be defaced or taken over, and crawled content flows into the model context).

### 1.1 Constraints (decided with stakeholder)

- **Document purpose:** academic + production (thesis/paper-grade rigor *and* buildable).
- **Infrastructure/budget:** flexible — GPU and/or managed services are acceptable.
- **Novelty appetite:** mostly proven methods, composed well, plus **1–2 invented methods** with ablation plans.
- **Scale target:** campus-wide (tens of thousands of potential users; bursty load around admissions/registration).

---

## 2. Comprehensive diagnosis of the current implementation

This diagnosis is grounded in a full read of the backend (`backend/app/**`), not the README's aspirational claims.

### 2.1 The dominant gap: "hybrid" retrieval is purely lexical

`app/retrieval/hybrid_retriever.py` performs SQL `ILIKE '%term%'` over `chunk_text` for up to 8 query terms, scoring by term frequency, a hand-curated boost list, and manually maintained synonym tables (`QUERY_EXPANSIONS`). `Chunk.embedding` exists (`VectorType` compiles to pgvector `vector` on Postgres) and `OpenAIEmbedder` exists, **but embeddings are never generated at ingest and never used at query time**. There is no semantic retrieval, no ANN, no real hybrid, and pgvector is effectively dead schema. This is the dominant accuracy ceiling.

### 2.2 Other findings (mapped to evaluation axes)

- **Reranking** (`app/retrieval/reranker.py`) is a heuristic source-type/confidence nudge — not a relevance reranker.
- **Embeddings** are English-centric (`text-embedding-3-small`) for Indonesian content; no multilingual model; single provider.
- **Faithfulness is URL-level only.** `app/rag/citation_validator.py` confirms cited URLs were retrieved and in-scope (good — prevents URL hallucination) but never checks the claim is *entailed* by the cited chunk. `answer_generator._ensure_sentence_citation_markers` auto-staples `[1]` onto uncited sentences, which can manufacture a false citation on an unsupported claim (hallucination vector, OWASP **LLM09**).
- **Guardrails** (`app/rag/guardrails.py`) are a ~12-pattern regex on the *user question only*. No indirect-prompt-injection defense: retrieved page text is injected verbatim into the context block (OWASP **LLM01**).
- **Excessive agency is low (good):** `app/agent/umb_agent.py` is deterministic orchestration, not an LLM tool-loop, with an iteration cap and no write tools. (The "agent" naming oversells it.)
- **Poisoning / embedding weakness (LLM04/08):** "truth = whatever we crawled in-scope" means a subdomain takeover or defacement directly poisons answers. No source-authority weighting, content-trust scoring, or ingest anomaly detection.
- **Unbounded consumption (LLM10):** answer cache + retries + top-k caps exist, but there is no API rate limiting, no per-request token budget, no max input length, and `/chat/stream` spawns a thread per request with no concurrency cap.
- **Freshness:** change detection is `content_hash` only; no recrawl prioritization, no staleness TTL, no "last verified" surfaced to users.
- **Evaluation** (`app/evaluation/evaluate_rag.py`) reports only "sources found / citation count / not_found rate" — it cannot substantiate accuracy claims.
- **Scalability:** retrieval fetches `top_k*20` rows then scores in Python; sync FastAPI + blocking `requests`; will not hold at the 50k-source target.
- **Preserved strengths:** provider abstraction, scope/citation validators, visible-steps streaming, redaction, deterministic controller, careful archive-URL handling.

---

## 3. Architecture (Approach B — modular hardening + serving substrate)

**Unifying thesis:** a per-host/per-fact **Trust substrate** (authority × freshness × corroboration) governs three decisions in the pipeline — *when to re-verify live, how to fuse evidence, and whether to assert a claim.*

```
Client (Next.js) ── SSE visible-steps stream (preserved)
   │
   ▼
[API tier · FastAPI async]
  └ Security middleware: per-IP/session rate-limit, token budget, max-input, concurrency cap   (LLM10)
  └ Input guard: intent + injection heuristics                                                  (LLM01)
   │
   ▼
[Bounded orchestrator]  (deterministic CRAG-style policy — NOT open-ended LLM agency)           (LLM06)
  1 intent/scope ─ 2 Trust+Volatility decision ─ 3 retrieve(dense ∥ sparse) ─
  4 JIT live re-verify? (conditional) ─ 5 TAHF fuse ─ 6 cross-encoder rerank ─
  7 generate(JSON, provenance-segregated context) ─ 8 CGCV verify ─ 9 respond
   │                          │                              │
   ▼                          ▼                              ▼
[Model serving · GPU]   [Stores]                       [Async ingest workers]
  TEI/vLLM:               Postgres/Supabase:              crawl→extract→chunk→embed
   · BGE-M3 (embed, ML)    · pgvector HNSW (dense)         →authority-score→SimHash dedup
   · bge-reranker-v2-m3    · FTS tsvector / OpenSearch     →content-trust/anomaly check   (LLM04/08)
   · mDeBERTa NLI          · valid-time fact store         →index
  LLM gateway (provider    · host-authority table        [Freshness scheduler]
   abstraction kept)       · eval store                    volatility-prioritized recrawl
                          Redis: semantic cache, rate counters, queues
[Observability] OpenTelemetry tracing · per-answer groundedness log · eval dashboard
```

- **Preserved:** provider abstraction, citation/scope validators, visible-steps streaming, redaction, deterministic (non-agentic) controller.
- **Replaced:** lexical-only retriever, heuristic reranker, URL-level-only validation, dead pgvector path.

---

## 4. The Trust substrate and the two novel methods

### 4.1 Trust substrate (shared primitives)

For evidence `e` from host `h`, fetched at time `t`, content-type `m`, supporting a candidate fact `f` of query-type `q`:

- **Authority** `A(h, q) ∈ [0,1] = g(host_prior(h), topical_match(h, q))`.
  - `host_prior(h)`: in-scope link-graph TrustRank/PageRank over the crawl graph [Gyöngyi 2004; Page 1999].
  - `topical_match(h, q)`: embedding similarity between the host's content centroid and the query fact-type (e.g., `pmb.` high for *fees/admissions*; `digilib.` high for *research docs*; student-org subdomains low).
  - This is the anti-poisoning lever (LLM04/08): a defaced/taken-over low-authority host cannot outweigh the registrar.
- **Freshness** `F(e) = exp(−λ(q) · age)`, `age = now − t` (or `now − valid_time` where extractable). `λ(q)` is set by the volatility class (§4.2).
- **Corroboration** `C(f)` = count of *independent* authoritative hosts asserting `f`, with near-duplicate content collapsed via SimHash/embedding dedup (prevents one mirrored source from faking agreement) [Manakul 2023 — corroboration-style consistency].

### 4.2 Method 1 (headline) — Volatility-Aware Just-in-Time Verification (VA-JIT)

A small **fact-volatility model** `v(q) ∈ [0,1]` predicts time-sensitivity from query + retrieved fact-type (high: fees, deadlines, schedules, contacts; low: vision/mission, history, program existence).

**Trigger policy:**

> if `v(q)` is high **and** ( best indexed evidence is stale: `age(e*) > τ(v)` **or** `C(f) < 2` **or** the fact is high-stakes ) → perform **targeted live re-verification**: fetch only the *top-authority in-scope page(s)* for `q` via the existing `live_retriever`, re-extract the specific fact, **cost-bounded** to `B` fetches/query.

**Why it is novel:** FLARE / active retrieval [Jiang 2023] triggers retrieval on **generation uncertainty**. VA-JIT triggers on **fact volatility × staleness × stakes** and performs a **targeted authoritative re-fetch** rather than a generic search — a knowledge-dynamics-driven trigger that the literature has not centered. It is the direct answer to the "knowledge is dynamic" requirement: a fee/deadline is correct *on the day asked*, not merely as of the last crawl. It reuses existing live-retrieval infrastructure.

**Ablation:** VA-JIT on/off; trigger components (volatility-only vs. +staleness vs. +stakes); budget `B` sweep; latency/cost vs. freshness-accuracy trade-off.

### 4.3 Method 2 — Trust-Aware Hybrid Fusion (TAHF) + Corroboration-Gated Claim Verification (CGCV)

**TAHF (fusion stage).** Dense (BGE-M3 [Chen 2024]) and sparse (BM25/FTS [Robertson 2009]) candidate lists are combined with Reciprocal Rank Fusion [Cormack 2009]:

```
RRF(d) = Σ_r 1 / (k + rank_r(d))
```

Top-N is reranked by a cross-encoder (bge-reranker-v2-m3) [Nogueira 2019], producing `rel(d)`. The final trust-aware score applies authority and freshness priors:

```
S(d) = rel(d) + α · A(h_d, q) + β · F(d)
```

`α, β` tuned on a dev set. **Ablation:** RRF-only → +rerank → +authority → +freshness; additive vs. multiplicative prior.

**CGCV (verification stage).**
1. Decompose the answer into **atomic claims** [Min 2023 — FActScore-style].
2. **Multilingual NLI entailment** of each claim against its cited chunk (mDeBERTa-NLI; LLM-judge fallback). Drop non-entailed claims — this kills hallucination *and* indirect injection, because injected instructions are not entailed by legitimate claims (LLM01/LLM09).
3. For **high-stakes/volatile** claims, require `C(c) ≥ 2` independent authoritative sources **or** a fresh VA-JIT-verified source; otherwise mark "needs verification → [official-unit action]" or abstain [Geifman 2017 — selective prediction].
4. Assert only entailed + corroborated claims, with citations and calibrated confidence [Kadavath 2022].

This replaces the current auto-`[1]`-stapling that can manufacture false citations. **Ablation:** CGCV on/off; NLI-only vs. +corroboration vs. +abstention; risk–coverage curves.

**Academic framing:** one trust model, three decision points (when to re-verify / how to fuse / whether to assert), each independently ablatable.

---

## 5. OWASP LLM Top 10 (2025) mitigation map

| # | Risk | Mitigation |
|---|------|------------|
| **01** | Prompt Injection | Provenance-segregated / spotlighted context (retrieved text data-marked as data, not instructions) [Hines 2024; Greshake 2023]; input intent guard; **CGCV entailment gate** (injected instructions are not entailed); no content-driven tool execution. |
| **02** | Sensitive Info Disclosure | Existing redaction + output-side PII/secret scanner + retrieved-content PII filter; public-only crawl. |
| **03** | Supply Chain | Pin dependencies + SBOM; pin model versions; sandbox external discovery tools; checksum downloaded assets. |
| **04** | Data & Model Poisoning | Authority weighting (TAHF) + corroboration gate; ingest anomaly/content-trust checks; SimHash dedup; subdomain-takeover monitoring. |
| **05** | Improper Output Handling | Strict JSON-schema validation (remove raw-content fallthrough); sanitize rendered Markdown; citation+entailment gate before display. |
| **06** | Excessive Agency | Bounded deterministic orchestrator (no open LLM tool-loop); read-only tools; cost-bounded, scope-locked JIT fetch; no write/exec. |
| **07** | System Prompt Leakage | Instruction/data separation; output filter for prompt echoes; JSON-only contract; no secrets in prompts. |
| **08** | Vector & Embedding Weakness | Authority-weighted fusion + corroboration + embedding-store provenance/integrity; dedup; neighbor-anomaly detection; vector-store access control. |
| **09** | Misinformation | CGCV (NLI + corroboration + selective abstention) + VA-JIT freshness + calibrated confidence + mandatory citations + official-unit actions. |
| **10** | Unbounded Consumption | Rate limiting, per-request token budget, max input length, JIT fetch budget `B`, concurrency cap, semantic cache, timeouts. |

---

## 6. Freshness & dynamic knowledge

Volatility-prioritized recrawl scheduler; **valid-time fact store** (facts carry effective dates); change detection beyond `content_hash` (semantic diff); per-volatility-class staleness TTL; VA-JIT closes the day-of gap; **"last verified [date]"** surfaced to users.

## 7. Multimodal

Keep the pipeline; add structure-aware table extraction; fold **per-modal extraction confidence into the Trust substrate** (low-confidence OCR/ASR → lower `A`/`F`, never high-confidence answers — strengthens the existing rule); cross-modal agreement contributes to corroboration `C`.

## 8. Evaluation methodology

- **Gold set:** stratified UMB questions (admissions, fees, programs, calendar, library, public-SSO, ID+EN), each with answer key, source URLs, **volatility** and **stakes** labels.
- **Retrieval:** recall@k, nDCG@k, MRR vs. labeled chunks.
- **Generation:** RAGAS (faithfulness, answer-relevance, context precision/recall) [Es 2024]; ARES [Saad-Falcon 2024]; ALCE citation precision/recall [Gao 2023b]; FActScore atomic factuality [Min 2023]; abstention correctness; `not_found` calibration.
- **Safety:** indirect-injection canary suite; poisoning simulation (inject contradicting low-authority page → authority/corroboration must resist); PII-leak tests.
- **Freshness:** time-travel eval — stale a fact, confirm VA-JIT recovers it.
- **Ablations (academic core):** as listed in §4; report risk–coverage curves for abstention.
- **Human expert eval** on a subset; **CI regression gates** so quality cannot silently drop.

## 9. UX, accessibility, actionability

Surface last-verified date + JIT-verified badge + confidence rationale + why-this-source (authority/corroboration) on source cards; structured **next-action cards** (deep links to official units/forms); clear abstention UX ("not found → verify here"); **WCAG 2.1 AA** (ARIA for streamed steps/source cards, keyboard nav, contrast, screen-reader-friendly citations, reduced-motion); ID/EN UI.

## 10. Cost & scalability (campus-wide)

Async FastAPI + worker pool; GPU model-serving (TEI/vLLM) with request batching; pgvector **HNSW** [Malkov 2020]; **Redis semantic cache** (embedding-keyed — the primary cost lever); **provider routing** (cheap model for intent/volatility/claim-decomposition, stronger model for synthesis); prompt caching; JIT budget caps; autoscaling + cache warming for admissions/registration bursts; concurrency cap + backpressure. Includes a `$/query` model driven by cache-hit ratio.

---

## 11. Workstream decomposition & sequencing

Each workstream becomes its own spec → plan → build cycle.

1. **Retrieval & grounding core** — pgvector HNSW + BM25/FTS + RRF + BGE-M3 + cross-encoder + **TAHF**. *Foundation.*
2. **Evaluation harness** — gold set + RAGAS/ARES/ALCE + ablation rig + CI gates. *Built in parallel with #1 so every change is measured.*
3. **Verification & abstention** — **CGCV**: claim decomposition + NLI + corroboration + selective abstention.
4. **VA-JIT freshness** — volatility model + targeted live re-verification + valid-time store + scheduler.
5. **Security hardening** — OWASP map: middleware, spotlighting, poisoning defenses, rate/token budgets. *Cross-cutting.*
6. **UX / accessibility / actionability + cost/scale** — serving substrate, semantic cache, async path, a11y. *Continuous.*

**Dependencies:** 1 → 3 → 4; 2 early/parallel; 5 cross-cutting; 6 last/continuous.

---

## 12. Key risks & mitigations

| Risk | Mitigation |
|------|------------|
| Indonesian NLI quality/latency | Multilingual NLI (mDeBERTa) + LLM-judge fallback; cache verdicts. |
| JIT latency | Async + budget `B` + semantic cache; only on volatile/high-stakes queries. |
| Authority cold-start | Seed priors from URL structure + in-scope link graph; refine over time. |
| Volatility-label cost | Bootstrap from a fact-type taxonomy; expand with feedback signals. |
| Cross-encoder GPU cost | Batching + rerank cache; rerank only fused top-N. |

---

## 13. References

RAG & retrieval:
1. Lewis et al. 2020. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS.
2. Karpukhin et al. 2020. *Dense Passage Retrieval for Open-Domain Question Answering.* EMNLP.
3. Robertson & Zaragoza 2009. *The Probabilistic Relevance Framework: BM25 and Beyond.* FnTIR.
4. Cormack et al. 2009. *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods.* SIGIR.
5. Chen et al. 2024. *BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings.* ACL Findings.
6. Nogueira & Cho 2019. *Passage Re-ranking with BERT.* arXiv.
7. Khattab & Zaharia 2020. *ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT.* SIGIR.
8. Malkov & Yashunin 2020. *Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs.* IEEE TPAMI.

Adaptive / corrective RAG:
9. Asai et al. 2024. *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection.* ICLR.
10. Yan et al. 2024. *Corrective Retrieval Augmented Generation (CRAG).* arXiv.
11. Jiang et al. 2023. *Active Retrieval Augmented Generation (FLARE).* EMNLP.
12. Gao et al. 2023a. *Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE).* ACL.

Faithfulness / evaluation / abstention:
13. Es et al. 2024. *RAGAS: Automated Evaluation of Retrieval Augmented Generation.* EACL (demo).
14. Saad-Falcon et al. 2024. *ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems.* NAACL.
15. Manakul et al. 2023. *SelfCheckGPT: Zero-Resource Black-Box Hallucination Detection for Generative LLMs.* EMNLP.
16. Min et al. 2023. *FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation.* EMNLP.
17. Gao et al. 2023b. *Enabling Large Language Models to Generate Text with Citations (ALCE).* EMNLP.
18. Geifman & El-Yaniv 2017. *Selective Classification for Deep Neural Networks.* NeurIPS.
19. Kadavath et al. 2022. *Language Models (Mostly) Know What They Know.* arXiv.

Authority / security:
20. Gyöngyi et al. 2004. *Combating Web Spam with TrustRank.* VLDB.
21. Page et al. 1999. *The PageRank Citation Ranking: Bringing Order to the Web.* Stanford Tech Report.
22. Greshake et al. 2023. *Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection.* AISec @ CCS.
23. Hines et al. 2024. *Defending Against Indirect Prompt Injection Attacks With Spotlighting.* arXiv (Microsoft).
24. Inan et al. 2023. *Llama Guard: LLM-based Input-Output Safeguard for Human-AI Conversations.* arXiv.

Considered alternative (not selected as headline):
25. Edge et al. 2024. *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* arXiv (Microsoft GraphRAG).

*Load-bearing citations are referenced inline at their design decisions; the full list exceeds the required 15 to document considered alternatives.*
