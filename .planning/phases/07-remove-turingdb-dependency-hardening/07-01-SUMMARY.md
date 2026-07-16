---
phase: 07-remove-turingdb-dependency-hardening
plan: 01
subsystem: infra
tags: [turingdb-removal, cli, benchmark-harness, admin-tooling, gate-guard]

# Dependency graph
requires:
  - phase: 06-migration-correctness-gate
    provides: "gate_guard.assert_gate_go + baseline/06-gate/gate-result.json (verdict=GO) authorizing irreversible TuringDB removal"
provides:
  - "Deletion of the legacy TuringDB-only benchmark/eval harness cluster (benchmark.py + 3 siblings + agent_quality_eval.py + 2 scripts wrappers + 2 test files)"
  - "Deletion of admin_repair.py (all three functions, whole-file discretion decision) + its test"
  - "cli.py pruned to the five live subcommands (serve, file-pipe, e2e-score, utcp-manual, lab)"
affects: [07-02-strip-live-turingdb-imports, 07-04-test-stub-sweep, 07-05-compose-env-rename]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Phase-entry gate assertion (gate_guard.assert_gate_go) as an irreversible-removal precondition, not new guard infra"]

key-files:
  created: []
  modified:
    - src/turing_agentmemory_mcp/cli.py
    - .gitignore

key-decisions:
  - "Deleted admin_repair.py wholesale (all three functions), not just the CLI-wired repair_vector_index, per 07-RESEARCH.md Pitfall 3's documented discretion point"

patterns-established: []

requirements-completed: [ARC-10]

coverage:
  - id: D1
    description: "Phase-6 GO gate asserted as the Phase-7 entry precondition (gate_guard.assert_gate_go against baseline/06-gate/gate-result.json, verdict=GO)"
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "python -c \"... assert_gate_go(Path('baseline/06-gate/gate-result.json'))\" prints GO, exit 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "Legacy TuringDB benchmark/eval harness cluster (benchmark.py, benchmark_stages.py, benchmark_memoryarena.py, benchmark_schema.py, agent_quality_eval.py, scripts/benchmark.py, scripts/agent_quality_eval.py, tests/test_benchmark.py, tests/test_agent_quality_eval.py) deleted; memoryarena.py and scripts/real_document_benchmark.py kept intact"
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "python -m pytest tests/ --collect-only -q -> 872 tests collected, zero collection errors"
        status: pass
    human_judgment: false
  - id: D3
    description: "admin_repair.py + tests/test_admin_repair.py deleted; cli.py pruned to serve/file-pipe/e2e-score/utcp-manual/lab, agent-quality-eval and repair-vector-index dispatch removed"
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "python -m turing_agentmemory_mcp.cli --help lists only serve/file-pipe/e2e-score/utcp-manual/lab"
        status: pass
      - kind: unit
        ref: "python -m ruff format --check src/turing_agentmemory_mcp/cli.py && python -m ruff check src/turing_agentmemory_mcp/cli.py"
        status: pass
      - kind: unit
        ref: "python -m pytest -m \"not integration and not gpu\" -q -> 853 passed, 1 pre-existing unrelated skip (missing optional utcp package), 10 deselected"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-07-16
status: complete
---

# Phase 7 Plan 1: Delete legacy TuringDB harness + admin_repair.py Summary

**Deleted the confirmed-dead legacy TuringDB benchmark/eval harness cluster and the ArcadeDB-meaningless admin_repair.py, pruning cli.py to its five live subcommands, after asserting the Phase-6 GO gate as the irreversible-removal precondition**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-16T19:00:24Z
- **Completed:** 2026-07-16T19:05:38Z
- **Tasks:** 3 completed
- **Files modified:** 13 (11 deleted, 2 edited)

## Accomplishments
- Asserted `gate_guard.assert_gate_go(Path("baseline/06-gate/gate-result.json"))` — verdict GO, `baseline/` provenance untouched — authorizing the irreversible removal that follows
- Deleted the 9-file legacy TuringDB-only harness cluster (`benchmark.py`, `benchmark_stages.py`, `benchmark_memoryarena.py`, `benchmark_schema.py`, `agent_quality_eval.py`, `scripts/benchmark.py`, `scripts/agent_quality_eval.py`, `tests/test_benchmark.py`, `tests/test_agent_quality_eval.py`) and dropped the now-dead `.turingdb/` `.gitignore` entry, while keeping the distinctly-named `memoryarena.py` and `scripts/real_document_benchmark.py` (the live ArcadeDB-era files) untouched
- Deleted `admin_repair.py` (all three functions) and `tests/test_admin_repair.py` wholesale, then pruned both the `agent-quality-eval` and `repair-vector-index` subparsers + dispatch from `cli.py`, leaving `serve`/`file-pipe`/`e2e-score`/`utcp-manual`/`lab` byte-for-byte unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Assert the Phase-6 GO gate** — no files modified (read-only precondition assertion), folded into the Task 2 commit's verification narrative
2. **Task 2: Delete the legacy TuringDB benchmark/eval harness cluster** - `d09144f` (feat)
3. **Task 3: Delete admin_repair.py and prune both dead cli.py subcommands** - `4da1746` (feat)

_Note: Task 1 produced no diff (gate assertion only) — its `GO` result is recorded in the Task 2 commit message and reverified independently below._

## Files Created/Modified
- `src/turing_agentmemory_mcp/benchmark.py` (deleted) — legacy TuringDB-backed pipeline-stage benchmark runner, superseded by `e2e_score.py`/`real_document_benchmark.py`
- `src/turing_agentmemory_mcp/benchmark_stages.py` (deleted) — imported the dead `turingdb_version` field
- `src/turing_agentmemory_mcp/benchmark_memoryarena.py` (deleted) — distinct from the kept `memoryarena.py`
- `src/turing_agentmemory_mcp/benchmark_schema.py` (deleted) — held the literal `from turingdb import __version__ as turingdb_version`
- `src/turing_agentmemory_mcp/agent_quality_eval.py` (deleted) — instantiated a real `TuringDaemon` subprocess, read `TURINGDB_AGENT_QUALITY_HOME`
- `scripts/benchmark.py`, `scripts/agent_quality_eval.py` (deleted) — thin CLI wrappers, dead once their targets were deleted
- `tests/test_benchmark.py`, `tests/test_agent_quality_eval.py` (deleted) — direct tests of the deleted cluster
- `src/turing_agentmemory_mcp/admin_repair.py` (deleted) — TuringDB CSV vector-repair + dead-read-path sparse/community repair, all three functions
- `tests/test_admin_repair.py` (deleted) — direct test of the deleted file
- `.gitignore` — removed the now-dead `.turingdb/` entry
- `src/turing_agentmemory_mcp/cli.py` — removed the `agent-quality-eval` and `repair-vector-index` subparsers + dispatch; `serve`/`file-pipe`/`e2e-score`/`utcp-manual`/`lab` unchanged

## Decisions Made
- Deleted `admin_repair.py` wholesale (all three functions: `repair_vector_index`, `repair_sparse_projection`, `repair_community_projection`), not just the CLI-wired `repair_vector_index` — per 07-RESEARCH.md's documented Pitfall 3 discretion point. Rationale: `repair_vector_index` targets a TuringDB CSV `vector/` directory meaningless under ArcadeDB's native `LSM_VECTOR`/HNSW; `repair_sparse_projection` rebuilds the SQLite-FTS5 `SparseIndex` that `store_evidence.py:116-119` proves is already dead for reads; `repair_community_projection` was never CLI-wired at all. All three are dead/unreachable in the ArcadeDB reality, consistent with the phase's aggressive debt-clearing scope (D-01).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Task 1's gate assertion produced no file diff (as expected — it's a read-only precondition check), so it has no standalone commit; its `GO` result is documented in this Summary and was independently reverified during overall plan verification.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The two surviving live `from turingdb import ...` call sites (`e2e_score.py`, `e2e_score_stubs.py`) and the stale docstrings/comments in `store_core.py`/`store_documents.py`/`store_rebuild.py`/`store.py` are unaffected by this plan and remain in scope for 07-02, per the RESEARCH-documented sequencing (src-side import removal must precede the 31-file test-stub sweep in 07-04).
- `pyproject.toml`'s `turingdb==1.35` dependency, `compose.yaml`'s TuringDB services, and the `TURINGDB_HOME`/`TURINGDB_GRAPH` env-var renames are all still pending in later plans of this phase — no blockers introduced by this plan.
- Full unit suite green (853 passed, 1 pre-existing unrelated skip, 10 deselected), `docker compose config --quiet` clean, ruff format/check clean, file-size cap clean — safe baseline for 07-02.

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: `.planning/phases/07-remove-turingdb-dependency-hardening/07-01-SUMMARY.md`
- FOUND: `src/turing_agentmemory_mcp/benchmark.py` deleted (does not exist)
- FOUND: `src/turing_agentmemory_mcp/admin_repair.py` deleted (does not exist)
- FOUND: `src/turing_agentmemory_mcp/memoryarena.py` kept intact
- FOUND: commit `d09144f` (Task 2)
- FOUND: commit `4da1746` (Task 3)
