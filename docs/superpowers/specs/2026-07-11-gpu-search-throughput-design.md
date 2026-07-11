# GPU Search Throughput Design

## Goal

Increase direct-MCP search throughput by keeping the GPU fed during retrieval stalls without changing retrieval or reranking semantics.

## Evidence

- A 60-second sample during the tuned LoCoMo run averaged 50.6% GPU utilization, with a 0-100% range.
- VRAM stayed at 2,728 MiB of 4,096 MiB.
- Rerank bursts reached 97-100% GPU utilization.
- The reranker currently runs with `--parallel 1`, and the evaluator issues searches sequentially.

The GPU is saturated while reranking but idle while a single request waits for embedding, TuringDB retrieval channels, graph expansion, and result hydration. Docker transport is not the primary cause.

## Design

1. Make llama.cpp reranker parallelism configurable and default it to two slots.
2. Add bounded search concurrency to the direct-MCP evaluator. The compatibility default remains one worker so existing benchmark contracts do not silently change.
3. Each worker owns a direct stdio MCP session. Workers share no in-process store or client state; they communicate only through the production TuringDB and GPU sidecars.
4. Preserve result determinism by collecting rows by original question index before metric calculation and artifact serialization.
5. Keep ingestion and checkpoint writes sequential. Only read-only `memory_search` calls run concurrently.

## Validation Gates

- Zero MCP search errors and zero container restarts.
- Identical retrieved-reference ordering for a deterministic smoke set at concurrency one and two.
- MRR and evidence recall do not regress on the selected LoCoMo gate conversations.
- Average GPU utilization exceeds 80% during the concurrent run.
- Questions per second improves over the sequential run.
- Start with two workers. Test three or four only after two passes VRAM, health, quality, and throughput gates.

## Follow-Up

Candidate limits of 50, 30, and 20 are a separate latency ablation. They must not be combined with the concurrency experiment because that would prevent attribution of quality or speed changes.
