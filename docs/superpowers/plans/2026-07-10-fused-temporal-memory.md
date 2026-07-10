# Fused Temporal Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate a local fused memory pipeline that turns raw MCP messages into provenance-preserving temporal graph records and retrieves them through dense, BM25, entity/graph, community, RRF, and Qwen signals.

**Architecture:** TuringDB remains the canonical episode, derived graph, and vector store. The shared GLiNER2 sidecar performs versioned composed extraction, SQLite FTS5 provides a recoverable sparse projection, `graspologic-native` computes deterministic Leiden communities, weighted RRF combines independent candidate channels, and Qwen reranks provenance-rich contexts.

**Tech Stack:** Python 3.11+, FastMCP, TuringDB 1.35, FastGLiNER2 ONNX, llama.cpp OpenAI-compatible embedding/rerank APIs, SQLite FTS5, graspologic-native 1.3.1, pytest, Docker Compose.

---

## File Map

- Create `src/turing_agentmemory_mcp/memory_extraction.py`: typed extraction contracts, schema identity, normalization, and HTTP client.
- Modify `src/turing_agentmemory_mcp/gliner_provider.py`: composed extraction provider and `/extract-memory` endpoint.
- Create `src/turing_agentmemory_mcp/sparse_index.py`: FTS5 schema, BM25 search, durable outbox, replay, and rebuild primitives.
- Create `src/turing_agentmemory_mcp/retrieval_fusion.py`: channel candidates, weighted RRF, explanations, and diversity selection.
- Create `src/turing_agentmemory_mcp/community_detection.py`: detector protocol, native Leiden backend, deterministic summaries.
- Create `src/turing_agentmemory_mcp/temporal_graph.py`: derived entity/fact/community records and deterministic normalization.
- Modify `src/turing_agentmemory_mcp/store.py`: transactional orchestration, graph projection, candidate channels, graph expansion, fusion, and reranking.
- Modify `src/turing_agentmemory_mcp/models.py`: derived provenance and channel explanation response fields.
- Modify `src/turing_agentmemory_mcp/search_controls.py`: fused score explanation validation/building.
- Modify `src/turing_agentmemory_mcp/rerank.py`: token-aware configurable rerank context.
- Modify `src/turing_agentmemory_mcp/server.py` and `src/turing_agentmemory_mcp/utcp.py`: maintenance and explainable search contracts.
- Modify `src/turing_agentmemory_mcp/admin_repair.py`: sparse/derived/community repair operations.
- Modify `src/turing_agentmemory_mcp/observability.py`: fused-stage metrics without private content.
- Modify `pyproject.toml`, `Dockerfile`, and `compose.yaml`: pinned native Leiden dependency and feature configuration.
- Modify `scripts/eval_backboard_locomo_mcp.py`: MRR, ablation metadata, cutoffs, and answer-evaluation handoff.
- Create focused tests matching each new module and extend direct-MCP integration tests.

### Task 1: Composed GLiNER2 Memory Extraction

**Files:**
- Create: `src/turing_agentmemory_mcp/memory_extraction.py`
- Modify: `src/turing_agentmemory_mcp/gliner_provider.py`
- Test: `tests/test_memory_extraction.py`
- Test: `tests/test_gliner_provider.py`

- [ ] **Step 1: Write failing contract tests**

Cover schema version/model identity, entity and relation normalization, confidence/spans, stable input order, malformed output, duplicate task labels, and provider failures.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run `pytest -q tests/test_memory_extraction.py tests/test_gliner_provider.py`.

- [ ] **Step 3: Implement typed extraction contracts and normalization**

Add immutable dataclasses for entity mentions, relation mentions, classifications, temporal expressions, and per-message extraction. Reject invalid spans, unknown references, non-finite confidence, and result-count mismatch.

- [ ] **Step 4: Implement `/extract-memory`**

Build one versioned composed schema, apply constrained subject/object labels, serialize normalized results, and use the existing bounded inference semaphore and private-log policy.

- [ ] **Step 5: Verify focused tests and commit**

Run focused tests plus `ruff check` on changed modules, then commit `feat: add composed GLiNER2 memory extraction`.

### Task 2: Temporal Derived Graph Projection

**Files:**
- Create: `src/turing_agentmemory_mcp/temporal_graph.py`
- Modify: `src/turing_agentmemory_mcp/store.py`
- Modify: `src/turing_agentmemory_mcp/models.py`
- Test: `tests/test_temporal_graph.py`
- Test: `tests/test_batch_memory.py`

- [ ] **Step 1: Write failing deterministic projection tests**

Cover entity canonicalization, stable IDs, relation/fact provenance, source inheritance, observation timestamps, valid-time fields, replay idempotence, and tenant separation.

- [ ] **Step 2: Confirm the tests fail without derived records**

Run `pytest -q tests/test_temporal_graph.py tests/test_batch_memory.py`.

- [ ] **Step 3: Implement pure projection planning**

Convert extraction output into deterministic entity, fact, and edge plans without database effects. Preserve source IDs and never infer unsupported facts.

- [ ] **Step 4: Add atomic TuringDB graph writes**

Create/update derived records after extraction and before vector publication. Roll back the batch path on extraction/projection failure and keep raw evidence immutable.

- [ ] **Step 5: Embed derived fact and entity text**

Batch Granite calls and load vectors under dedicated indexes while preserving the existing 768-dimensional contract.

- [ ] **Step 6: Verify and commit**

Run focused tests and commit `feat: project temporal facts and entities`.

### Task 3: Recoverable FTS5 BM25 Projection

**Files:**
- Create: `src/turing_agentmemory_mcp/sparse_index.py`
- Modify: `src/turing_agentmemory_mcp/store.py`
- Modify: `src/turing_agentmemory_mcp/admin_repair.py`
- Test: `tests/test_sparse_index.py`
- Test: `tests/test_admin_repair.py`

- [ ] **Step 1: Write failing FTS/outbox tests**

Cover tenant filtering, phrase and exact identifiers, BM25 ordering, upsert/delete idempotence, crash replay, stale schema rebuild, expiry, and unavailable-index errors.

- [ ] **Step 2: Confirm failure**

Run `pytest -q tests/test_sparse_index.py tests/test_admin_repair.py`.

- [ ] **Step 3: Implement SQLite schema and safe query compilation**

Use bound parameters, FTS5 `unicode61`, WAL mode, busy timeout, explicit transactions, and bounded result counts. Never interpolate user query syntax directly.

- [ ] **Step 4: Implement durable projection outbox**

Record pending upsert/delete operations, replay them idempotently, checkpoint schema version, and expose lag/repair state.

- [ ] **Step 5: Integrate writes and administrative rebuild**

Project episode/fact/entity/community text and support full rebuild from TuringDB without changing canonical IDs.

- [ ] **Step 6: Verify and commit**

Run focused tests and commit `feat: add recoverable BM25 projection`.

### Task 4: Multi-Channel Weighted RRF

**Files:**
- Create: `src/turing_agentmemory_mcp/retrieval_fusion.py`
- Modify: `src/turing_agentmemory_mcp/search_controls.py`
- Modify: `src/turing_agentmemory_mcp/models.py`
- Test: `tests/test_retrieval_fusion.py`
- Test: `tests/test_search_controls.py`

- [ ] **Step 1: Write failing fusion tests**

Cover incomparable raw scores, weighted rank contributions, missing-channel behavior, deterministic ties, duplicate IDs, channel caps, and complete explanation output.

- [ ] **Step 2: Confirm failure**

Run `pytest -q tests/test_retrieval_fusion.py tests/test_search_controls.py`.

- [ ] **Step 3: Implement channel candidates and weighted RRF**

Use rank constant 60 by default, positive finite weights, deterministic source ordering, and no implicit score normalization.

- [ ] **Step 4: Implement provenance-aware diversity**

Prevent repeated derived records from one source message from consuming the final result set while retaining explicit multi-hop evidence.

- [ ] **Step 5: Verify and commit**

Run focused tests and commit `feat: fuse retrieval channels with weighted RRF`.

### Task 5: Integrated Entity, Graph, Dense, And Sparse Search

**Files:**
- Modify: `src/turing_agentmemory_mcp/store.py`
- Modify: `src/turing_agentmemory_mcp/server.py`
- Modify: `src/turing_agentmemory_mcp/utcp.py`
- Test: `tests/test_fused_memory_search.py`
- Test: `tests/test_retrieval_filters.py`
- Test: `tests/test_utcp_manual.py`

- [ ] **Step 1: Write failing search pipeline tests**

Cover independent episode/fact/entity/BM25 rankings, query entity extraction, one/two-hop expansion, pre-fusion tenant/filter enforcement, degraded-channel reporting, and MCP serialization.

- [ ] **Step 2: Confirm failure**

Run the focused test group.

- [ ] **Step 3: Implement independent candidate generators**

Do not reuse the current all-memory lexical scan. Keep channel limits configurable and attach source provenance before fusion.

- [ ] **Step 4: Integrate RRF and final result assembly**

Return the existing memory fields plus optional fused explanations without breaking non-explain clients.

- [ ] **Step 5: Verify filters/governance and commit**

Run focused tests and commit `feat: integrate fused temporal memory search`.

### Task 6: Token-Aware Qwen Reranking

**Files:**
- Modify: `src/turing_agentmemory_mcp/rerank.py`
- Modify: `src/turing_agentmemory_mcp/store.py`
- Test: `tests/test_rerank.py`
- Test: `tests/test_fused_memory_search.py`

- [ ] **Step 1: Write failing context and fallback tests**

Cover source/date/path context, configurable byte/rune/token approximation limit, provider errors, invalid response, explicit fallback state, and no private telemetry.

- [ ] **Step 2: Implement bounded provenance-rich rerank documents**

Replace the fixed 480-character constant with configuration and deterministic context assembly.

- [ ] **Step 3: Preserve fused order on visible fallback**

Mark rerank status in explanations and telemetry.

- [ ] **Step 4: Verify and commit**

Run focused tests and commit `feat: rerank fused memory context`.

### Task 7: Deterministic Leiden Communities

**Files:**
- Create: `src/turing_agentmemory_mcp/community_detection.py`
- Modify: `src/turing_agentmemory_mcp/store.py`
- Modify: `src/turing_agentmemory_mcp/admin_repair.py`
- Modify: `pyproject.toml`
- Test: `tests/test_community_detection.py`
- Test: `tests/test_admin_repair.py`

- [ ] **Step 1: Write failing detector tests**

Cover weighted edges, deterministic seed, hierarchy, max cluster size, disconnected components, isolates, canonical community IDs, and deterministic summaries.

- [ ] **Step 2: Confirm failure**

Run `pytest -q tests/test_community_detection.py tests/test_admin_repair.py`.

- [ ] **Step 3: Implement detector protocol and native backend**

Pin `graspologic-native==1.3.1`, call its weighted hierarchical Leiden API directly, and keep an optional unshipped `vtraag` adapter boundary.

- [ ] **Step 4: Implement derived community rebuild**

Build communities from tenant entity edges, write deterministic summaries/provenance, batch Granite embeddings, and replace only derived community state.

- [ ] **Step 5: Add community candidate retrieval**

Search community vectors independently and expand selected communities to representative source facts.

- [ ] **Step 6: Verify and commit**

Run focused tests and commit `feat: add Leiden community memory`.

### Task 8: Runtime Configuration And Operational Signals

**Files:**
- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Modify: `src/turing_agentmemory_mcp/observability.py`
- Modify: `src/turing_agentmemory_mcp/admin_repair.py`
- Test: `tests/test_observability.py`
- Test: `tests/test_compose_config.py`

- [ ] **Step 1: Add failing configuration/telemetry tests**

Cover pinned dependency, feature flags, valid weights/limits, projection location, repair status, extraction schema identity, and content-free spans.

- [ ] **Step 2: Implement configuration and health cadence**

Expose stage readiness, projection lag, community age, model identities, and degraded-channel counters.

- [ ] **Step 3: Build and verify Compose**

Run `docker compose config`, build using cached layers/models, and start all services with healthy cadence.

- [ ] **Step 4: Commit**

Commit `ops: configure fused temporal memory pipeline`.

### Task 9: Comparable Direct-MCP LoCoMo Evaluation

**Files:**
- Modify: `scripts/eval_backboard_locomo_mcp.py`
- Modify: `tests/test_backboard_locomo_runner.py`
- Create: `scripts/eval_locomo_answers.py`
- Test: `tests/test_locomo_answer_eval.py`

- [ ] **Step 1: Write failing evaluator tests**

Cover canonical category names, MRR, top 20/50/200 cutoffs, ablation identity, context token accounting, answerer/judge metadata, resume, and no gold-answer ingestion.

- [ ] **Step 2: Implement retrieval metrics and answer handoff**

Keep MCP as the only memory interface and persist enough retrieved context for a pinned benchmark answerer/judge phase.

- [ ] **Step 3: Verify evaluator tests and commit**

Commit `test: add comparable LoCoMo evaluation contract`.

### Task 10: Full Verification And Benchmark Gates

**Files:**
- Modify only defects discovered by verification.

- [ ] **Step 1: Run static and unit gates**

Run `ruff check .`, `pytest -q`, and `git diff --check`.

- [ ] **Step 2: Rebuild and start the product**

Use cached model volumes, wait by health cadence, and verify all product and sidecar health endpoints.

- [ ] **Step 3: Run direct MCP smoke**

Store raw messages, verify composed extraction and derived graph provenance, search each channel, rebuild communities, and confirm Qwen/Granite GPU execution.

- [ ] **Step 4: Run LoCoMo staged ablations**

Measure dense-only, dense+BM25, entity/graph fusion, community fusion, and Qwen reranking at fixed question subsets before the full run.

- [ ] **Step 5: Run the full 1,540-question direct-MCP evaluation**

Use health cadence rather than a benchmark wall-clock timeout. Record retrieval, answer, token, latency, stage, model, and configuration metrics.

- [ ] **Step 6: Compare against Mem0 under the same contract**

Do not claim a win unless dataset, questions, cutoff, answerer, judge, prompts, and token accounting match and every required score exceeds the selected Mem0 baseline.

- [ ] **Step 7: Final completion audit**

Map every design requirement to code, tests, runtime evidence, and benchmark output; leave the goal active if any evidence is missing.

