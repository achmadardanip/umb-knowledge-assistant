# Known Issues

## KI-001 — `test_qwen3_reranker` fails on memory-constrained hosts

```
Test:          app/tests/test_qwen3_reranker.py::test_qwen3_ranks_answering_chunk_above_tangential
Category:      Resource Exhaustion (environment)
Root Cause:    Windows paging-file / commit-limit exhaustion while loading the Qwen3
               reranker transformer on top of the test session's other model loads
               (E5 embedder + transformers + a resident Ollama qwen2.5:7b ≈ 5 GB).
Error:         OSError: The paging file is too small for this operation to complete. (1455)
               / "memory allocation of N bytes failed"
Production Risk: Low
```

### Why it is NOT a code regression
- It is a **memory allocation error**, not a logic/assertion failure.
- It **fails identically with all P3/P4 changes stashed** at the green P3 commit
  (`git stash` diagnosis) — independent of this branch's work.
- It **passed earlier in the same session** at the same commit, and
  `Qwen3Reranker()` loads fine **standalone** once the resident Ollama model is unloaded.
- It is marked `@pytest.mark.slow` and only manifests after a long suite run accumulates
  model memory.

### Mitigations (when the reranker test must pass locally)
- Unload the resident LLM first: `curl http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b-instruct","keep_alive":0}'`.
- Increase the Windows page file (System → Advanced → Performance → Virtual memory).
- Run the slow reranker test in isolation / early, or on a GPU/larger-memory host.
- Production is unaffected: the reranker is gated (`RERANKER_ENABLED`) and loads once in a
  long-lived server process, not under per-test memory churn.
