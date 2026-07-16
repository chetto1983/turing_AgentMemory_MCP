---
phase: 07-remove-turingdb-dependency-hardening
plan: 05
subsystem: testing
tags: [pytest, graspologic-native, fastmcp, importlib-metadata, grep-gate, compat-smoke]

# Dependency graph
requires:
  - phase: 07-01
    provides: src-side turingdb import removal (all live call sites cut)
  - phase: 07-02
    provides: pyproject.toml turingdb dependency removal
provides:
  - src-wide grep-gate proving zero turingdb imports remain anywhere in src/turing_agentmemory_mcp
  - graspologic-native version-pin + live hierarchical_leiden compat-smoke (DEP-01)
  - fastmcp version-range + create_mcp_app tool-registration compat-smoke (DEP-02)
affects: [07-08 (phase close), any future graspologic-native/fastmcp version bump]

# Tech tracking
tech-stack:
  added: []
  patterns: [rglob-based src-wide forbidden-substring grep-gate, importlib.metadata version-pin compat-smoke, dummy-store create_mcp_app() smoke]

key-files:
  created:
    - tests/test_no_turingdb_imports.py
    - tests/test_graspologic_compat.py
  modified:
    - tests/test_warning_filters.py

key-decisions:
  - "Generalized the existing test_store_arcadedb_core.py single-file forbidden-substring pattern to a src-wide rglob scan, keeping the narrower store_core.py-specific guard untouched (it also checks other forbidden TuringDB write primitives)."
  - "Extended tests/test_warning_filters.py with the DEP-02 fastmcp compat-smoke instead of creating a new overlapping file, per plan prohibition."
  - "No pytest.skip in any of the three files -- graspologic-native and fastmcp are unconditional pyproject dependencies, so a missing package is a hard failure, not a legitimate skip."

patterns-established:
  - "Pattern 1: src-wide no-import grep-gate via Path.rglob('*.py') + substring scan, distinct from narrower single-file forbidden-primitive guards."
  - "Pattern 2: unconditional-dependency compat-smoke pairs a pinned/ranged importlib.metadata.version assertion with a live call against the real API (not a fake/injected backend), so a breaking upstream bump fails CI before adoption."

requirements-completed: [ARC-10, DEP-01, DEP-02]

coverage:
  - id: D1
    description: "src-wide grep-gate asserts zero turingdb import occurrences across all of src/turing_agentmemory_mcp/*.py"
    requirement: "ARC-10"
    verification:
      - kind: unit
        ref: "tests/test_no_turingdb_imports.py::test_no_turingdb_import_anywhere_in_src"
        status: pass
    human_judgment: false
  - id: D2
    description: "graspologic-native installed version pinned at exactly 1.3.1 and a live hierarchical_leiden smoke over a tiny connected graph assigns every node to a final cluster"
    requirement: "DEP-01"
    verification:
      - kind: unit
        ref: "tests/test_graspologic_compat.py::test_graspologic_compat_version_is_pinned"
        status: pass
      - kind: unit
        ref: "tests/test_graspologic_compat.py::test_graspologic_compat_hierarchical_leiden_smoke"
        status: pass
    human_judgment: false
  - id: D3
    description: "fastmcp installed version satisfies >=3.4,<4 and create_mcp_app(store=object()).list_tools() returns at least 20 registered tools"
    requirement: "DEP-02"
    verification:
      - kind: unit
        ref: "tests/test_warning_filters.py::test_fastmcp_compat_installed_version_satisfies_pin"
        status: pass
      - kind: unit
        ref: "tests/test_warning_filters.py::test_fastmcp_compat_create_mcp_app_registers_tools"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-16
status: complete
---

# Phase 7 Plan 5: Dependency Hardening Compat Oracles Summary

**Added a src-wide no-turingdb-import grep-gate, a graspologic-native 1.3.1 pin + live Leiden smoke, and a fastmcp >=3.4,<4 range + tool-registration smoke -- all three green on today's environment with no skip path.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-16T19:52:00Z
- **Completed:** 2026-07-16T20:04:00Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments
- Generalized the existing single-file turingdb-import guard to a src-wide `rglob("*.py")` scan proving removal completeness (ARC-10), confirming Plans 01+02 already cut every src-side turingdb import.
- Added a DEP-01 compat-smoke that pins `graspologic-native==1.3.1` via `importlib.metadata.version` and runs the real `hierarchical_leiden` call with the exact live signature from `community_detection.py` over a tiny connected graph, asserting every node lands in a final cluster.
- Extended `tests/test_warning_filters.py` with a DEP-02 compat-smoke that range-checks the installed `fastmcp` version (`>=3.4,<4`) and constructs `create_mcp_app(store=object())` to assert a `>=20` tool-registration floor, reusing the dummy-store pattern already proven in `tests/test_auth.py`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create the src-wide no-turingdb-import grep-gate** - `8a2bd72` (test)
2. **Task 2: Create the DEP-01 graspologic-native compat-smoke** - `18add8f` (test)
3. **Task 3: Extend test_warning_filters.py with the DEP-02 fastmcp compat-smoke** - `d1b9777` (test)

**Plan metadata:** (this commit, docs: complete plan)

_Note: All three tasks were RED-by-construction oracle additions -- each test's own failing assertion IS its RED, no separate test-of-the-test was written, per the plan's TDD framing._

## Files Created/Modified
- `tests/test_no_turingdb_imports.py` - New; `test_no_turingdb_import_anywhere_in_src` rglobs `src/turing_agentmemory_mcp/*.py` and asserts zero `import turingdb`/`from turingdb` occurrences.
- `tests/test_graspologic_compat.py` - New; `test_graspologic_compat_version_is_pinned` (exact 1.3.1 pin) and `test_graspologic_compat_hierarchical_leiden_smoke` (live 3-node Leiden clustering).
- `tests/test_warning_filters.py` - Extended with `test_fastmcp_compat_installed_version_satisfies_pin` and `test_fastmcp_compat_create_mcp_app_registers_tools`; the two pre-existing tests (`test_fastmcp_import_is_deprecation_clean`, `test_project_requires_fastmcp_v3`) are unchanged.

## Decisions Made
- Kept the existing `test_seam_contains_no_turingdb_write_primitives_or_csv_vector_load` in `test_store_arcadedb_core.py` untouched; it checks other forbidden TuringDB write primitives (`new_change`, `CHANGE SUBMIT`, `LOAD VECTOR`) specific to `store_core.py`, a distinct and still-valid assertion from the new src-wide scan.
- Extended `test_warning_filters.py` rather than creating a new file, per the plan's explicit prohibition against a second overlapping fastmcp-pin file.
- No `pytest.skip` anywhere in the three files -- both `graspologic-native` and `fastmcp` are unconditional dependencies, so there is no legitimate skip condition; a missing/incompatible package produces a hard failure.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All acceptance criteria verified directly:
- `python -m pytest tests/test_no_turingdb_imports.py tests/test_graspologic_compat.py tests/test_warning_filters.py -q` -> 7 passed.
- `python -m pytest -q -k graspologic_compat` and `-k fastmcp_compat` both select and pass their respective new tests (an unrelated pre-existing collection-time skip elsewhere in the suite appears in both runs' summary line but is not part of this plan's files).
- `grep -c pytest.skip` across all three files returns 0.
- `python -m ruff format --check tests` and `python -m ruff check tests` pass; `scripts/check-file-size.sh` reports all files within the 600-LOC cap.
- `python -m pytest tests/test_store_arcadedb_core.py -q` still passes (existing narrower guard preserved).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ARC-10, DEP-01, DEP-02 requirements delivered by this plan and marked complete.
- The three oracles are now permanent CI tripwires: any future turingdb-import regression, graspologic-native version bump, or fastmcp breaking bump will fail loudly before adoption.
- No blockers for the remaining Phase 7 plans (06, 07, 08).

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

All created files and task commit hashes verified present on disk / in git log.
