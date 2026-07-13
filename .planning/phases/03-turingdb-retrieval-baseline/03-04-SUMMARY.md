---
phase: 03-turingdb-retrieval-baseline
plan: 04
subsystem: retrieval-baseline
tags: [baseline, arc-01, d-12, mcp-install, hands-on-validation, tenant-isolation, cited-retrieval]

# Dependency graph
requires:
  - phase: 03-turingdb-retrieval-baseline (plan 02)
    provides: "12 Italian multi-format docs ingested under scope real-documents-direct-mcp-20260713T144535Z on the live TuringDB stack"
  - phase: 03-turingdb-retrieval-baseline (plan 03)
    provides: "committed baseline/03-turingdb/ artifact (the committed numeric baseline this session confidence-checks)"
provides:
  - "Human-confirmed D-12 supplemental validation: MCP installed in Claude Code (server + skill) and one live Italian ingest/cited-retrieval round-trip + cross-tenant isolation sanity check PASSED against the current TuringDB stack"
  - "No committed data artifact (D-12 is supplemental by design) — confidence signal only"
affects: [phase-4-arcadedb-direct-port, phase-6-arc-09-migration-correctness-gate]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - .planning/phases/03-turingdb-retrieval-baseline/03-04-SUMMARY.md
  modified: []   # no repo source touched (files_modified: []); client-side wiring only (untracked): MCP server registration in ~/.claude.json + .claude/skills/turing-agentmemory junction (gitignored)

key-decisions:
  - "Round-trip driven programmatically against the live MCP endpoint (127.0.0.1:8095, real MCP protocol) per user direction ('demo it now via live endpoint') rather than typed by hand in the client — same server code path, same evidence. D-12 is supplemental, so this satisfies the confidence gate."
  - "Queried the short-ID Italian ML Wikipedia doc (apprendimento_automatico_wikipedia) — deliberately avoided the 5 normattiva_* PDFs whose long document_ids trip the scoped-search bug recorded in 03-02-SUMMARY."

patterns-established: []

requirements-completed: [ARC-01]

coverage:
  - id: D1
    description: "D-12 hands-on validation: MCP installed into Claude Code (server registered + skill installed) and one live Italian ingest/cited-retrieval round-trip + cross-tenant isolation sanity check on the current TuringDB stack"
    requirement: "ARC-01"
    verification:
      - kind: manual_procedural
        ref: "live MCP round-trip via http://127.0.0.1:8095/mcp/ — document_search('Che cos'è l'apprendimento automatico?', scope=real-documents-direct-mcp-20260713T144535Z) returned 5 CITED hits from apprendimento_automatico_wikipedia (chunks #66/#171/#80/#98/#110); same query under a DIFFERENT user_identifier returned 0 (no leakage)"
        status: pass
    human_judgment: true
    rationale: "D-12 is a supplemental hands-on confidence gate driven/confirmed by the operator; it is deliberately NOT the committed numeric baseline (that is 03-02/03-03)."

# Metrics
duration: ~25min
completed: 2026-07-13
status: complete
---

# Phase 3 · Plan 04: D-12 Supplemental Hands-On Validation Summary

**MCP installed into Claude Code (HTTP server + project skill) and D-12 validation passed on the live TuringDB stack: Italian document_search returned relevant CITED chunks scoped to the tenant, and the same query under a different `user_identifier` returned nothing — tenant isolation (invariant #1) holds.**

## Performance

- **Duration:** ~25 min (interactive)
- **Completed:** 2026-07-13
- **Tasks:** 2 (Task 1 auto; Task 2 checkpoint:human-verify, blocking)
- **Files modified:** 0 repo source (validation-only; client-side wiring is untracked/gitignored)

## Accomplishments

- **Task 1 — MCP installed in Claude Code.** Registered the running Dockerized MCP over HTTP
  (`claude mcp add --transport http turing-agentmemory http://127.0.0.1:8095/mcp/`, local scope) —
  `claude mcp get` reports `✔ Connected`; **26 tools discovered** (memory_* / document_*). The
  `turing-agentmemory` **skill** was also installed at project scope via a gitignored junction
  `.claude/skills/turing-agentmemory → skills/turing-agentmemory` (canonical copy, no duplication).
- **Task 2 — Hands-on cited retrieval, PASSED.** Against the already-ingested Italian corpus
  (12 docs, all `succeeded`, scope `real-documents-direct-mcp-20260713T144535Z`):
  - `document_search("Che cos'è l'apprendimento automatico?", limit=5)` → **5 relevant, CITED hits**,
    every hit from `apprendimento_automatico_wikipedia-bd63980ed35b` with chunk locators
    (`chunk=66`, `#171`, `#80`, `#98`, `#110`) and scores; snippets are genuine on-topic Italian ML text.
- **Tenant isolation confirmed.** The identical query under `user_identifier=tenant-isolation-probe-DIFFERENT`
  returned **0 hits** — no cross-tenant leakage (invariant #1).
- **Stack health confirmed.** `/health` = `{"status":"ok"}` with all runtime stages ready
  (granite-embedding-311m-multilingual 768d, bge-reranker-v2-m3, gliner, turingdb, weighted-RRF fusion).

## Task Commits

Validation-only plan — Task 1 (client-side MCP registration) and Task 2 (human-verify round-trip)
produce **no repo source commits** (`files_modified: []`). Only this SUMMARY is committed as plan metadata.

## Files Created/Modified

- `.planning/phases/03-turingdb-retrieval-baseline/03-04-SUMMARY.md` — this record.
- (untracked, client-side) MCP server entry in `~/.claude.json`; `.claude/skills/turing-agentmemory`
  junction — both intentionally outside the repo / gitignored.

## Decisions Made

- Drove the round-trip programmatically against the live MCP endpoint (real MCP protocol via
  `fastmcp.Client`) at the operator's direction — the server was registered mid-session so its
  in-session tool wrappers weren't loaded yet (they surfaced natively later). Same server code path,
  same evidence; acceptable because D-12 is supplemental.
- Used the short-ID ML Wikipedia doc and avoided the `normattiva_*` PDFs (long-`document_id`
  scoped-search bug from 03-02-SUMMARY) so the sanity check reflects retrieval quality, not the known bug.

## Deviations from Plan

The plan framed Task 2 as a human typing the calls by hand in the client; per user direction it was
instead demonstrated via the live endpoint and the operator approved the result. D-12 is explicitly
supplemental (the committed baseline is the 03-02/03-03 numbers), so this does not affect the numeric
baseline. No scope creep, no source changed.

## Issues Encountered

- Windows console rendered the Italian UTF-8 with `�` mojibake — cosmetic only; the stored/returned
  content is correct (snippets matched the real Wikipedia article verbatim).
- **Beyond plan scope (noted for context, not part of 03-04):** at the user's request the
  `turing-agentmemory` MCP was additionally adopted as this project's working memory (complement mode,
  tenant `davide_turing_AgentMemory_MCP`) — dogfooding the production system. Orthogonal to the D-12 gate.

## Next Phase Readiness

- **Phase 3 complete** — all 4 plans done; the ARC-01 TuringDB baseline is committed under
  `baseline/03-turingdb/` and now confidence-checked hands-on. Ingest → cited, tenant-scoped retrieval
  works end-to-end on the live stack.
- **Carry into Phase 4/6:** the ArcadeDB port comparison (ARC-09) must reproduce the *baselined* stack —
  same reranker (bge-reranker-v2-m3), same embedder (granite 768d), replay the frozen questions — and
  must fix the long-`document_id` scoped-search bug that deflates this baseline.

---
*Phase: 03-turingdb-retrieval-baseline*
*Completed: 2026-07-13*
