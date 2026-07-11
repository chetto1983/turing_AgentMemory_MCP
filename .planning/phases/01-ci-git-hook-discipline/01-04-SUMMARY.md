---
phase: 01-ci-git-hook-discipline
plan: 04
subsystem: infra
tags: [file-size-cap, refactor, operator-scripts, benchmark, locomo]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline
    provides: "D-08/D-09 no-allowlist 600-LOC file-size cap decision; scripts/ scanned like every other tracked *.py"
provides:
  - "scripts/real_document_benchmark.py at 586 LOC (was 827) with a new scripts/real_document_benchmark_scoring.py sibling (294 LOC)"
  - "scripts/eval_backboard_locomo_mcp.py at 524 LOC (was 936) with a new scripts/eval_backboard_locomo_mcp_dataset.py sibling (503 LOC)"
  - "All four tracked scripts/eval_backboard_locomo_mcp*.py and scripts/real_document_benchmark*.py files at or under the 600-LOC cap"
affects: [scripts/check-file-size.sh, .github/workflows/ci.yml file-size job, any future plan touching these two operator benchmark scripts]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flat scripts/ sibling split by concern (no package/__init__.py) — matches scripts/benchmark.py's thin-shim convention and the src/turing_agentmemory_mcp/benchmark.py, e2e_score.py, gliner_provider.py mixin-sibling precedent from this same phase"
    - "Dual-mode sibling import (try bare import, except ImportError fall back to `scripts.<name>` dotted import) so the split resolves both under `python -m pytest` (repo root on sys.path, scripts/ is an implicit namespace package) and under `python scripts/<name>.py` direct execution (script's own dir on sys.path[0], no scripts/ package visible)"
    - "`# noqa: F401 - some re-exported for tests` on re-export import blocks, matching the exact convention already used in src/turing_agentmemory_mcp/benchmark.py, e2e_score.py, and gliner_provider.py"
    - "Monkeypatch-sensitive functions (call_tool and everything that calls it at module-global scope: ingest_conversation, evaluate_question, evaluate_conversation) kept co-located in the original module rather than moved to a sibling, because tests/test_backboard_locomo_runner.py does `monkeypatch.setattr(runner, \"call_tool\", fake_call)` and relies on those functions resolving `call_tool` via their own module's globals at call time — moving them to a sibling that imports call_tool separately would silently break the patch"

key-files:
  created:
    - scripts/real_document_benchmark_scoring.py
    - scripts/eval_backboard_locomo_mcp_dataset.py
  modified:
    - scripts/real_document_benchmark.py
    - scripts/eval_backboard_locomo_mcp.py

key-decisions:
  - "real_document_benchmark.py split: deterministic/pure helpers (utc_timestamp, load_env_file, safe_id, normalize_text, normalized_tokens, source_units, select_evidence, file_digest, select_passages, _json_object_from_text, parse_generated_questions, evidence_rank, _metrics, summarize_results) moved to real_document_benchmark_scoring.py; the live-MCP CLI (parse_args, QuestionGenerator, tool_payload, upload_document, wait_for_jobs, search_questions, atomic_json_write, run, main) stayed in the original"
  - "eval_backboard_locomo_mcp.py split: all dataset/message-building/metrics helpers (parse_args, utc_timestamp, git_commit, safe_id, session_number, session_keys, turn_content, build_messages, chunks, normalize_text, estimate_tokens, retrieval_cutoffs, validate_batch_size, validate_search_concurrency, mcp_transport, answer_in_hits, result_ref, compact_hit, retrieval_diagnostics, summarize_entity_extraction, require_entity_model, extraction_summary_from_runtime, resume_state, question_rows, init_metric_counts, update_metrics, finalize_metrics, plus CATEGORY_NAMES/COMPARABLE_CUTOFFS/MAX_INGEST_BATCH/MAX_SEARCH_CONCURRENCY and the ResumeState/QuestionEvaluation NamedTuples) moved to eval_backboard_locomo_mcp_dataset.py; call_tool, ingest_conversation, evaluate_question, evaluate_conversation, run, main stayed in the original specifically to preserve the monkeypatch(runner, \"call_tool\", ...) test contract"

requirements-completed: [CI-01]

coverage:
  - id: D1
    description: "scripts/real_document_benchmark.py decomposed to 586 LOC via a new real_document_benchmark_scoring.py sibling; evidence_rank, normalize_text, parse_generated_questions, select_evidence, select_passages, summarize_results remain importable from scripts.real_document_benchmark unchanged"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "tests/test_real_document_benchmark.py (10 tests)"
        status: pass
      - kind: other
        ref: "py_compile scripts/real_document_benchmark.py scripts/real_document_benchmark_scoring.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "scripts/eval_backboard_locomo_mcp.py decomposed to 524 LOC via a new eval_backboard_locomo_mcp_dataset.py sibling; every symbol tests/test_backboard_locomo_runner.py accesses via runner.<name> (including monkeypatched call_tool consumers) still resolves"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "tests/test_backboard_locomo_runner.py (16 tests)"
        status: pass
      - kind: other
        ref: "py_compile scripts/eval_backboard_locomo_mcp.py scripts/eval_backboard_locomo_mcp_dataset.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Full suite stays at the 362-test green baseline and ruff stays clean after both splits; no tracked scripts/eval_backboard_locomo_mcp*.py or scripts/real_document_benchmark*.py file exceeds 600 LOC"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "python -m pytest -q (362 passed)"
        status: pass
      - kind: other
        ref: "python -m ruff check src tests scripts"
        status: pass
      - kind: other
        ref: "git ls-files 'scripts/eval_backboard_locomo*.py' 'scripts/real_document_benchmark*.py' line-count check (524, 503, 586, 294)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Docker E2E score gate (scripts/e2e_score.py) validates the dockerized stack end-to-end — not runnable on this Windows host per the environment constraint"
    verification: []
    human_judgment: true
    rationale: "scripts/e2e_score.py requires turingdb + live provider endpoints; this Windows executor host cannot install/import turingdb. Deferred to the wave-level Docker E2E run the orchestrator performs after all Wave 1 plans land."

# Metrics
duration: 20min
completed: 2026-07-11
status: complete
---

# Phase 1 Plan 04: Decompose over-cap operator benchmark scripts Summary

**Split `scripts/eval_backboard_locomo_mcp.py` (936→524 LOC) and `scripts/real_document_benchmark.py` (827→586 LOC) into flat `scripts/` concern siblings, preserving every tested import path and the `call_tool` monkeypatch contract, with zero runtime behavior change.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-07-11T21:05:00Z (approx)
- **Completed:** 2026-07-11T21:15:00Z
- **Tasks:** 2
- **Files modified:** 4 (2 slimmed originals, 2 new siblings)

## Accomplishments
- `scripts/real_document_benchmark.py` reduced from 827 to 586 LOC by extracting all deterministic/pure helpers (evidence grounding, passage selection, question parsing, result scoring) into `scripts/real_document_benchmark_scoring.py` (294 LOC); the live-MCP upload/ingest/search CLI stayed in the original.
- `scripts/eval_backboard_locomo_mcp.py` reduced from 936 to 524 LOC by extracting dataset loading, LoCoMo message building, and deterministic metrics helpers into `scripts/eval_backboard_locomo_mcp_dataset.py` (503 LOC); `call_tool` and everything that calls it (`ingest_conversation`, `evaluate_question`, `evaluate_conversation`) stayed co-located in the original to preserve `tests/test_backboard_locomo_runner.py`'s `monkeypatch.setattr(runner, "call_tool", fake_call)` contract.
- All four tracked files are now at or under the 600-LOC cap with no allowlist exemption (D-08/D-09).
- Both scripts remain runnable-by-path with unchanged CLI entrypoints and argument surfaces; neither is wired into CI (D-10).
- Full 362-test suite stays green; `ruff check src tests scripts` stays clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: Split scripts/real_document_benchmark.py (preserve tested helpers)** - `e2481e9` (refactor)
2. **Task 2: Split scripts/eval_backboard_locomo_mcp.py (preserve tested symbols)** - `ad1c34e` (refactor)

**Plan metadata:** (this commit, following SUMMARY.md creation)

## Files Created/Modified
- `scripts/real_document_benchmark_scoring.py` - New sibling: evidence grounding, passage/question parsing, and result scoring helpers (evidence_rank, normalize_text, parse_generated_questions, select_evidence, select_passages, summarize_results, plus internal utc_timestamp/load_env_file/safe_id/file_digest)
- `scripts/real_document_benchmark.py` - Slimmed to the live-MCP CLI (parse_args, QuestionGenerator, upload_document, wait_for_jobs, search_questions, atomic_json_write, run, main); re-imports the scoring sibling via a dual-mode try/except so both `python -m pytest` and `python scripts/real_document_benchmark.py` resolve it
- `scripts/eval_backboard_locomo_mcp_dataset.py` - New sibling: dataset loading (parse_args, git_commit, session/turn parsing, build_messages), retrieval metrics (init_metric_counts, update_metrics, finalize_metrics, retrieval_cutoffs), and diagnostics (compact_hit, retrieval_diagnostics, summarize_entity_extraction, require_entity_model)
- `scripts/eval_backboard_locomo_mcp.py` - Slimmed to the async MCP-bridge runner (call_tool, ingest_conversation, evaluate_question, evaluate_conversation, run, main); re-imports the dataset sibling via the same dual-mode try/except

## Decisions Made
- **Monkeypatch co-location constraint (eval_backboard_locomo_mcp.py):** `call_tool`, `ingest_conversation`, `evaluate_question`, and `evaluate_conversation` were kept in the original module rather than moved, because `tests/test_backboard_locomo_runner.py` monkeypatches `runner.call_tool` (a module-global rebind) and the calling functions must resolve that name via their own module's globals at call time. Moving them to a sibling that imports `call_tool` by value at import time would have frozen the reference and silently broken the patched tests. This is the primary boundary that shaped the split (everything else — dataset/metrics — was safe to move since none of it depends on live rebinding).
- **Dual-mode sibling import pattern:** Both slimmed originals use `try: from <sibling> import (...) except ImportError: from scripts.<sibling> import (...)`, because `scripts/` has no `__init__.py` and the two execution modes put different directories on `sys.path[0]` (repo root under `python -m pytest`, the script's own directory under `python scripts/<name>.py`). This satisfies the plan's key_link that sibling scripts must resolve when run directly by path.
- **`# noqa: F401 - some re-exported for tests` re-export marker:** Matches the exact convention already established this phase in `src/turing_agentmemory_mcp/benchmark.py`, `e2e_score.py`, and `gliner_provider.py` for import blocks that mix internally-used and test-only-re-exported names.

## Deviations from Plan

None - plan executed exactly as written. Both tasks followed the plan's stated split boundaries (deterministic helpers vs. live-MCP runner for real_document_benchmark.py; dataset/metrics helpers vs. call_tool-dependent orchestration for eval_backboard_locomo_mcp.py) and the acceptance criteria (`pytest` on the two affected test files, full 362-test suite, ruff, LOC cap) all passed without needing bug fixes, missing-functionality additions, or architectural changes.

## Issues Encountered

None. The one non-obvious risk — `monkeypatch.setattr(runner, "call_tool", fake_call)` breaking if `ingest_conversation`/`evaluate_conversation` moved to a sibling that imported `call_tool` by value — was identified during read-first analysis of `tests/test_backboard_locomo_runner.py` before writing any code, and avoided by keeping those four functions in the original module.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Threat Flags

None. Both threats identified in the plan's `<threat_model>` (T-04-01: a moved tested helper breaking its unit test; T-04-02: a sibling import failing to resolve at runtime) are exactly what this plan's verification covers, and both are mitigated: `tests/test_real_document_benchmark.py` (10/10) and `tests/test_backboard_locomo_runner.py` (16/16) pass, and the dual-mode try/except import resolves sibling imports in both `pytest` and direct `python scripts/<name>.py` execution modes.

## Next Phase Readiness

- All operator-script file-size violations flagged for Phase 1 are resolved; `scripts/check-file-size.sh` (once landed by a sibling plan in this phase) will find zero violations under `scripts/`.
- **Docker E2E deferred:** `scripts/e2e_score.py` and `docker compose run --rm e2e` were not run on this Windows executor host per the environment constraint (these scripts import `turingdb`, which cannot be installed here). The orchestrator's wave-level Docker E2E run after all Wave 1 plans land is the gate that validates end-to-end correctness; this plan's changes are structural-only (behavior-preserving refactor of two operator tools not wired into CI per D-10), so no retrieval-affecting risk is introduced.
- No blockers for downstream Phase 1 plans.

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

All created/modified files verified present on disk; both task commits (`e2481e9`, `ad1c34e`) verified present in git history.
