# GPU Search Throughput Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the reranker GPU fed with two independent direct-MCP search workers while preserving deterministic quality metrics.

**Architecture:** The evaluator creates one direct stdio MCP client per worker and assigns read-only question searches through a bounded queue. Results are restored to source order before scoring and serialization. Compose exposes llama.cpp parallel slots as a configurable value with production default two.

**Tech Stack:** Python 3.13+, asyncio, FastMCP Client/StdioTransport, Docker Compose, pytest.

---

### Task 1: Configurable Reranker Parallelism

**Files:**
- Modify: `compose.yaml`
- Test: `tests/test_docker_hardening.py`

- [ ] **Step 1: Write the failing Compose contract test**

Assert that the reranker command contains `--parallel` followed by `${RERANK_PARALLEL:-2}` so production uses two slots and operators can override it.

- [ ] **Step 2: Run the focused test and verify RED**

Run `pytest tests/test_docker_hardening.py -q` and confirm the parallel-value assertion fails against the literal `1`.

- [ ] **Step 3: Implement the minimal Compose change**

Replace the literal parallel value with `${RERANK_PARALLEL:-2}`. Do not rebuild or restart services during the active sequential benchmark.

- [ ] **Step 4: Verify GREEN and Compose rendering**

Run `pytest tests/test_docker_hardening.py -q` and `docker compose config --quiet`.

- [ ] **Step 5: Commit**

Commit the test and Compose change as `perf: enable parallel GPU reranking`.

### Task 2: Deterministic Concurrent Search Evaluation

**Files:**
- Modify: `scripts/eval_backboard_locomo_mcp.py`
- Test: `tests/test_backboard_locomo_runner.py`

- [ ] **Step 1: Write failing evaluator tests**

Test validation of worker counts, deterministic ordering when searches finish out of order, and one MCP client per worker. Use fake async search workers; do not call Docker in unit tests.

- [ ] **Step 2: Run the focused tests and verify RED**

Run `pytest tests/test_backboard_locomo_runner.py -q` and confirm failures are caused by the missing concurrency API.

- [ ] **Step 3: Implement bounded worker execution**

Add `--search-concurrency` with default one and validation range one through four. Keep question evaluation logic in a single-question coroutine, execute it through worker-owned clients, and sort completed rows by question index before metric aggregation and checkpoint serialization.

- [ ] **Step 4: Verify GREEN and static checks**

Run `pytest tests/test_backboard_locomo_runner.py -q` and `ruff check scripts/eval_backboard_locomo_mcp.py tests/test_backboard_locomo_runner.py`.

- [ ] **Step 5: Commit**

Commit evaluator and tests as `perf: add bounded direct MCP search concurrency`.

### Task 3: Runtime Throughput Gate

**Files:**
- Modify only if a verified defect is found by the gate.
- Output: `.benchmarks/` runtime artifacts, ignored by Git.

- [ ] **Step 1: Let the active sequential full run finish**

Keep health cadence; do not impose a timeout or restart its containers.

- [ ] **Step 2: Rebuild and start the approved runtime**

Run `docker compose up -d --build` after the sequential artifact is durable. Confirm all six services are healthy and the reranker reports two parallel slots.

- [ ] **Step 3: Run a two-worker direct-MCP smoke gate**

Run the evaluator with `--search-concurrency 2` on completed gate conversations using the existing cached dataset and model volumes.

- [ ] **Step 4: Compare quality and throughput**

Require zero errors, unchanged deterministic retrieval ordering on the smoke set, no MRR/evidence regression, GPU average above 80%, and improved questions per second.

- [ ] **Step 5: Run the full verification suite**

Run `pytest -q`, `ruff check .`, and `docker compose config --quiet`.

- [ ] **Step 6: Commit any validation-driven fix separately**

If no defect is found, do not commit benchmark artifacts. If a defect is found, return to TDD and commit only the focused correction.
