---
phase: 03-turingdb-retrieval-baseline
plan: 03
subsystem: retrieval-baseline
tags: [baseline, retrieval, arc-01, e2e-score, reranker-swap, artifact-commit]

# Dependency graph
requires:
  - phase: 03-turingdb-retrieval-baseline (plan 02)
    provides: "raw captures: real-document-benchmark.json, e2e-results.json, capture-provider-env.txt (BGE reranker, snapshot SHA ab7abd0)"
provides:
  - "baseline/03-turingdb/corpus-manifest.json (D-06 manifest-only corpus record, no whole-file bytes)"
  - "baseline/03-turingdb/frozen-questions.json (D-08 Phase-6 replay contract, load_frozen_questions-validated)"
  - "baseline/03-turingdb/BASELINE.md (D-10/D-11 human-readable manifest: provider config, run params, git SHA, as-observed per-check e2e table, D-07 inflation caveats, reproduction commands)"
  - "committed baseline/03-turingdb/ tree (5 files, force-added, one atomic commit 07cab0b) — the ARC-01 yardstick landed before any ArcadeDB code (SC#3)"
affects: [phase-6-arc-09-migration-correctness-gate, phase-4-rechunking]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Committed baseline artifact contract: 5-file baseline/{md,json} tree force-added past .gitignore, giving Phase 6 a fixed, diffable, per-check comparison target instead of an aggregate score."

key-files:
  created:
    - baseline/03-turingdb/corpus-manifest.json
    - baseline/03-turingdb/frozen-questions.json
    - baseline/03-turingdb/BASELINE.md
  modified:
    - CHANGELOG.md

key-decisions:
  - "BASELINE.md documents the ACTUAL captured reality, not the plan's original assumptions: BGE reranker (not Qwen3), granite embedder dims=768, actual run params (5 q/file, concurrency 3, local Ollama question-gen), snapshot SHA ab7abd0."
  - "AS-OBSERVED D-07 confirmation superseded RESEARCH.md's [ASSUMED] candidate list: direct inspection of e2e-results.json shows 4 checks (document_ingest_text_writes_chunks, document_search_hybrid_exact_code_match_explains_lexical_score, document_ingest_text_is_idempotent_for_same_payload, document_reindex_text_replaces_old_chunks_and_metadata) report ok=true while their own detail field is literally false — a confirmed harness check()-inflation bug, not a hypothesis. Correcting for this yields a true pass count of 14/19, independently matching D-07's own '~14/19' estimate. The RESEARCH.md vacuous-all() candidates (memory_search_does_not_leak_bob, memory_delete_hides_memory_from_get_and_search) did NOT trigger false-passing in this specific run (their collections were non-empty) and were documented as a structural risk only, not a confirmed false-positive."
  - "capture-provider-env.txt (produced in 03-02) was NOT added to the committed 5-file tree — the plan's <artifacts_produced> and Task 3 acceptance criteria both name exactly 5 files (BASELINE.md, corpus-manifest.json, e2e-results.json, frozen-questions.json, real-document-benchmark.json). All of its content (provider config + git SHA) is fully transcribed into BASELINE.md, so nothing is lost; it remains a local, untracked working file."

requirements-completed: [ARC-01]

coverage:
  - id: D1
    description: "corpus-manifest.json built by field-subset extraction from real-document-benchmark.json (filename/suffix/bytes/sha256/page_count only, no whole-file bytes; xlsx sheet_count documented as a null gap)"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "python -c round-trip check: load_frozen_questions() + corpus-manifest.json non-empty-docs assertion (12 docs, 12 frozen files)"
        status: pass
    human_judgment: false
  - id: D2
    description: "frozen-questions.json round-trips through scripts/real_document_benchmark_scoring.py::load_frozen_questions without raising"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "python -c load_frozen_questions(Path('baseline/03-turingdb/frozen-questions.json')) — returned 12 files, no exception"
        status: pass
    human_judgment: false
  - id: D3
    description: "BASELINE.md pins every D-11 field as concrete actual values (provider model IDs/dims/endpoints, run params, git SHA ab7abd0) and documents the as-observed per-check e2e table with both D-07 inflation phenomena kept separate"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "python -c word-presence assertion over BASELINE.md (Provider/Corpus/Frozen/Run param/git/per-check/Reproduction/chunk) — all present"
        status: pass
    human_judgment: true
    rationale: "The correctness of the D-07 as-observed inflation analysis (which checks are confirmed false-passing vs. structural-risk-only) is a substantive judgment call transcribed from raw JSON; a human should confirm the interpretation before Phase 6 relies on it as the diffing contract."
  - id: D4
    description: "Full baseline/03-turingdb/ tree (5 curated files) force-added past .gitignore and committed in one atomic commit before any ArcadeDB code, with a clean secret/whole-file scrub and CHANGELOG.md updated"
    requirement: "ARC-01"
    verification:
      - kind: unit
        ref: "git ls-files baseline/03-turingdb/ | sort -> exactly BASELINE.md, corpus-manifest.json, e2e-results.json, frozen-questions.json, real-document-benchmark.json; all *.json json.loads-valid; commit 07cab0b"
        status: pass
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-07-13
status: complete
---

# Phase 3 Plan 3: Committed TuringDB Retrieval Baseline Summary

**Assembled and committed the ARC-01 baseline artifact (`baseline/03-turingdb/`) reflecting the ACTUAL BGE-reranker capture from 03-02 — not the plan's original assumptions — including an AS-OBSERVED confirmation that 4 e2e checks report `ok=true` while their own assertion evaluated `false`, independently matching D-07's "~14/19" true-pass estimate.**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-07-13T15:17:05Z
- **Tasks:** 3 (single atomic commit per the plan's own design, not per-task)
- **Files modified:** 6 (5 new baseline artifact files + CHANGELOG.md)

## Accomplishments
- `corpus-manifest.json`: field-subset extraction (12 docs, no whole-file bytes; xlsx sheet_count documented as a `null` gap).
- `frozen-questions.json`: 12 files x 5 questions, re-keyed by filename, validated against `load_frozen_questions` (Phase 6 replay contract).
- `BASELINE.md`: every D-11 field pinned as a concrete actual value — granite embedder (dims 768), BGE reranker (not the plan's Qwen3), the real run params (5 q/file, concurrency 3, local Ollama question-gen, `--root D:/tmp/baseline-corpus`), snapshot SHA `ab7abd0`, an as-observed 19-row per-check e2e table, both D-07 inflation phenomena documented separately with a NEW confirmed finding (4 checks with `ok=true`/`detail=false`), the document-scoped-search `document_id` bug caveat, and a runnable Reproduction section with both actual commands.
- One atomic commit (`07cab0b`) force-adding exactly the 5 curated files past `.gitignore`, landing before any ArcadeDB-touching code (SC#3).
- `CHANGELOG.md` updated to record the new committed baseline contract.

## Task Commits

Per the plan's own design (Task 3's acceptance criteria explicitly requires "One atomic commit"), Tasks 1 and 2 built files without intermediate commits; Task 3 is the single commit point covering all three tasks' output plus the two raw captures from 03-02:

1. **Tasks 1+2+3 combined: assemble corpus-manifest.json + frozen-questions.json + BASELINE.md, force-add all 5 files, update CHANGELOG.md** - `07cab0b` (docs)

## Files Created/Modified
- `baseline/03-turingdb/corpus-manifest.json` - D-06 manifest-only corpus record (filename/suffix/bytes/sha256/page_count; xlsx sheet_count null)
- `baseline/03-turingdb/frozen-questions.json` - D-08 questions_by_document, Phase-6 replay contract
- `baseline/03-turingdb/BASELINE.md` - D-10/D-11 human-readable manifest with as-observed e2e caveats
- `baseline/03-turingdb/e2e-results.json` - raw D-02 capture (from 03-02, committed here)
- `baseline/03-turingdb/real-document-benchmark.json` - raw D-01 capture (from 03-02, committed here)
- `CHANGELOG.md` - added the new committed-baseline entry under Unreleased/Added

## Decisions Made
- Documented the ACTUAL capture reality (BGE reranker, granite embedder, real run params, SHA `ab7abd0`) rather than the plan's original assumed config, per the CRITICAL context supplied for this run.
- Confirmed the D-07 false-passing check set AS OBSERVED from the raw JSON rather than trusting RESEARCH.md's [ASSUMED] candidate list blindly: 4 checks (`document_ingest_text_writes_chunks`, `document_search_hybrid_exact_code_match_explains_lexical_score`, `document_ingest_text_is_idempotent_for_same_payload`, `document_reindex_text_replaces_old_chunks_and_metadata`) show `ok=true` with `detail=false` — a genuine harness bug, independently confirming D-07's "~14/19" estimate. The two vacuous-`all()` candidates from RESEARCH.md did not trigger in this run and are documented as a structural risk only, kept separate from the confirmed false-passing set.
- Excluded `capture-provider-env.txt` from the committed 5-file tree (plan names exactly 5 artifacts); its content is fully transcribed into BASELINE.md so no information is lost.

## Deviations from Plan

### Auto-fixed Issues

None — no Rule 1/2/3 auto-fixes were needed; this was a pure assembly/documentation plan and its own acceptance criteria were followed as designed.

### Content deviations (directed by the CRITICAL context, not a deviation rule)

**1. BASELINE.md documents the ACTUAL captured stack, not the plan's originally assumed config**
- **Found during:** Task 2 (authoring BASELINE.md)
- **Issue:** The plan text (written before 03-02 ran) implicitly assumed the originally planned provider config and run params. The actual 03-02 capture deviated heavily (reranker swap to BGE, local Ollama for question-gen, reduced question count/concurrency, curated 12-file corpus with a fetched HTML snapshot).
- **Fix:** BASELINE.md was authored entirely from 03-02-SUMMARY.md and the raw captures as ground truth — every D-11 field reflects the actual run, not the plan's assumptions.
- **Files modified:** baseline/03-turingdb/BASELINE.md
- **Verification:** Automated word-presence check passed; cross-checked every field against capture-provider-env.txt and real-document-benchmark.json.
- **Committed in:** 07cab0b

---

**Total deviations:** 0 auto-fixed (Rules 1-4); 1 content-fidelity correction directed explicitly by the task's CRITICAL context block.
**Impact on plan:** None on scope — the plan's own acceptance criteria (D-11 fields as concrete actual values) required this; the plan text's illustrative examples were superseded by ground truth without altering the plan's structure or file list.

## Issues Encountered
- The raw `e2e-results.json`'s `check()` semantics (`ok = bool(detail)`) do not hold for 4 of the 19 checks in this specific captured run — resolved by transcribing this AS a documented finding (not a bug to fix; Phase 4+ owns re-baselining the CI threshold per D-07/RESEARCH.md scope boundary) rather than treating it as a blocking issue for this plan.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 6 (ARC-09) has a complete, committed, per-check-diffable baseline (`baseline/03-turingdb/`) to compare the ArcadeDB port against, including the frozen questions needed for a like-for-like replay.
- Phase 4 (re-chunking, ARC-04/ARC-05) must diff BASELINE.md's per-check table PER-CHECK, not just the aggregate score, since 2 of the confirmed false-passing checks hardcode chunk_count values that may legitimately change.
- The document-scoped search `document_id` bug (deflates full-corpus MRR/recall) and the O(all-chunks) full-scan cost are both tracked in `.planning/research/FUTURE-MILESTONE-retrieval-memory-quality.md` and are expected to be addressed by the ArcadeDB port's native indexed search.
- No blockers for proceeding to the next phase.

---
*Phase: 03-turingdb-retrieval-baseline*
*Completed: 2026-07-13*

## Self-Check: PASSED
- All 5 baseline artifact files found on disk under `baseline/03-turingdb/`.
- This SUMMARY.md found on disk.
- Both commits (`07cab0b` baseline artifact, `07cb4a7` summary) found in git log.
