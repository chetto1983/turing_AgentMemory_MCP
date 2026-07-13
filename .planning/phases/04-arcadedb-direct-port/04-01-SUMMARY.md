---
phase: 04-arcadedb-direct-port
plan: 01
subsystem: database
tags: [arcadedb, docker-compose, urllib, vector-search, full-text, spike]

requires: []
provides:
  - "arcadedb Compose service (arcadedata/arcadedb:26.7.1) on a persistent volume, hardened non-root/tmpfs/security_opt, add-only alongside turingdb"
  - "ArcadeDBClient (src/turing_agentmemory_mcp/arcadedb_client.py) — thin stdlib-urllib query/command/begin/commit/rollback/is_ready client"
  - "tests/test_arcadedb_client.py — committed live smoke test resolving all five D-02 capability unknowns"
  - "scripts/arcadedb_spike.py — re-runnable D-04/D-05 bake-off harness"
  - "04-SPIKE-FINDINGS.md — the D-02 hard-gate decision record (D-03/D-04/D-05) every downstream wave consumes"
affects: [04-02, 04-03, 04-04, 04-05, 04-06, 04-07, 04-08, 04-09]

tech-stack:
  added: ["arcadedata/arcadedb:26.7.1 (Docker image, no new pip dependency)"]
  patterns:
    - "ArcadeDBClient mirrors OpenAICompatibleEmbedder/Reranker exactly: frozen dataclass, from_env(), urllib retry-with-backoff, raise-hard on exhaustion"
    - "All query values (including vector literals and IN-array params) bound as named/positional params via ArcadeDB's own params field -- never inline string interpolation"
    - "arcadedb-session-id header session model for cross-call read-your-writes transactions (D-08 groundwork); sqlscript LET-chaining as the alternative single-call batch mechanism"

key-files:
  created:
    - src/turing_agentmemory_mcp/arcadedb_client.py
    - tests/test_arcadedb_client.py
    - scripts/arcadedb_spike.py
    - .planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md
  modified:
    - compose.yaml
    - .env.example

key-decisions:
  - "D-03 (confirmed, unchanged): keep over-fetch-then-filter for filtered vector search -- k-underfill is empirically present (post-filter, not HNSW pushdown)"
  - "D-04 (spike-decided): native LSM_SPARSE_VECTOR (vector.sparseNeighbors) wins the lexical channel over Lucene SEARCH_INDEX -- higher MRR/recall and zero errors on the 60-question yardstick vs 2/60 Lucene query-parse failures on unescaped natural-language punctuation"
  - "D-05 (spike-decided): SQL MATCH/TRAVERSE wins the graph-query surface over openCypher -- same query language as vectorNeighbors/SEARCH_INDEX, so one statement composes traversal with ranking"
  - "Corrected a locked CONTEXT.md assumption: ArcadeDB 26.7.1 vector literals ARE bindable as named params (not inline-only) -- client and tests bind them"
  - "Endpoint prefix resolved as /api/v1/{query,command,begin,commit,rollback}/<db> (not the unversioned /query/graph/<db> form this repo's generic arcadedb skill shows)"
  - "arcadedb Compose service runs as the image's native uid 1000 (not this repo's 10001 convention, which belongs to custom-built Dockerfiles, not this stock image)"

patterns-established:
  - "Live-container capability spikes: prove empirically against the pinned image via a committed pytest smoke test marked `integration`, never trust doc-sourced syntax claims that disagree across sources"
  - "Bake-off corpus built from already-committed evidence_quote excerpts when source document bytes are external/uncommitted (D-06) -- keeps re-runnable scripts grounded in real text without needing the original files"

requirements-completed: [ARC-02, ARC-03]

coverage:
  - id: D1
    description: "arcadedb Compose service starts healthy on a persistent volume, turingdb untouched"
    requirement: "ARC-02"
    verification:
      - kind: integration
        ref: "docker compose up -d arcadedb && docker compose ps arcadedb (observed: healthy); tests/test_docker_hardening.py, tests/test_compose_config.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "ArcadeDBClient + live smoke test resolve all five D-02 capability unknowns with concrete assertions"
    requirement: "ARC-03"
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_client.py (7 tests, run against live arcadedata/arcadedb:26.7.1 container)"
        status: pass
    human_judgment: false
  - id: D3
    description: "D-04/D-05 bake-off harness produces a parity-diffable JSON artifact and the findings doc records D-03/D-04/D-05 with evidence"
    verification:
      - kind: integration
        ref: "scripts/arcadedb_spike.py --out .benchmarks/arcadedb-spike.json (run live); .planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md"
        status: pass
    human_judgment: false

duration: 50min
completed: 2026-07-13
status: complete
---

# Phase 4 Plan 1: ArcadeDB D-02 Spike Summary

**Resolved all five ArcadeDB 26.7.1 capability unknowns empirically against a live container and picked the D-03/D-04/D-05 winners (over-fetch-then-filter, native sparse-vector lexical channel, SQL graph traversal) with bake-off evidence — the hard gate blocking every downstream query-builder wave is now closed.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-07-13
- **Tasks:** 3/3 completed
- **Files modified:** 5 (2 modified, 3 new) + 1 new doc

## Accomplishments

- Stood up a hardened `arcadedb` Compose service (`arcadedata/arcadedb:26.7.1`, digest
  `sha256:37db3d210bde5849ba5c772ce33b8666b215a77f7b88331fda31fbbf2d130738`) on a
  persistent named volume, add-only alongside `turingdb` (grep count for
  `turingdb:` unchanged: 5).
- Wrote a minimal, thin stdlib-`urllib` `ArcadeDBClient` and a committed live
  smoke test (`tests/test_arcadedb_client.py`, 7 tests, marked `integration`)
  that resolved all five D-02 unknowns with concrete, not enumerated, assertions.
- Built `scripts/arcadedb_spike.py`, a re-runnable D-04/D-05 bake-off harness
  that indexed the real, committed `evidence_quote` excerpts from
  `baseline/03-turingdb/frozen-questions.json` (60 questions, 12 documents)
  plus 8 hand-authored lexical-stress queries into ArcadeDB with both lexical
  channels, and prototyped the 2-hop entity→fact→memory traversal in both
  SQL MATCH and openCypher.
- Wrote `04-SPIKE-FINDINGS.md`, the written decision record every downstream
  wave consumes: resolved HTTP surface, vector function/DDL, transaction
  model, full-text score exposure, and the D-03/D-04/D-05 decisions with
  bake-off evidence.
- Discovered and documented a real, previously-undocumented fragility:
  `SEARCH_INDEX`'s query argument is parsed as raw Lucene query syntax, so
  unescaped natural-language punctuation (`?`, `*`, `(`, `)`) can raise a
  parse exception — 2 of 60 frozen questions failed this way live. This
  directly fed the D-04 decision toward `LSM_SPARSE_VECTOR`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Stand up the hardened arcadedb Compose service** - `e93673e` (feat)
2. **Task 2: Minimal ArcadeDBClient + committed smoke test** - `c0eaa9c` (feat)
3. **Task 3: D-04/D-05 bake-off + spike findings** - `633ef33` (feat)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP/REQUIREMENTS update)

_Note: no TDD RED/GREEN gate applies — this plan's type is `execute`, not `tdd`._

## Files Created/Modified

- `compose.yaml` - new `arcadedb` service block (hardened, uid 1000, persistent volume, wget-based healthcheck against `/api/v1/ready`) + `arcadedb-data` volume
- `.env.example` - `ARCADEDB_URL`/`ARCADEDB_DATABASE`/`ARCADEDB_USER`/`ARCADEDB_PASSWORD` (add-only, `${VAR:-default}` convention)
- `src/turing_agentmemory_mcp/arcadedb_client.py` - thin urllib client: `query`/`command`/`begin`/`commit`/`rollback`/`is_ready`/`probe`/`ensure_database`
- `tests/test_arcadedb_client.py` - the D-02 hard-gate smoke test (7 tests, `integration`-marked)
- `scripts/arcadedb_spike.py` - the D-04/D-05 bake-off harness
- `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md` - the written decision record

## Decisions Made

- **D-03 (confirmed, no change):** keep the existing over-fetch-then-filter pattern for
  filtered vector search. Evidence: a live fixture proved k-underfill (a
  `k=2` filtered query returned only 1 of 3 matching active records; `k=20`
  recovered all 3).
- **D-04 (spike-decided): native `LSM_SPARSE_VECTOR`** (`vector.sparseNeighbors`) is the
  winning lexical channel. Evidence: on the 60-question frozen yardstick it
  beat Lucene `SEARCH_INDEX` on MRR@20 (0.577 vs 0.546), recall@20 (0.85 vs
  0.733), had zero search errors (vs 2/60 for Lucene), and ~6x lower mean
  latency. Lucene narrowly won the 8-query lexical-stress set, but that does
  not offset its raw-query-parsing fragility and the sparse channel's native
  scorability for RRF.
- **D-05 (spike-decided): SQL `MATCH`/`TRAVERSE`** is the winning graph-query
  surface. Evidence: both SQL and openCypher bind params cleanly and
  complete the 2-hop prototype, but only SQL is the same `language` as
  `vectorNeighbors`/`SEARCH_INDEX`, letting one statement traverse and rank.
- **Endpoint prefix, vector DDL, and transaction model resolved by live testing,
  not doc consultation** — `/api/v1/...`, `CREATE INDEX ON Type (prop)
  LSM_VECTOR METADATA {...}`, and an `arcadedb-session-id` header session
  model, all confirmed against the pinned 26.7.1 image and documented in
  04-SPIKE-FINDINGS.md so no later wave re-derives them from disagreeing docs.
- **Corrected a locked CONTEXT.md assumption:** vector literals ARE bindable as
  named params on 26.7.1 (the "vector literals must be inlined" assumption
  from capabilities §1 [S5] does not hold) — the client and tests bind every
  value, including vectors, as params.
- **`arcadedb` Compose service runs as uid 1000** (the stock image's own
  non-root user), not this repo's 10001 convention — that convention belongs
  to custom-built Dockerfiles (turingdb, llama-provider, gliner-provider), not
  a stock third-party image; Docker correctly inherits ownership onto the
  fresh named volume (verified live).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Empty-credential auth test asserted the wrong HTTP status**
- **Found during:** Task 2 (writing the smoke test)
- **Issue:** `test_credentials_are_required_and_enforced` initially asserted
  HTTP 401 for empty username/password, but `ArcadeDBClient` always sends a
  (possibly-empty) `Authorization: Basic` header, so ArcadeDB returns 403
  ("Basic authentication error"), not 401 (which only occurs when the header
  is fully absent, confirmed separately via raw `curl`).
- **Fix:** Updated the test's expected status to 403 with an explanatory
  comment distinguishing this from the raw-curl-confirmed 401 (no-header)
  case; both paths still prove auth is enforced (T-04-01-01).
- **Files modified:** `tests/test_arcadedb_client.py`
- **Verification:** `pytest tests/test_arcadedb_client.py -q` — all 7 pass
- **Committed in:** `c0eaa9c` (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — test assertion corrected to match
actual, verified server behavior).
**Impact on plan:** No scope creep — the fix is a test-correctness adjustment
discovered while proving the exact auth behavior the plan's threat model
required (T-04-01-01).

## Issues Encountered

None beyond the deviation above. The `LSM_SPARSE_VECTOR` DDL required all four
metadata keys to avoid a startup error the first time (`dimensions`,
`similarity`, `maxConnections`, `beamWidth`) — resolved by reading the engine's
own error message, not a retry loop; not counted as a deviation since it was
resolved on the first corrected attempt while empirically deriving the DDL
form (the literal point of this spike).

## User Setup Required

None — no external service configuration required. The `arcadedb` Compose
service is self-contained; `ARCADEDB_PASSWORD` has a usable local-dev default
in `.env.example` (documented as needing override for any non-local deployment).

## Next Phase Readiness

The D-02 hard gate is satisfied: Wave 2+ query-builder plans can now build
against the resolved, live-confirmed ArcadeDB syntax in
`04-SPIKE-FINDINGS.md` (endpoint prefix, `vectorNeighbors` DDL/query form,
`LSM_SPARSE_VECTOR` DDL/query form, SQL `MATCH` traversal, session-header
transaction model) without re-deriving any of it from disagreeing
documentation. No store_*.py query builder was touched this plan (prohibited,
honored). `retrieval_fusion.py`'s RRF weights are unchanged. The `arcadedb`
container is currently running locally (`docker compose up -d arcadedb`,
healthy) for the next wave's convenience, though nothing in this plan requires
it to stay up between sessions.

---
*Phase: 04-arcadedb-direct-port*
*Completed: 2026-07-13*

## Self-Check: PASSED

All created/modified files found on disk; all three task commit hashes
(`e93673e`, `c0eaa9c`, `633ef33`) found in git history.
