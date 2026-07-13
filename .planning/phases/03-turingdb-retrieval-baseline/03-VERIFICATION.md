---
phase: 03-turingdb-retrieval-baseline
verified: 2026-07-13T18:00:00Z
status: passed
score: 18/18 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 3: TuringDB Retrieval Baseline Verification Report

**Phase Goal:** A recorded, versioned retrieval-quality baseline of the current TuringDB stack exists as the yardstick for the migration-correctness gate.
**Verified:** 2026-07-13T18:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 (SC#1) | `scripts/e2e_score.py` and `real_document_benchmark.py` ran against the current TuringDB-backed stack and results captured to a versioned artifact | ✓ VERIFIED | `baseline/03-turingdb/real-document-benchmark.json` (12 docs, all `job.status=succeeded`, `question_count=60`); `baseline/03-turingdb/e2e-results.json` (`check_count=19`, `score=9.474`, `verdict=FAILED_SCORE_GATE`) |
| 2 (SC#2) | Baseline artifact records provider config, corpus, and run parameters — reproducible + directly comparable | ✓ VERIFIED | `baseline/03-turingdb/BASELINE.md` §Provider Configuration (model IDs, dims, endpoints), §Corpus (12 files, sha256 manifest), §Run Parameters (all CLI flags), §Reproduction (verbatim commands) |
| 3 (SC#3) | Baseline committed before any ArcadeDB code touches the stack | ✓ VERIFIED | Commit `07cab0b` (`docs(03): commit TuringDB retrieval baseline artifact (ARC-01)`); `grep -ril "arcadedb" src/` returns zero matches; no commit after `07cab0b` touches ArcadeDB code |
| 4 | `load_frozen_questions` parses a valid frozen-questions file into `questions_by_document` | ✓ VERIFIED | `scripts/real_document_benchmark_scoring.py:152-165`; test `test_load_frozen_questions_round_trips` passes (ran live: 1 passed) |
| 5 | `load_frozen_questions` raises `ValueError` on malformed/empty/wrong-shape input | ✓ VERIFIED | Same function, explicit `raise ValueError(...)` on missing/empty mapping and per-row required-key check; test `test_load_frozen_questions_rejects_malformed` passes |
| 6 | `resolve_questions` returns frozen questions WITHOUT invoking `generate` when frozen is loaded | ✓ VERIFIED | Test `test_resolve_questions_skips_generation_when_frozen` passes (all 3 new tests: `3 passed` confirmed via live pytest run) |
| 7 | `real_document_benchmark.py` accepts `--frozen-questions`; every tracked `*.py` ≤ 600 LOC | ✓ VERIFIED | `scripts/real_document_benchmark.py:99` (`parser.add_argument("--frozen-questions", ...)`); `bash scripts/check-file-size.sh` → "all tracked *.py files within the 600-LOC cap" |
| 8 | `real_document_benchmark.py` ran with real GPU embed+rerank providers on the Italian corpus | ✓ VERIFIED | `real-document-benchmark.json` summary shows real MRR/recall numbers per document; BASELINE.md confirms `agentmemory-embed:8080`/`agentmemory-rerank:8080` (granite embedder, BGE reranker), not stub |
| 9 | `e2e_score.py` ran inside Docker with real providers, produced a full `checks[]` array, not collapsed to 1 check | ✓ VERIFIED | `e2e-results.json`: `check_count=19`, `len(checks)=19`, provider signature `agentmemory-embed:8080`/`agentmemory-rerank:8080` (not `127.0.0.1:<random>` stub) |
| 10 | Live embed/rerank model IDs, dimensions, endpoints captured verbatim (not compose defaults) | ✓ VERIFIED | BASELINE.md §Provider Configuration pins actual values: `granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M` dims=768, `bge-reranker-v2-m3-Q8_0.gguf` — differs from the plan's original Qwen3 assumption, explicitly documented as a mid-phase swap |
| 11 | Baseline run exercised all four D-04 formats (PDF, XLSX, EPUB, webpage/HTML) | ✓ VERIFIED | `real-document-benchmark.json` documents[].suffix set = `{.docx, .epub, .html, .pdf, .pptx, .xlsx}` — all four required formats present plus two extras |
| 12 | `baseline/03-turingdb/` contains all five files: BASELINE.md, e2e-results.json, real-document-benchmark.json, frozen-questions.json, corpus-manifest.json | ✓ VERIFIED | `git ls-files baseline/03-turingdb/` lists exactly these 5 files, all committed |
| 13 | `corpus-manifest.json` contains only manifest fields + sha256 per document, never whole-file bytes (D-06) | ✓ VERIFIED | Inspected all 12 doc entries — keys limited to `{filename, suffix, bytes, sha256, page_count, sheet_count}`; no content/byte-payload field found |
| 14 | `frozen-questions.json` keys questions by filename in the exact schema `load_frozen_questions` consumes | ✓ VERIFIED | Live round-trip: `load_frozen_questions(Path("baseline/03-turingdb/frozen-questions.json"))` returned 12 files with rows containing `{answer, evidence_quote, question, source_id}`, no exception |
| 15 | BASELINE.md records every D-11 metadata field and documents the AS-OBSERVED known-false-passing e2e checks with the inflation caveat (D-07), two phenomena kept separate | ✓ VERIFIED | Read full file: §Provider Configuration, §Corpus, §Frozen Questions, §Run Parameters, §Snapshot Git SHA, §Per-check table (transcribed from e2e-results.json, matches raw JSON exactly), §Known Inflation Caveats explicitly separates phenomenon (a) stub-embedder vs (b) harness `check()` bug, §Reproduction |
| 16 | The whole `baseline/03-turingdb/` tree is force-added (gitignored) and committed before any ArcadeDB code (SC#3, D-09) | ✓ VERIFIED | Commit `07cab0b` contains all 5 files; `.gitignore` line 15 (`e2e-results.json`) confirms force-add was required; no ArcadeDB code exists in `src/` as of HEAD |
| 17 | Turing AgentMemory MCP installed into Claude Code and reachable via the turing-agentmemory skill | ✓ VERIFIED (human-confirmed) | 03-04-SUMMARY.md: `claude mcp get` reports Connected, 26 tools discovered; skill installed at project scope. Per task context, this human-verify item was performed and passed this session — not re-flagged as pending |
| 18 | A human confirms an Italian corpus file ingests and returns tenant-scoped, cited retrieval (D-12) | ✓ VERIFIED (human-confirmed) | 03-04-SUMMARY.md + task context: live `document_search` against `127.0.0.1:8095` returned 5 cited hits (chunks #66/#171/#80/#98/#110) from `apprendimento_automatico_wikipedia`; identical query under a different `user_identifier` returned 0 hits (tenant isolation held). Documented, passed this session per explicit task instruction — not re-flagged as human_needed |

**Score:** 18/18 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `baseline/03-turingdb/real-document-benchmark.json` | D-01 raw benchmark output | ✓ VERIFIED | Valid JSON, 12 docs all `succeeded`, `question_count=60`, per-document MRR/recall present |
| `baseline/03-turingdb/e2e-results.json` | D-02 raw e2e score output | ✓ VERIFIED | Valid JSON, `check_count=19`, `checks[]` len 19, real provider signature |
| `baseline/03-turingdb/corpus-manifest.json` | D-06 manifest-only corpus record | ✓ VERIFIED | 12 docs, `{filename,suffix,bytes,sha256,page_count,sheet_count}` fields only, no bytes payload |
| `baseline/03-turingdb/frozen-questions.json` | D-08 Phase-6 replay contract | ✓ VERIFIED | Round-trips through `load_frozen_questions`, 12 files × 5 questions |
| `baseline/03-turingdb/BASELINE.md` | D-10/D-11 human-readable manifest | ✓ VERIFIED | 307 lines, all required sections present with concrete values |
| `scripts/real_document_benchmark_scoring.py::load_frozen_questions` | D-08 loader function | ✓ VERIFIED | Implemented (not stub), validates schema, raises ValueError on malformed input |
| `scripts/real_document_benchmark_scoring.py::resolve_questions` | D-08 frozen/generate branch | ✓ VERIFIED | Implemented, skips `generate()` when frozen set present |
| `scripts/real_document_benchmark.py` `--frozen-questions` flag | Additive CLI flag | ✓ VERIFIED | Present at line 99, wired into `run()` at line 437 |
| `baseline/03-turingdb/capture-provider-env.txt` | D-11 live provider env capture | ⚠️ ORPHANED (by design) | Present on disk (untracked/uncommitted) — 03-03-SUMMARY documents the deliberate decision to exclude it from the committed 5-file tree because its content is fully transcribed into BASELINE.md. Does not affect goal achievement (not part of the plan's committed-artifact contract). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `scripts/real_document_benchmark.py` | `scripts/real_document_benchmark_scoring.py` | re-export import in both try/except blocks | ✓ WIRED | `load_frozen_questions`/`resolve_questions` imported at lines 35/38 and 50/53 |
| `scripts/real_document_benchmark.py run()` | `resolve_questions` | per-file loop call | ✓ WIRED | Line 481: `resolve_questions, frozen, path.name, generate=generate` inside `asyncio.to_thread` |
| `baseline/03-turingdb/corpus-manifest.json` | `real-document-benchmark.json documents[]` | field-subset extraction, sha256 match | ✓ WIRED | Manifest doc count (12) matches benchmark doc count (12); sha256 values present and correctly formatted (64 hex chars) |
| `baseline/03-turingdb/frozen-questions.json` | `real-document-benchmark.json documents[].questions` | re-key by filename | ✓ WIRED | 12 files × 5 questions = 60 rows, matches `question_count=60` in benchmark summary |
| `baseline/03-turingdb/BASELINE.md` per-check section | `e2e-results.json checks[]` | as-observed transcription | ✓ WIRED | Cross-checked all 19 rows of BASELINE.md's table against raw JSON `ok`/`detail` values — exact match, including the 4 confirmed false-passing checks and 1 genuine failure |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| New frozen-questions loader tests pass | `python -m pytest tests/test_real_document_benchmark.py -k "load_frozen_questions or resolve_questions" -q` | `3 passed, 10 deselected` | ✓ PASS |
| 600-LOC cap holds | `bash scripts/check-file-size.sh` | "all tracked *.py files within the 600-LOC cap" | ✓ PASS |
| Ruff clean | `python -m ruff check scripts tests` | "All checks passed!" | ✓ PASS |
| Frozen-questions.json loads via real loader | `load_frozen_questions(Path("baseline/03-turingdb/frozen-questions.json"))` | 12 files, no exception | ✓ PASS |
| All baseline JSON files valid | `json.loads()` over all 5 files | all parse successfully | ✓ PASS |
| Credential scan on committed baseline files | `grep -riE "PROVIDER_API_KEY|Authorization|sk-|bearer" baseline/03-turingdb/*` | Only match is `PROVIDER_API_KEY=ollama` (a documented, non-secret local placeholder value for the no-auth Ollama endpoint, not a leaked credential) | ✓ PASS |
| No ArcadeDB code present after baseline commit | `grep -ril "arcadedb" src/` | 0 matches | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ARC-01 | 03-01, 03-02, 03-03, 03-04 | Snapshot the current TuringDB retrieval baseline before any backend change | ✓ SATISFIED | REQUIREMENTS.md line 133: `ARC-01 \| Phase 3 \| Complete`; all four plans declare `requirements: [ARC-01]`; committed artifact + all must-haves verified above |

No orphaned requirements — REQUIREMENTS.md maps only ARC-01 to Phase 3, and all four plans claim it.

### Anti-Patterns Found

None. Scanned `scripts/real_document_benchmark_scoring.py`, `scripts/real_document_benchmark.py`, and `baseline/03-turingdb/BASELINE.md` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` — zero matches. `load_frozen_questions`/`resolve_questions` are full implementations, not stubs.

### Human Verification Required

None. The two D-12 human-verify items (03-04, MCP install + hands-on ingest/cited-retrieval/tenant-isolation check) were already performed and passed this session, as documented in `03-04-SUMMARY.md` and confirmed in the verification task context. Per explicit instruction, these are recorded as VERIFIED (human-confirmed) above rather than re-routed to a pending human-verification queue.

### Gaps Summary

No gaps. All 18 must-haves (3 roadmap Success Criteria + 15 plan-level must-haves across 03-01/03-02/03-03/03-04) are verified against the actual codebase and committed artifacts:

- The two baseline-producing scripts (`real_document_benchmark.py`, `e2e_score.py`) were run against the live, GPU-backed TuringDB stack and their raw JSON outputs are committed.
- The committed `baseline/03-turingdb/` tree (5 files, commit `07cab0b`) fully documents provider config, corpus manifest (no whole-file bytes), frozen questions (Phase-6 replay contract), and per-check e2e results with the two D-07 inflation phenomena explicitly kept separate — satisfying the reproducibility/comparability contract.
- The commit landed before any ArcadeDB code exists in the repository, satisfying the ordering constraint.
- The additive `--frozen-questions` / `load_frozen_questions` / `resolve_questions` code (03-01) is a real, tested implementation, not a stub, and is correctly wired into the CLI and re-export chain.
- The one minor deviation (`capture-provider-env.txt` left untracked/uncommitted) is an explicit, documented design decision from 03-03 — its content is fully transcribed into the committed BASELINE.md, so no information is lost and the 5-file committed contract (which is what the plan's acceptance criteria and this phase's roadmap actually require) is intact.

The phase goal — "a recorded, versioned retrieval-quality baseline of the current TuringDB stack exists as the yardstick for the migration-correctness gate" — is achieved.

---

_Verified: 2026-07-13T18:00:00Z_
_Verifier: Claude (gsd-verifier)_
