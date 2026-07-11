---
phase: 01-ci-git-hook-discipline
plan: 06
subsystem: infra
tags: [ruff, formatting, ci, python, testing]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline (plans 01-05)
    provides: all 10 over-cap files decomposed into ≤600-LOC concern modules (Wave 1)
provides:
  - Repo-wide ruff-format-clean tree (ruff format --check exits 0 across src/tests/scripts)
  - Behavior-preservation proof on the merged, reformatted Wave-1 tree (362 pytest, ruff check clean, zero files >600 LOC)
  - tests/test_entity_extraction_http.py split (HTTP-backend GLiNER tests), keeping test_entity_extraction.py under the cap post-format
affects: [01-07, 01-08, 01-09]

# Tech tracking
tech-stack:
  added: []
  patterns: ["one-time repo-wide ruff format bootstrap pass (D-09a) before enabling a format pre-commit hook"]

key-files:
  created:
    - tests/test_entity_extraction_http.py
  modified:
    - 70 files across src/, tests/, scripts/ (ruff format only)
    - tests/test_entity_extraction.py (formatted, then split)

key-decisions:
  - "Followed the orchestrator's explicit Windows-environment instruction: did NOT run scripts/e2e_score.py locally (turingdb has no Windows wheel) and did NOT chase VALIDATED_10_10; behavior-preservation signal is pytest staying at 362 passed, per plan's stated fallback."

patterns-established:
  - "Formatting-only bootstrap passes must re-check the 600-LOC cap after running — ruff format can push a near-boundary file over the line via multi-line-call expansion, and the fix is a Wave-1-style concern split, not touching the ruff config."

requirements-completed: [CI-01]

coverage:
  - id: D1
    description: "Repo-wide ruff format bootstrap pass applied; ruff format --check now exits 0 across src/tests/scripts"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "ruff format --check src tests scripts"
        status: pass
    human_judgment: false
  - id: D2
    description: "Full pytest suite stays green (362 passed) on the merged, reformatted Wave-1 tree — behavior preserved"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "python -m pytest -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every tracked *.py file is ≤600 LOC on the merged tree (zero files over cap, including the format-pass-induced test_entity_extraction.py split)"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "git ls-files '*.py' | while read f; do n=$(wc -l < \"$f\"); [ \"$n\" -le 600 ] || echo OVER:$f:$n; done"
        status: pass
    human_judgment: false
  - id: D4
    description: "E2E behavior-preservation on the merged tree via the Docker stub gate — score unchanged from the pre-phase baseline (not run locally on Windows per environment constraint)"
    verification: []
    human_judgment: true
    rationale: "turingdb has no Windows wheel; scripts/e2e_score.py cannot run locally in this environment. The orchestrator runs the real E2E via Docker after this wave and verifies the stub gate stays at the pre-existing baseline (9.474, 18/19 — the document_search_retrieves_exact_top1 gap is a pre-existing HashingEmbedder-stub limitation, unrelated to this formatting-only plan)."

# Metrics
duration: ~15min
completed: 2026-07-11
status: complete
---

# Phase 1 Plan 06: Ruff Format Bootstrap Pass Summary

**Repo-wide `ruff format` bootstrap pass under pinned ruff 0.15.21 — 70 files reformatted, `ruff format --check` clean, 362 pytest unchanged, zero tracked `*.py` over the 600-LOC cap.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2
- **Files modified:** 71 (70 reformatted + 1 new split test file)

## Accomplishments
- Ran `ruff format src tests scripts` once across the whole tree (D-09a): 70 of 105 tracked files were reformatted, 35 were already clean. `ruff format --check src tests scripts` now exits 0 — the pre-commit hook 01-07 wires up will not self-block on pre-existing drift.
- Verified the merged result of all five Wave-1 decompositions plus the format pass preserves behavior: `python -m pytest -q` reports 362 passed both before and after the format pass (identical to the Wave-1 baseline).
- `ruff check src tests scripts` stays clean (no new lint violations from the format pass).
- Full-tree file-size sweep confirmed via `git ls-files '*.py' | while read f; do ... done` — zero output, meaning no tracked `*.py` exceeds 600 LOC.

## Task Commits

Each task was committed atomically:

1. **Task 1: Repo-wide ruff format bootstrap pass (D-09a)** — `22d2e8b` (style) — includes the required `tests/test_entity_extraction.py` split (deviation below), since both changes had to land together to keep the tree format-clean AND ≤600-LOC-compliant at every commit.

Task 2 (full behavior-preservation gate on the merged tree) ran verification only — no source files changed, so no separate commit; its acceptance criteria (pytest 362, ruff check/format clean, zero files over cap) are all satisfied by the state left after Task 1's commit and are re-confirmed below.

**Plan metadata:** commit created via `commit` step below (see Files Created/Modified).

## Files Created/Modified
- `tests/test_entity_extraction_http.py` (new, 246 LOC) — HTTP-backend GLiNER entity-extraction tests, split out of `test_entity_extraction.py`
- `tests/test_entity_extraction.py` (370 LOC after split) — local/native-backend GLiNER entity-extraction tests + the generic `entity_metadata_search_text` test
- 68 other `src/`, `tests/`, `scripts/` files — formatting-only changes from `ruff format` (no logic changes; see `git show 22d2e8b --stat`)

## Decisions Made
- Did not run `scripts/e2e_score.py` locally — turingdb has no Windows wheel, so it cannot execute in this environment. Per the orchestrator's explicit Windows-environment guidance, the behavior-preservation signal for this plan is `pytest -q` staying at 362 passed (formatting must be behavior-neutral); the Docker E2E stub gate is verified by the orchestrator after this wave and is expected to remain at the pre-existing baseline of 9.474 (18/19) — the one failing check (`document_search_retrieves_exact_top1_...`) is a pre-existing HashingEmbedder-stub limitation unrelated to this formatting pass.
- Did not touch `pyproject.toml`'s ruff pin (still `ruff>=0.9`) — the venv already has the pinned `0.15.21` installed and the plan's Task 1 only required using that version for the format pass, not rewriting the pin. Bumping the pin in `pyproject.toml` is L-04's job (CI wiring, a later plan in this phase), not this bootstrap plan's `files_modified` scope.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug / Rule 3 - Blocking] Split `tests/test_entity_extraction.py` after the format pass pushed it over the 600-LOC cap**
- **Found during:** Task 1 (repo-wide ruff format pass), confirmed blocking during Task 2's file-size sweep
- **Issue:** Before the format pass, `tests/test_entity_extraction.py` was 598 LOC (under cap, not one of the 10 files D-09 identified as over-cap). `ruff format` expanded several multi-line calls (magic-trailing-comma / line-wrapping), pushing it to 612 LOC — over the no-allowlist 600-LOC cap (D-08/D-09) that this plan's own acceptance criteria require to be zero-violation on the merged tree.
- **Fix:** Split the file into two concern-named siblings, mirroring the exact pattern already used for `test_gliner_provider.py`/`test_batch_memory.py` in Wave 1: `tests/test_entity_extraction.py` (370 LOC — local/native GLiNER backend tests: `gliner2_onnx`, `gliner`, `gliner2`, malformed-span/normalization helpers, plus the generic `entity_metadata_search_text` test) and `tests/test_entity_extraction_http.py` (246 LOC — `gliner2_http` backend tests). No test logic was altered; every assertion, fixture, and monkeypatch was moved verbatim.
- **Files modified:** `tests/test_entity_extraction.py`, `tests/test_entity_extraction_http.py` (new)
- **Verification:** `ruff format --check` clean on both files; `ruff check` clean; `python -m pytest tests/test_entity_extraction.py tests/test_entity_extraction_http.py -q` → 19 passed (matches the original file's 19 test functions, 12+7 split); full suite still 362 passed; full-tree LOC sweep now empty.
- **Committed in:** `22d2e8b` (part of Task 1's commit, since the format pass and the resulting cap fix had to land together — the tree must never be in a state where it's format-clean but cap-violating, or vice versa)

---

**Total deviations:** 1 auto-fixed (Rule 1/3 — blocking cap violation caused by the formatting pass itself)
**Impact on plan:** Necessary to satisfy the plan's own explicit acceptance criteria ("zero tracked *.py over 600 LOC" and "ruff format --check clean" must both hold simultaneously on the merged tree). No scope creep — the split only touched the one file the format pass pushed over cap.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The tree is fully `ruff format`-clean, ≤600-LOC-compliant, and behaviorally green (362 pytest, `ruff check` clean) — the mandatory bootstrap gate (phase-critical constraint #2) is satisfied. Plan 01-07 (lefthook pre-commit hook wiring) can now enable `ruff format --check` as a commit gate without self-blocking on pre-existing drift.
- E2E behavior-preservation on the merged tree is NOT independently re-verified in this environment (Windows, no turingdb wheel) — the orchestrator's Docker E2E run after this wave is the authoritative check; expected result is the unchanged pre-phase baseline (9.474, 18/19).

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

- FOUND: tests/test_entity_extraction_http.py
- FOUND: tests/test_entity_extraction.py
- FOUND: .planning/phases/01-ci-git-hook-discipline/01-06-SUMMARY.md
- FOUND: 22d2e8b (git log --oneline --all)
