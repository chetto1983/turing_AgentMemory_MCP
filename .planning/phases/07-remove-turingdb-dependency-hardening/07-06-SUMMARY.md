---
phase: 07-remove-turingdb-dependency-hardening
plan: 06
subsystem: docs
tags: [docs, arcadedb, lab, frontend, changelog, bertoni-rename]

# Dependency graph
requires:
  - phase: 07-01
    provides: legacy TuringDB harness/CLI deletion (benchmark cluster, admin_repair.py's repair-vector-index)
  - phase: 07-02
    provides: src-side turingdb import removal (e2e_score.py/e2e_score_stubs.py)
  - phase: 07-03
    provides: Bertoni app-state rename (BERTONI_HOME, bertoni-data volume, AGENTMEMORY_GRAPH)
provides:
  - "TuringDB-free user-facing docs (README, six operational docs, HACKER_NEWS.md, skill docs)"
  - "CHANGELOG.md Removed entry documenting the full TuringDB cut + Bertoni app-state rename"
  - "Lab dashboard no longer requires turingdb_version; architecture diagram shows ArcadeDB node"
  - "Frontend example query and architecture panel label read ArcadeDB"
affects: [07-07, 07-08]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - README.md
    - CHANGELOG.md
    - docs/configuration.md
    - docs/deployment.md
    - docs/operations.md
    - docs/security.md
    - docs/performance.md
    - docs/limitations.md
    - docs/publication/HACKER_NEWS.md
    - skills/turing-agentmemory/SKILL.md
    - skills/turing-agentmemory/references/architecture.md
    - skills/turing-agentmemory/references/operations.md
    - src/turing_agentmemory_mcp/lab.py
    - tests/test_lab.py
    - src/turing_agentmemory_mcp/frontend/app.js
    - src/turing_agentmemory_mcp/frontend/index.html
    - tests/test_docker_hardening.py

key-decisions:
  - "Dropped turingdb_version from lab.py's REQUIRED_BENCHMARK_FIELDS entirely rather than renaming to backend_version -- the benchmark.py harness cluster that produced it was deleted in 07-01, so no live producer needs the field, and inventing a new required field with no producer would just create a different always-false gate."
  - "Rewrote README/operations.md sections that referenced already-deleted 07-01 functionality (repair-vector-index CLI, agent_quality_eval.py) as fix-on-touch bugs while sweeping those exact TuringDB-text lines -- pointed operators at memory_rebuild_vector_projection (live MCP tool) and real_document_benchmark.py (live ArcadeDB-era script) instead of leaving instructions for deleted commands."
  - "Backup/operations docs now explicitly call out both bertoni-data (MCP app-state) and arcadedb-data (canonical graph/vector) as volumes needing backup coverage, since the prior TuringDB-era instructions only covered the single shared /turing volume and silently omitted the now-separate canonical data store."

patterns-established: []

requirements-completed: []  # ARC-10 intentionally NOT marked complete here -- closes at phase end (07-08) per plan success_criteria.

coverage:
  - id: D1
    description: "User-facing docs (README, six operational docs, HACKER_NEWS.md, skill docs) describe ArcadeDB as the sole backend with Bertoni-rooted app-state paths -- zero TuringDB-backend references remain"
    verification:
      - kind: other
        ref: "grep -rilE 'turingdb' README.md docs/configuration.md docs/deployment.md docs/operations.md docs/security.md docs/performance.md docs/limitations.md docs/publication/HACKER_NEWS.md skills/turing-agentmemory/ | grep -v docs/architecture.md | wc -l -> 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "CHANGELOG.md Removed entry records the TuringDB dependency/service removal and the /turing to /bertoni app-state rename"
    verification:
      - kind: other
        ref: "grep -niE 'Removed' CHANGELOG.md shows entry mentioning TuringDB and /bertoni"
        status: pass
    human_judgment: false
  - id: D3
    description: "lab.py no longer requires a turingdb_version benchmark field; architecture diagram shows an ArcadeDB store node; tests/test_lab.py fixture matches"
    verification:
      - kind: unit
        ref: "tests/test_lab.py -q"
        status: pass
    human_judgment: false
  - id: D4
    description: "Frontend example query and architecture label read ArcadeDB (SQL MATCH object-notation, not Cypher/TuringDB)"
    verification:
      - kind: other
        ref: "grep -riE 'turingdb' src/turing_agentmemory_mcp/frontend/ -> 0; grep -niE 'arcadedb' src/turing_agentmemory_mcp/frontend/index.html -> >0"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-16
status: complete
---

# Phase 7 Plan 06: Docs + Lab/Frontend TuringDB Sweep Summary

**Swept every TuringDB-backend reference in user-facing docs and the Lab/frontend UI to ArcadeDB, and fixed two adjacent stale-instruction bugs (deleted repair-vector-index CLI, deleted agent_quality_eval.py) discovered while touching those exact lines.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3
- **Files modified:** 17 (16 planned + 1 required-coupling test file)

## Accomplishments

- README.md, the six operational docs (configuration/deployment/operations/security/performance/limitations), `docs/publication/HACKER_NEWS.md`, and the three `skills/turing-agentmemory/` files now describe ArcadeDB as the canonical backend, native `LSM_VECTOR` HNSW + Lucene retrieval, and `/bertoni`-rooted app-state paths (`BERTONI_HOME`, `bertoni-data` volume, `AGENTMEMORY_GRAPH`) -- zero `turingdb` (any case) references remain in the swept set.
- `docs/architecture.md` verified already clean and left untouched; `docs/superpowers/` historical records untouched.
- `CHANGELOG.md` gained a `Removed` entry under `## Unreleased` documenting the full `turingdb==1.35` dependency cut, the legacy harness cluster deletion, `repair-vector-index`/`admin_repair.py` removal, the `sys.modules["turingdb"]` test stub removal, and the app-state rename (`TURINGDB_HOME`->`BERTONI_HOME`, `turing-data`->`bertoni-data`, `TURINGDB_GRAPH`->`AGENTMEMORY_GRAPH`, `TURINGDB_EMBED_DIMENSIONS`->`EMBED_DIMENSIONS`, dead `TURINGDB_URL`/`TURINGDB_*_INDEX` deletion).
- `lab.py`'s `REQUIRED_BENCHMARK_FIELDS` no longer requires `turingdb_version` (dropped, not renamed -- its only producer, `benchmark.py`, was deleted in 07-01); the architecture-diagram store node/edge renamed `turingdb`/`TuringDB` -> `arcadedb`/`ArcadeDB`. `tests/test_lab.py`'s fixture updated to match; both `test_lab.py` tests pass.
- `frontend/app.js`'s stale Cypher-shaped `(m:Memory)-[r]->(store:TuringDB)` example query preset replaced with an ArcadeDB SQL `MATCH {type:...,as:...}.out('EDGE'){as:...}` object-notation example (Phase 4 D-05 form), labeled ArcadeDB. `frontend/index.html`'s static `<span>TuringDB</span>` architecture-panel label replaced with `ArcadeDB`.
- Fixed-on-touch: README's "Vector Index Repair"/"Backup And Restore" sections and `docs/operations.md`'s "Vector Recovery"/"Backup" sections referenced the `repair-vector-index` CLI command and `docker compose ... turingdb` service invocations that no longer exist (both deleted by earlier Phase-7 plans) -- rewrote them to point at the live `memory_rebuild_vector_projection` MCP tool and the current `arcadedb`/`turing-agentmemory-mcp` Compose services, and to cover both the `bertoni-data` (app-state) and `arcadedb-data` (canonical) volumes for backup completeness.
- Fixed-on-touch: README's "Run Locally"/"Score Gate" sections referenced the deleted `scripts/agent_quality_eval.py` harness and `TuringDB daemon starts` check wording -- rewrote to describe the live `scripts/e2e_score.py` (ArcadeDB `ArcadeE2EBackend`) and `scripts/real_document_benchmark.py`.
- Required coupling: updated `tests/test_docker_hardening.py::test_readme_documents_backup_restore_and_build_attestation`'s literal string assertions from `turing-data:/turing` to `bertoni-data:/bertoni` to stay in lockstep with the README rewrite (file not in this plan's `files_modified` frontmatter but directly mirrors the section edited in Task 1).

## Task Commits

Each task was committed atomically:

1. **Task 1: Sweep user-facing docs + add CHANGELOG removal entry** - `b913754` (docs)
2. **Task 2: Fix Lab dashboard required-field + architecture diagram** - `23615bd` (fix)
3. **Task 3: Fix frontend UI labels + example query** - `0e8ba25` (fix)

**Required coupling (README/test_docker_hardening.py lockstep):** `6d21c7b` (test)

## Files Created/Modified

- `README.md` - ArcadeDB-backed framing; rewrote Backup/Restore, Vector Projection Repair, Build Attestation, Run Locally, Score Gate, Industrial Practice Notes sections
- `CHANGELOG.md` - Added `Removed` entry for the TuringDB cut + Bertoni rename
- `docs/configuration.md` - `BERTONI_HOME`/`AGENTMEMORY_GRAPH` replace the "legacy names" paragraph; `/bertoni/data/...` path renames
- `docs/deployment.md` - ArcadeDB prerequisites, `bertoni-data`/`arcadedb-data` volume mentions, upgrade/rollback wording
- `docs/operations.md` - Backup/Restore/Vector Recovery sections rewritten for ArcadeDB + Bertoni volumes; audit/span path renames
- `docs/security.md` - "only MCP reaches ArcadeDB" network-policy wording
- `docs/performance.md` - "stack used ArcadeDB locally" method note
- `docs/limitations.md` - "blocking provider or ArcadeDB call" wording
- `docs/publication/HACKER_NEWS.md` - ArcadeDB fact-sheet wording (2 spots)
- `skills/turing-agentmemory/SKILL.md` - "canonical records in ArcadeDB"
- `skills/turing-agentmemory/references/architecture.md` - "ArcadeDB stores the canonical tenant-scoped graph"
- `skills/turing-agentmemory/references/operations.md` - "MCP and ArcadeDB container state"
- `src/turing_agentmemory_mcp/lab.py` - Dropped `turingdb_version` from `REQUIRED_BENCHMARK_FIELDS`; renamed diagram node/edge to arcadedb/ArcadeDB
- `tests/test_lab.py` - Removed `turingdb_version` from the fixture row
- `src/turing_agentmemory_mcp/frontend/app.js` - ArcadeDB object-notation example query preset
- `src/turing_agentmemory_mcp/frontend/index.html` - ArcadeDB architecture-panel label
- `tests/test_docker_hardening.py` - Updated backup-command string assertions to `bertoni-data:/bertoni`

## Decisions Made

- Dropped `turingdb_version` from `REQUIRED_BENCHMARK_FIELDS` entirely (not renamed to `backend_version`) -- no live benchmark producer needs it after 07-01's harness deletion.
- Rewrote the dead `repair-vector-index`/`agent_quality_eval.py` doc references discovered while sweeping the exact TuringDB-text lines they were on, pointing operators at the live `memory_rebuild_vector_projection` tool and `real_document_benchmark.py` script instead of leaving broken CLI instructions.
- Backup docs now name both `bertoni-data` (app-state) and `arcadedb-data` (canonical) volumes, since the prior single-volume TuringDB-era instructions silently omitted the canonical data store once ArcadeDB became a separate Compose service/volume.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] README/docs referenced deleted `repair-vector-index` CLI command and `agent_quality_eval.py` script**
- **Found during:** Task 1 (docs sweep)
- **Issue:** `repair-vector-index` (admin_repair.py) and `agent_quality_eval.py` were deleted in 07-01, but README.md's "Vector Index Repair"/"Run Locally"/"Score Gate" sections and `docs/operations.md`'s "Vector Recovery" section still instructed operators to run them -- broken, misleading instructions on the exact lines being swept for TuringDB text.
- **Fix:** Rewrote to reference the live `memory_rebuild_vector_projection` MCP tool and `scripts/real_document_benchmark.py`.
- **Files modified:** `README.md`, `docs/operations.md`
- **Verification:** Manual review; no automated test covers doc prose accuracy beyond the grep/CHANGELOG assertions already required by the plan.
- **Committed in:** `b913754` (Task 1 commit)

**2. [Rule 3 - Blocking] `tests/test_docker_hardening.py` positive-assertion test would fail after the README Backup And Restore rewrite**
- **Found during:** Task 1 (docs sweep), flagged explicitly by the orchestrator's required-coupling note
- **Issue:** `test_readme_documents_backup_restore_and_build_attestation` asserted the literal old `turing-data:/turing` strings, which no longer exist in README.md after the rename.
- **Fix:** Updated the two literal-string assertions to `bertoni-data:/bertoni`.
- **Files modified:** `tests/test_docker_hardening.py`
- **Verification:** `python -m pytest tests/test_docker_hardening.py tests/test_lab.py -q` -> 17 passed
- **Committed in:** `6d21c7b`

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes were directly on the lines already being edited for this plan's stated scope (TuringDB sweep + the explicitly flagged README/test coupling); no unrelated scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Docs, Lab, and frontend are now TuringDB-free and describe the ArcadeDB + Bertoni reality; ready for 07-07/07-08's remaining CLAUDE.md invariant rewrite and cut-proof verification.
- Full unit suite (856 passed, 1 skipped, 10 deselected), ruff format-check, ruff check, `check-file-size.sh`, and `docker compose config --quiet` all green after this plan.
- ARC-10 intentionally left `Pending` in REQUIREMENTS.md per this plan's explicit success criteria -- it closes at phase end (07-08).

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

All 17 modified/created files verified present on disk; all 4 task/coupling commits (`b913754`, `23615bd`, `0e8ba25`, `6d21c7b`) verified present in git log.
