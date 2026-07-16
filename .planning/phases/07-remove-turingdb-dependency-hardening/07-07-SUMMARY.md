---
phase: 07-remove-turingdb-dependency-hardening
plan: 07
subsystem: docs
tags: [claude-md, invariants, governance, arcadedb, mvcc, tenant-binding]

# Dependency graph
requires:
  - phase: 07-remove-turingdb-dependency-hardening (07-01, 07-02, 07-03)
    provides: legacy TuringDB harness removal, e2e_score TuringDB-import cleanup, BERTONI_HOME/AGENTMEMORY_GRAPH env renames
provides:
  - CLAUDE.md Invariants section rewritten for the ArcadeDB-sole reality (11 invariants, renumbered)
  - CLAUDE.md Notes section BERTONI_HOME reconciliation
  - .claude/CLAUDE.md Constraints/milestone-framing reconciled to completed-fact tense
affects: [07-08 (human review gate consumes this rewrite)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Invariant text traced to a RESEARCH.md substrate table (Phase 4/5 CONTEXT.md + STATE.md citations), not re-derived from memory"

key-files:
  created: []
  modified:
    - CLAUDE.md
    - .claude/CLAUDE.md

key-decisions:
  - "Invariant #6 (old): 'sort vector results...composed VECTOR SEARCH...MATCH...rows do not preserve vector order' retired outright, not reworded -- live code (store_search.py:222) sorts the final blended RRF score for output ordering, not because vectorNeighbors fails to preserve order; native HNSW returns record+score together per 04-CONTEXT.md D-03/SC#3."
  - "SparseIndex (sparse_index.py) explicitly NOT claimed as deleted in the new invariant #7 -- it survives as a fusion_enabled-gated channel with a .status() signal; only the write-side outbox-as-second-source-of-truth is retired, per store_evidence.py:116-119 live evidence."
  - "Corrected a pre-existing wrong cross-reference in .claude/CLAUDE.md (said stable IDs = 'invariant #3'; CLAUDE.md's actual numbering has always had stable IDs at #4) while reconciling the same paragraph -- fix-on-touch, not scope creep."
  - "ARC-10 intentionally left Pending in REQUIREMENTS.md per this plan's explicit instruction -- it closes at phase end (07-08), not here."

requirements-completed: []

coverage:
  - id: D1
    description: "CLAUDE.md invariant #2 states ArcadeDB is the sole canonical backend, superseding (not merely editing) the TuringDB-canonical claim"
    requirement: "ARC-10"
    verification:
      - kind: other
        ref: "grep -qiE 'ArcadeDB.*(sole|canonical)|(sole|canonical).*ArcadeDB' CLAUDE.md"
        status: pass
    human_judgment: false
  - id: D2
    description: "New invariants codified: MVCC 503 ConcurrentModificationException handled via run_in_transaction redo, native LSM_VECTOR+Lucene ACID-consistent with graph writes (SparseIndex not deleted), one-DB-per-tenant + TenantBinding + mandatory user_identifier predicate"
    requirement: "ARC-10"
    verification:
      - kind: other
        ref: "grep -qiE 'ConcurrentModificationException|503' CLAUDE.md && grep -qiE 'TenantBinding' CLAUDE.md"
        status: pass
    human_judgment: false
  - id: D3
    description: "Tenant-scope (#1) and stable-ID (#4) invariants reconfirmed, not weakened or dropped"
    requirement: "ARC-10"
    verification:
      - kind: other
        ref: "grep -i 'user_identifier' CLAUDE.md (fail-closed tenant-scope invariant present)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Stale 'TURINGDB_HOME remains its transitional env name' note replaced by BERTONI_HOME reality in both files"
    requirement: "ARC-10"
    verification:
      - kind: other
        ref: "grep -qi 'TURINGDB_HOME remains' CLAUDE.md .claude/CLAUDE.md returns 0 in both"
        status: pass
    human_judgment: false
  - id: D5
    description: ".claude/CLAUDE.md milestone framing reflects completed ArcadeDB migration (no 'migrates to ArcadeDB this milestone' pending language, no 'invariant #2 TuringDB canonical' live claim)"
    requirement: "ARC-10"
    verification:
      - kind: other
        ref: "grep -i 'migrates to ArcadeDB' .claude/CLAUDE.md returns 0; grep -iE 'ArcadeDB.*(sole|canonical|backend)' .claude/CLAUDE.md returns >0"
        status: pass
    human_judgment: false
  - id: D6
    description: "No fabricated behavior claims introduced -- vector-ordering invariant cross-checked against live store_search.py before retiring"
    requirement: "ARC-10"
    verification: []
    human_judgment: true
    rationale: "Requires a human/reviewer read of the retired invariant's rationale against the plan's own threat register (T-07-10); this SUMMARY documents the cross-check performed (store_search.py:222 read live) but the correctness judgment itself is the Plan 08 human review gate this plan was built to feed."

# Metrics
duration: ~15min
completed: 2026-07-16
status: complete
---

# Phase 7 Plan 7: Rewrite CLAUDE.md invariants for ArcadeDB-sole reality Summary

**Rewrote both CLAUDE.md and .claude/CLAUDE.md's invariant/constraint prose to state ArcadeDB as the sole canonical backend as completed fact, codifying MVCC-503 handling, native ACID vector+full-text, and TenantBinding while reconfirming tenant-scope and stable-ID invariants verbatim.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-16T20:20:19Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- CLAUDE.md's 9-invariant list rewritten to 11 invariants: superseded the TuringDB-canonical claim (#2), merged the physical-isolation invariant with TenantBinding.verify()'s derive_tenant_database_identity + hmac.compare_digest mechanics (#3), replaced the per-batch submit-before-match rationale with run_in_transaction's single managed begin/commit (#5), added a new MVCC-conflict invariant (HTTP 503 ConcurrentModificationException → redo whole cycle, never blind-retry) (#6), added a new native-ACID vector+full-text invariant that explicitly preserves SparseIndex as a live fusion-gated channel rather than claiming it was deleted (#7), and replaced the stale composed-VECTOR-SEARCH re-sort claim with the reconnect()/`/health` reachability-probe reality (#8)
- CLAUDE.md Notes section's "TURINGDB_HOME remains its transitional env name" replaced with the live BERTONI_HOME reality (default `/bertoni`, read at 3 independent call sites)
- .claude/CLAUDE.md's milestone framing flipped from pending ("migrates to ArcadeDB this milestone", "invariant #2 ... is superseded") to completed fact; the Constraints tech-stack line and Key-Dependencies line that still named `turingdb 1.35` as the primary database now name ArcadeDB
- Fixed a pre-existing wrong invariant cross-reference in .claude/CLAUDE.md (stable IDs mislabeled "invariant #3"; corrected to #4, CLAUDE.md's actual numbering)

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite the CLAUDE.md Invariants section + Notes** - `6c915cf` (docs)
2. **Task 2: Reconcile .claude/CLAUDE.md Constraints, Durability, and milestone framing** - `fe49845` (docs)

_Note: docs-only plan; no test/feat/refactor commits._

## Files Created/Modified
- `CLAUDE.md` - Invariants section rewritten (9→11 invariants, ArcadeDB-sole framing); Notes section BERTONI_HOME reconciliation
- `.claude/CLAUDE.md` - "What This Is" milestone framing, Constraints block (tech-stack/architecture/tenant-isolation lines), Key Dependencies turingdb line reconciled to ArcadeDB-sole completed-fact prose

## Decisions Made
- Retired the old invariant #6 (app-layer vector re-sort) outright rather than rewording it into a weaker claim, after confirming live in `store_search.py:222` that the existing `sorted(seeds, ...)` call sorts the final blended RRF score for presentation, not because ArcadeDB's `vectorNeighbors` fails to return record+score together (it does, per 04-CONTEXT.md D-03/SC#3 — the `vector_id` int-join was deleted, not ported). Fabricating a weaker version of the old claim would have violated the plan's explicit prohibition against asserting a vector-ordering behavior the code doesn't exhibit.
- New invariant #7's wording explicitly says `SparseIndex` "is not deleted; it survives as a `fusion_enabled`-gated memory-search channel with a `.status()` health signal only" — the RESEARCH substrate flagged this as a caveat other phrasings could get wrong (claiming the whole class was removed), so it was written defensively.
- Left `.claude/CLAUDE.md`'s Platform Requirements / Entry Points / Architectural-Constraints tables (e.g. the stale `repair-vector-index` CLI entry, the "TuringDB client is blocking" threading note) untouched — out of this plan's explicit scope boundary ("do NOT attempt a full rewrite of the large auto-generated tech-stack/architecture tables ... that is the deferred full-rebrand phase," i.e. Phase 14). These remain known stale prose for that later phase, not silently missed here.

## Deviations from Plan

None - plan executed as written. The one fix-on-touch item (correcting the wrong `invariant #3` stable-ID cross-reference in `.claude/CLAUDE.md` to `#4`) was inside the same Constraints paragraph task 2 was already editing, not a separate out-of-scope excursion.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
Both governance docs now describe the ArcadeDB-sole reality with the new invariants codified and no fabricated behavior claims — ready for Plan 08's human review gate. ARC-10 remains intentionally Pending in REQUIREMENTS.md per this plan's explicit instruction; it closes at phase end in 07-08, not here.

---
*Phase: 07-remove-turingdb-dependency-hardening*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: CLAUDE.md
- FOUND: .claude/CLAUDE.md
- FOUND: .planning/phases/07-remove-turingdb-dependency-hardening/07-07-SUMMARY.md
- FOUND commit: 6c915cf
- FOUND commit: fe49845
