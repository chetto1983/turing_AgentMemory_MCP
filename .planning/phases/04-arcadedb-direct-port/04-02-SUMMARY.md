---
phase: 04-arcadedb-direct-port
plan: 02
subsystem: database
tags: [arcadedb, urllib, mvcc, transactions, retry, readiness]

# Dependency graph
requires:
  - phase: 04-01
    provides: spike-minimal ArcadeDBClient (query/command/begin/commit/rollback, is_ready/probe, ensure_database) empirically validated against a live arcadedata/arcadedb:26.7.1 container
provides:
  - Full ArcadeDBClient transaction surface (query/command/sqlscript/begin/commit/rollback)
  - run_in_transaction(body, commit_retries=...) -- managed begin/body/commit helper with a bounded MVCC commit-retry-N wrapper (D-08 infra)
  - is_mvcc_conflict() predicate classifying ArcadeDB's ConcurrentModificationException signal
  - A transport-layer fix so ArcadeDB's own conflict signal (HTTP 503) is never masked by blind generic retry
  - ARCADEDB_COMMIT_RETRIES env var wired into from_env()
  - is_ready()/probe() reconfirmed as the non-raising D-10 readiness primitive (no code change needed, tests added)
affects: [04-03-schema-bootstrap, 04-04-core-seam, 04-05-store-mixins, 04-06-store-mixins, 04-07-store-mixins, 04-08-store-mixins]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Managed-transaction callback (`run_in_transaction(body)`): caller runs N command()/sqlscript() calls scoped to one session inside `body`, this wrapper owns begin/commit/rollback and the MVCC retry policy"
    - "Predicate-based conflict classification (`is_mvcc_conflict`) mirroring `retryable_provider_code` in provider_config.py -- reused by both the transport retry-skip decision and the outer commit-retry-N decision, not inlined twice"
    - "Per-function `@pytest.mark.integration` on live-container tests instead of a blanket module-level `pytestmark`, so mocked-HTTP unit tests in the same file run in the fast/default tier"

key-files:
  created: []
  modified:
    - src/turing_agentmemory_mcp/arcadedb_client.py
    - tests/test_arcadedb_client.py

key-decisions:
  - "ArcadeDB's MVCC conflict signal (empirically confirmed live, not in 04-SPIKE-FINDINGS.md which deferred it) is HTTP 503 with an `exception` field of `com.arcadedb.exception.ConcurrentModificationException`; retrying the identical `commit` call again does NOT recover because ArcadeDB invalidates the session on any failure, returning a different, masking error (`TransactionException`, \"Transaction not begun\") instead"
  - "Chose a Python-side commit-retry-N loop over SQL's `COMMIT RETRY N` clause: the spike explicitly deferred confirming that SQL syntax works on 26.7.1, so this wave does not rely on an unconfirmed mechanism"
  - "run_in_transaction redoes the WHOLE begin->body->commit cycle on conflict (not just re-POSTing commit), matching the empirically-confirmed recovery path; only the one MVCC signal is retried this way, any other failure propagates immediately"
  - "_request's generic transport retry loop now skips retrying when the HTTP error body is the MVCC conflict signal -- fixes a masking bug where blind transport-level retry (503 and 500 are both in _RETRYABLE_HTTP_CODES) would have silently converted a real conflict into an unrelated 'Transaction not begun' error by the time it reached any caller-level retry logic"
  - "sqlscript() is a thin wrapper over the existing command(language='sqlscript') path already exercised by 04-01's smoke test -- no new endpoint behavior, just a named, documented entry point"
  - "Task 2 (readiness) required no production code change: is_ready()/probe() from 04-01 already satisfied D-10's contract (stateless, never raises, no TuringDB load_graph/list_loaded_graphs/set_graph semantics) -- only new tests were added to lock this in"

requirements-completed: [ARC-03]

coverage:
  - id: D1
    description: "ArcadeDBClient exposes sqlscript(), rollback() (already present), begin()/commit() (already present), and run_in_transaction() -- a managed begin->body->commit helper"
    requirement: ARC-03
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_begin_command_commit_issue_calls_in_order"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_sqlscript_posts_single_multi_statement_body"
        status: pass
    human_judgment: false
  - id: D2
    description: "Bounded MVCC commit-retry-N wrapper: a conflicted commit retries the whole transaction up to ARCADEDB_COMMIT_RETRIES times then raises; a non-conflict HTTP 500 is not retried by the wrapper (only by the separate transport loop)"
    requirement: ARC-03
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_commit_conflict_retries_whole_transaction_then_succeeds"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_commit_conflict_exhausts_bounded_retry_budget_then_raises"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_non_conflict_500_is_not_retried_by_the_mvcc_wrapper"
        status: pass
    human_judgment: false
  - id: D3
    description: "Params bind as ?/:named separately from statement text; a value containing quotes/special characters does not corrupt the statement"
    requirement: ARC-03
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_params_bind_and_do_not_corrupt_statement"
        status: pass
    human_judgment: false
  - id: D4
    description: "Readiness probe (is_ready()/probe()) returns a bool, never raises on an unreachable endpoint, and reflects recovery after a transient failure without a manual reload step"
    requirement: ARC-03
    verification:
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_is_ready_returns_true_when_probe_succeeds"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_is_ready_returns_false_without_raising_when_unreachable"
        status: pass
      - kind: unit
        ref: "tests/test_arcadedb_client.py#test_probe_reflects_recovery_after_transient_failure"
        status: pass
    human_judgment: false

# Metrics
duration: ~90min
completed: 2026-07-13
status: complete
---

# Phase 4 Plan 02: ArcadeDB Managed Transactions + Commit-Retry-N + Readiness Summary

**Grew `ArcadeDBClient` with `sqlscript`/`run_in_transaction` (a managed begin/body/commit helper bounded by a Python-side MVCC commit-retry-N loop) and fixed a transport-retry bug that would have silently masked ArcadeDB's real conflict signal — discovered by inducing an actual MVCC conflict against the live container rather than guessing the HTTP contract.**

## Performance

- **Duration:** ~90 min
- **Completed:** 2026-07-13
- **Tasks:** 2
- **Files modified:** 2 (`src/turing_agentmemory_mcp/arcadedb_client.py`, `tests/test_arcadedb_client.py`)

## Accomplishments

- `ArcadeDBClient.sqlscript(body, params=...)` — multi-statement `BEGIN;...;COMMIT;` batches in one call, a documented entry point over the existing `command(language="sqlscript")` path.
- `ArcadeDBClient.run_in_transaction(body, commit_retries=...)` — the D-08 managed-transaction primitive: runs `begin()` → `body(session_id)` → `commit()`, and on an MVCC conflict redoes the *entire* cycle from a fresh session (not just the failed commit), bounded by `ARCADEDB_COMMIT_RETRIES` (default 3).
- `is_mvcc_conflict(detail)` — a small, reusable predicate (mirrors `provider_config.retryable_provider_code`) that recognizes ArcadeDB's `ConcurrentModificationException` signal; used both to keep `_request`'s generic transport retry from masking a conflict, and to drive `run_in_transaction`'s retry decision.
- **Empirically resolved the one thing 04-SPIKE-FINDINGS.md explicitly deferred**: induced a real MVCC conflict against the live `arcadedb` container (two concurrent sessions updating the same vertex) to observe the actual wire contract, rather than guessing it. Findings (see module docstring in `arcadedb_client.py` for the full write-up):
  - A losing commit returns **HTTP 503** with JSON body `{"exception": "com.arcadedb.exception.ConcurrentModificationException", ...}`.
  - Retrying the *same* commit call afterward does **not** recover — the server invalidates the session on any failure, so the next call (commit, rollback, or command) on that session returns a *different* error: HTTP 500 `com.arcadedb.exception.TransactionException`, `"Transaction not begun"`.
  - `rollback()` after any failure (including after a failed commit) succeeds (204) and is idempotent — safe to call unconditionally in cleanup paths.
  - A duplicate-key/unique-constraint violation is a distinct, non-retryable HTTP **409** (`DuplicatedKeyException`) — not in `_RETRYABLE_HTTP_CODES`, so it was never at risk of the masking bug.
- Readiness (`is_ready()`/`probe()`) reconfirmed to already satisfy D-10's contract from 04-01 — no code change needed, only new tests locking in the bool-return/never-raise/no-manual-reload behavior.
- 16/16 tests green (7 live-container smoke tests from 04-01, unaffected, plus 9 new mocked-HTTP unit tests that need no live container).

## Task Commits

Each task was committed atomically, following RED (failing test) → GREEN (implementation) TDD gates:

1. **Task 1: Managed-transaction surface + commit-retry-N wrapper (D-08 infra)**
   - `test(04-02): add failing tests for managed-transaction + commit-retry-N surface` — `8622a88` (RED: 4 of 9 new tests fail because `sqlscript`/`run_in_transaction`/`commit_retries` don't exist yet on the 04-01 client)
   - `feat(04-02): grow ArcadeDBClient with sqlscript, managed transactions, and MVCC commit-retry-N` — `cfdf88c` (GREEN: all 16 tests pass)
2. **Task 2: Readiness probe / reconnect primitive (D-10 infra)** — folded into the same GREEN commit above (`cfdf88c`); no production code change was required, only the 3 new readiness tests bundled in the RED/GREEN commits above confirm the existing 04-01 `is_ready()`/`probe()` already satisfies D-10.

**Plan metadata:** (this commit, following this SUMMARY)

_Note: both tasks' tests were combined into one RED commit and one GREEN commit because Task 2 required zero production code changes — splitting it into its own empty-diff "feat" commit would not have been meaningful. The task boundary is documented here and in the coverage IDs (D1/D2/D3 map to Task 1, D4 maps to Task 2) instead._

## Files Created/Modified

- `src/turing_agentmemory_mcp/arcadedb_client.py` (212 → 312 LOC) — added `sqlscript()`, `run_in_transaction()`, `is_mvcc_conflict()`, `commit_retries` field + `ARCADEDB_COMMIT_RETRIES` env wiring, and the `_request` transport-retry-skip fix for the conflict signal. Module docstring extended with the full empirically-confirmed MVCC contract.
- `tests/test_arcadedb_client.py` (284 → 584 LOC) — moved the blanket `pytestmark = pytest.mark.integration` to per-function `@pytest.mark.integration` decorators on the 7 existing live-container smoke tests, and added 9 new mocked-`urlopen` unit tests (scripted transport + fake response/HTTPError helpers) covering the new surface plus the pre-existing begin/command/commit/readiness behavior.

## Decisions Made

- **MVCC conflict signal resolved empirically, not guessed**: HTTP 503 + `exception: com.arcadedb.exception.ConcurrentModificationException`, confirmed by inducing a real conflict against the live container (two concurrent sessions racing an `UPDATE` on the same vertex) rather than relying on `04-SPIKE-FINDINGS.md`, which explicitly deferred this ("`COMMIT RETRY N` (A3) was not exercised this wave — deferred to whichever later wave first needs the retry wrapper").
- **Python-side retry loop, not SQL `COMMIT RETRY N`**: the doc-sourced `BEGIN ISOLATION REPEATABLE_READ; ...; COMMIT RETRY N;` sqlscript form was never empirically confirmed on 26.7.1, so this wave does not build on an unconfirmed mechanism. `run_in_transaction` implements the retry in Python instead, matching the plan's explicit "implement whichever the spike proved" instruction.
- **Whole-transaction retry, not commit-only retry**: because a failed commit invalidates the session server-side, `run_in_transaction` re-runs `begin()` → `body()` → `commit()` from scratch on each retry attempt — re-POSTing just `commit()` was empirically proven not to recover.
- **Transport-retry-skip fix for the conflict signal (Rule 1 bug, found while building the retry wrapper)**: `_request`'s existing generic retry loop treats both HTTP 500 and 503 as retryable. Left unfixed, a real MVCC conflict (503) would have been blindly retried at the transport layer, and the *second* attempt (on the now-invalidated session) would return the unrelated 500 "Transaction not begun" error — destroying the conflict signal before `run_in_transaction` ever saw it. Fixed by having `_request` skip its own retry specifically when the error body matches `is_mvcc_conflict`, so the true signal always survives to reach the caller-level retry policy.
- **`rollback()` called defensively (not guarded further) after any `body()`/`commit()` failure** in `run_in_transaction`: confirmed live that `rollback` after a failed commit or a failed command both return 204 (idempotent, safe), so no special-casing was needed beyond a `try/except RuntimeError: pass` in case a genuinely unreachable server also fails the cleanup rollback.
- **Test file marker refactor**: moved `pytestmark = pytest.mark.integration` from module scope to per-function decorators on the 7 pre-existing live-container tests. This was necessary (not optional) because the module-level marker would have incorrectly gated the 9 new mocked-HTTP unit tests behind a live-container dependency they don't need, defeating the purpose of writing them as fast, hermetic unit tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed transport-retry masking of the MVCC conflict signal**
- **Found during:** Task 1 (building the commit-retry-N wrapper)
- **Issue:** `_request`'s pre-existing generic transport retry loop (`_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}`) would blindly retry a `commit()` call that failed with an MVCC conflict (HTTP 503). Because ArcadeDB invalidates the session on any failure, the retried request returns a *different* error (HTTP 500, `TransactionException`, "Transaction not begun") — destroying the original conflict signal before any caller-level retry logic (including the very wrapper this task builds) could see it. Confirmed live by inducing an actual conflict against the running `arcadedb` container.
- **Fix:** `_request`'s `HTTPError` handling now reads the error body first and skips its own retry when `is_mvcc_conflict(detail)` is true, regardless of remaining transport attempts, so the conflict signal is raised immediately and intact. `run_in_transaction` owns all retry policy for that one signal instead.
- **Files modified:** `src/turing_agentmemory_mcp/arcadedb_client.py`
- **Verification:** `tests/test_arcadedb_client.py::test_commit_conflict_retries_whole_transaction_then_succeeds`, `::test_commit_conflict_exhausts_bounded_retry_budget_then_raises`, `::test_non_conflict_500_is_not_retried_by_the_mvcc_wrapper`
- **Committed in:** `cfdf88c` (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Restructured test-file markers so new unit tests aren't gated behind live infra**
- **Found during:** Task 1 (adding mocked-HTTP unit tests to `tests/test_arcadedb_client.py`)
- **Issue:** The file previously applied `pytestmark = pytest.mark.integration` at module scope, marking every test in the file — including the new mocked-`urlopen` unit tests this plan needed to add, which require no live container. Leaving this in place would have made the new unit tests silently gated behind `docker compose up -d arcadedb`, contradicting the plan's own goal of tests that "skip cleanly when unreachable" for the *live* tests only.
- **Fix:** Moved the marker to per-function `@pytest.mark.integration` decorators on the 7 pre-existing live-container smoke tests (matched 1:1 with the plan's "Wave-1's 7 smoke tests still pass" acceptance criterion); the 9 new unit tests are unmarked and run in the default/fast tier.
- **Files modified:** `tests/test_arcadedb_client.py`
- **Verification:** `pytest tests/test_arcadedb_client.py -q -m "not integration"` runs 9 tests with zero live dependency; `pytest tests/test_arcadedb_client.py -q` runs all 16 (9 unit + 7 live, container was up) green.
- **Committed in:** `8622a88` (Task 1 RED commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking test-structure fix)
**Impact on plan:** Both were necessary for correctness (the masking bug would have silently broken the exact feature this task built) and to complete the task as specified (the marker fix). No scope creep — no store/query-builder code was touched.

## Issues Encountered

None beyond the deviations above. The live `arcadedb` container (already running healthy from Wave 1) was used directly to empirically confirm the MVCC conflict wire contract via a throwaway scratch database (`mvcc_probe_db*`), dropped after each probe; no lasting state left in the container.

## User Setup Required

None - no external service configuration required. New env var `ARCADEDB_COMMIT_RETRIES` (default `3`) follows the existing `ARCADEDB_*` convention already documented for 04-01; no `.env.example` change was required by this plan (compose/env wiring for the full stack is later-wave work).

## Next Phase Readiness

`ArcadeDBClient`'s full surface is now ready for 04-03 (schema bootstrap) and 04-04 (core seam / `store_core.py` port): `query`/`command`/`sqlscript`/`begin`/`commit`/`rollback`, `run_in_transaction` for D-08's single-managed-transaction write path, and `is_ready`/`probe` for D-10's readiness wiring into `RuntimeSignals.configure_stage`/`/health`. No blockers. The final method surface for Wave 3 to build against:

```
ArcadeDBClient.query(statement, *, params=None, language="sql", session_id=None) -> list[dict]
ArcadeDBClient.command(statement, *, params=None, language="sql", session_id=None) -> list[dict]
ArcadeDBClient.sqlscript(body, *, params=None, session_id=None) -> list[dict]
ArcadeDBClient.begin() -> str
ArcadeDBClient.commit(session_id) -> None
ArcadeDBClient.rollback(session_id) -> None
ArcadeDBClient.run_in_transaction(body: Callable[[str], T], *, commit_retries=None) -> T
ArcadeDBClient.is_ready() -> bool   (alias: probe)
ArcadeDBClient.ensure_database() -> None
```

No concern-split was needed this wave — the file grew from 212 to 312 LOC, well under the 600-LOC cap.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-13*

## Self-Check: PASSED

- FOUND: `src/turing_agentmemory_mcp/arcadedb_client.py`
- FOUND: `tests/test_arcadedb_client.py`
- FOUND: `.planning/phases/04-arcadedb-direct-port/04-02-SUMMARY.md`
- FOUND: commit `8622a88` (test: RED)
- FOUND: commit `cfdf88c` (feat: GREEN)
- `python -m pytest tests/test_arcadedb_client.py -q` — 16 passed
- `python -m ruff check src tests` — all checks passed
- `bash scripts/check-file-size.sh` — all tracked *.py files within the 600-LOC cap
