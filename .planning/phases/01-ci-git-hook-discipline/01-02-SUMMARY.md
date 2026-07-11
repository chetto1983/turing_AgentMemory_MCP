---
phase: 01-ci-git-hook-discipline
plan: 02
subsystem: infra
tags: [fastmcp, sqlite, http-server, gliner2, refactor]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline
    provides: store.py decomposed into 9 store_<concern>.py mixin modules (01-01), establishing the sibling-module concern-split precedent this plan follows
provides:
  - server.py split by MCP tool group (server_memory_tools.py, server_document_tools.py) behind registrar functions
  - document_jobs.py split into schema/dataclass (document_jobs_schema.py) vs SQLite session/query methods (document_jobs.py)
  - gliner_provider.py split into extraction/label-schema logic (gliner_provider_extraction.py) vs HTTP-server plumbing (gliner_provider_http.py)
  - all six resulting files (plus the 2 orchestrator/facade files) at or under the 600-LOC cap, no allowlist
affects: [01-03, 01-04, 01-05, 01-06, ci-git-hook-discipline hooks/CI phase work relying on the file-size cap]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP tool-group registrar functions: register_<group>_tools(app, memory, ..., tool_span) called from create_mcp_app, preserving the assembled FastMCP app exactly"
    - "Schema/session module split for SQLite-backed stores (document_jobs_schema.py holds the dataclass + row-serialization helpers; document_jobs.py holds DocumentJobStore's connection/query methods), matching sparse_index.py's module shape"
    - "Protocol-vs-HTTP-impl separation for HTTP providers (gliner_provider_extraction.py owns the provider contract/validation; gliner_provider_http.py owns BaseHTTPRequestHandler/ThreadingHTTPServer plumbing), matching entity_extraction.py's convention"

key-files:
  created:
    - src/turing_agentmemory_mcp/server_memory_tools.py
    - src/turing_agentmemory_mcp/server_document_tools.py
    - src/turing_agentmemory_mcp/document_jobs_schema.py
    - src/turing_agentmemory_mcp/gliner_provider_extraction.py
    - src/turing_agentmemory_mcp/gliner_provider_http.py
  modified:
    - src/turing_agentmemory_mcp/server.py
    - src/turing_agentmemory_mcp/document_jobs.py
    - src/turing_agentmemory_mcp/gliner_provider.py

key-decisions:
  - "server.py split into exactly two tool groups (memory, document) rather than three — this alone brought server.py from 762 to 257 LOC, well under the cap, so a third 'admin' group wasn't needed"
  - "gliner_provider.py's HTTP LOGGER keeps the literal name \"turing_agentmemory_mcp.gliner_provider\" (not module __name__) so it stays defined in gliner_provider_http.py without breaking tests that assert on caplog(logger=\"turing_agentmemory_mcp.gliner_provider\")"
  - "main()/_install_shutdown_signal_handlers()/_read_settings() stay in gliner_provider.py (not moved to a sibling) because tests monkeypatch gliner_provider.make_server and gliner_provider.signal directly by module attribute — moving them would break those patches"
  - "Payload-validation functions (_validate_extract_payload etc.) and RequestFailure live in gliner_provider_extraction.py, not gliner_provider_http.py, to keep the dependency one-directional (http -> extraction) and avoid a circular import between the two new siblings"

patterns-established:
  - "Registrar-function tool-group split for FastMCP apps: register_<group>_tools(app, memory, ..., tool_span) closures, called once each from create_mcp_app"

requirements-completed: [CI-01]

coverage:
  - id: D1
    description: "server.py split by MCP tool group into server_memory_tools.py/server_document_tools.py; create_mcp_app registers every original @app.tool(); create_mcp_app/auth_from_env import paths unchanged"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "tests/test_auth.py, tests/test_server_batch_tool.py, tests/test_governance.py"
        status: pass
      - kind: unit
        ref: "python -m pytest -q (362 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "document_jobs.py split into document_jobs_schema.py (DocumentIngestJob dataclass, schema constants, row serialization) and document_jobs.py (DocumentJobStore session/lease/heartbeat methods); DocumentJobStore/DocumentIngestJob import paths unchanged"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "tests/test_document_jobs.py, tests/test_document_job_manager.py"
        status: pass
      - kind: unit
        ref: "python -c \"from turing_agentmemory_mcp.document_jobs import DocumentJobStore, DocumentIngestJob\""
        status: pass
    human_judgment: false
  - id: D3
    description: "gliner_provider.py split into gliner_provider_extraction.py (GLiNERProvider, FastGLiNER2Adapter, payload validation) and gliner_provider_http.py (GLiNERHTTPServer, make_handler, make_server, start_server); GLiNERProvider/start_server import paths unchanged; caplog logger-name assertions still pass"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "tests/test_gliner_provider.py (53 tests, including caplog logger-name assertions)"
        status: pass
      - kind: unit
        ref: "python -c \"from turing_agentmemory_mcp.gliner_provider import GLiNERProvider, start_server\""
        status: pass
    human_judgment: false
  - id: D4
    description: "All server*/document_jobs*/gliner_provider*.py tracked files at or under 600 LOC (no allowlist); full pytest suite stays at 362 passed; ruff check clean"
    requirement: "CI-01"
    verification:
      - kind: unit
        ref: "git ls-files 'src/turing_agentmemory_mcp/server*.py' 'src/turing_agentmemory_mcp/document_jobs*.py' 'src/turing_agentmemory_mcp/gliner*.py' | while read f; do n=$(wc -l < \"$f\"); [ \"$n\" -le 600 ] || echo OVER; done (prints nothing)"
        status: pass
      - kind: unit
        ref: "python -m pytest -q (362 passed); python -m ruff check src tests scripts (clean)"
        status: pass
    human_judgment: false

duration: 16min
completed: 2026-07-11
status: complete
---

# Phase 1 Plan 2: Decompose server.py, document_jobs.py, gliner_provider.py Summary

**Split three over-cap modules (server.py 762, document_jobs.py 666, gliner_provider.py 658 LOC) into 600-LOC-or-under concern siblings — MCP tool-group registrars, SQLite schema/session boundary, and HTTP-plumbing/extraction-logic boundary — with every public import path (`create_mcp_app`, `auth_from_env`, `DocumentJobStore`, `DocumentIngestJob`, `GLiNERProvider`, `start_server`) preserved and the full 362-test suite unchanged.**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-07-11T20:29:31Z
- **Completed:** 2026-07-11T20:45:24Z
- **Tasks:** 2
- **Files modified:** 8 (3 modified, 5 created)

## Accomplishments

- `server.py` (762 LOC) split by MCP tool group: `server_memory_tools.py` (`register_memory_tools`, 14 `memory_*` tools) and `server_document_tools.py` (`register_document_tools`, 12 `document_*` tools). `server.py` now 257 LOC and still assembles the identical FastMCP app via two registrar calls from `create_mcp_app`.
- `document_jobs.py` (666 LOC) split into `document_jobs_schema.py` (130 LOC: `DocumentIngestJob` dataclass, `DOCUMENT_JOB_SCHEMA_VERSION`, and the `_instant`/`_timestamp`/`_json`/`_job` row-serialization helpers) and `document_jobs.py` (554 LOC: `DocumentJobStore`'s SQLite session/lease/heartbeat query methods), matching `sparse_index.py`'s schema-vs-session module shape.
- `gliner_provider.py` (658 LOC) split into `gliner_provider_extraction.py` (329 LOC: `GLiNERProvider`, `FastGLiNER2Adapter`, `ExtractProvider` Protocol, `RequestFailure`/`ProviderFailure`, all wire-payload validation and label-schema normalization) and `gliner_provider_http.py` (259 LOC: `GLiNERHTTPServer`, `make_handler`, `make_server`, `start_server`, `_canonical_path`), matching `entity_extraction.py`'s Protocol-vs-HTTP-impl convention. `gliner_provider.py` itself shrank to 105 LOC, keeping only `main()`, `_read_settings()`, `_install_shutdown_signal_handlers()`, and re-exports.
- All eight resulting/modified files are ≤600 LOC (largest is `document_jobs.py` at 554); full suite stays at 362 passed; `ruff check src tests scripts` clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: Split server.py by MCP tool group** - `2c45d86` (refactor)
2. **Task 2: Split document_jobs.py and gliner_provider.py** - `086b296` (refactor)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `src/turing_agentmemory_mcp/server_memory_tools.py` - `register_memory_tools(app, memory, tool_span)`; the 14 `memory_*` MCP tools, moved verbatim
- `src/turing_agentmemory_mcp/server_document_tools.py` - `register_document_tools(app, memory, uploads, document_manager, tool_span)`; the 12 `document_*` MCP tools, moved verbatim
- `src/turing_agentmemory_mcp/server.py` - now holds env-config factories, `store_from_env`, `create_mcp_app` (health route + two registrar calls), `auth_from_env`
- `src/turing_agentmemory_mcp/document_jobs_schema.py` - `DocumentIngestJob` dataclass, schema constants, row (de)serialization helpers
- `src/turing_agentmemory_mcp/document_jobs.py` - `DocumentJobStore` only (SQLite init/enqueue/claim/lease/cancel/retry/succeed query methods), imports schema helpers
- `src/turing_agentmemory_mcp/gliner_provider_extraction.py` - `ExtractProvider` Protocol, `RequestFailure`/`ProviderFailure`, `FastGLiNER2Adapter`, `GLiNERProvider`, all payload-validation/normalization helpers
- `src/turing_agentmemory_mcp/gliner_provider_http.py` - `GLiNERHTTPServer`, `make_handler`, `_canonical_path`, `make_server`, `start_server`, the request-scoped `LOGGER`
- `src/turing_agentmemory_mcp/gliner_provider.py` - `main()`, `_read_settings()`/`_read_bounded_int()`, `_install_shutdown_signal_handlers()`, plus re-exports of the names external code/tests still resolve via `gliner_provider.*`

## Decisions Made

- **Two tool groups, not three:** splitting `server.py` into `server_memory_tools.py`/`server_document_tools.py` alone dropped it to 257 LOC — well under the cap — so a separate "admin" siblings wasn't warranted; kept the split minimal per scope control.
- **HTTP LOGGER keeps its original dotted name:** `gliner_provider_http.py` defines `LOGGER = logging.getLogger("turing_agentmemory_mcp.gliner_provider")` (literal string, not `__name__`) so `tests/test_gliner_provider.py`'s `caplog.set_level(logging.INFO, logger="turing_agentmemory_mcp.gliner_provider")` assertions keep passing even though the HTTP handler code now physically lives in a different module file.
- **`main()`/`_install_shutdown_signal_handlers()`/`_read_settings()` stay in `gliner_provider.py`:** several tests do `monkeypatch.setattr(gliner_provider, "make_server", ...)` and `monkeypatch.setattr(gliner_provider.signal, "signal", ...)` — these rely on `main()`'s `__globals__` being `gliner_provider.__dict__` and on `signal` being imported directly into that module. Moving `main()` to a sibling would have broken both patch points.
- **Validation functions and `RequestFailure` live in `gliner_provider_extraction.py`, not `gliner_provider_http.py`:** `GLiNERProvider.extract()`/`extract_memory()` call the validation functions directly, and the HTTP dispatch also calls them for pre-counting. Putting them in the extraction module makes the dependency strictly one-directional (`gliner_provider_http.py` imports from `gliner_provider_extraction.py`, never the reverse), avoiding a circular import between the two new siblings.
- Ran `ruff check --fix` (import-sort only, `I001`) on each newly-written/modified file immediately after creation, then re-verified `ruff check` clean with no `--fix` — a mechanical, behavior-preserving step, not a manual deviation.

## Deviations from Plan

None - plan executed exactly as written. The plan explicitly left new-sibling naming and the exact tool-group/schema-session/HTTP-extraction split boundaries to executor judgment; no rule-1/2/3/4 deviations were needed — no bugs found, no missing critical functionality, no blocking issues, no architectural changes.

## Issues Encountered

- Initial `document_jobs.py` split landed at 554 LOC — comfortably under the 600 cap but the tightest margin of the three splits (versus 257/554/105 for the others). No further sub-split was needed; verified explicitly with `wc -l` and the tracked-file sweep.
- The gliner_provider split required tracing three cross-cutting constraints before writing any code: (1) the `caplog` logger-name coupling in `tests/test_gliner_provider.py`, (2) the `monkeypatch.setattr(gliner_provider, "make_server"/"signal", ...)` module-attribute coupling, and (3) avoiding a circular import between the two new siblings given `RequestFailure`/validation functions are used by both the provider class and the HTTP dispatch layer. All three were resolved by keeping `main()` and the signal-handler installer in the orchestrator file and by making `gliner_provider_http.py` depend one-directionally on `gliner_provider_extraction.py`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three plan-02 target modules (`server.py`, `document_jobs.py`, `gliner_provider.py`) and their five new concern siblings are ≤600 LOC, satisfying the file-size precondition this phase's `check-file-size.sh` hook depends on.
- Public import paths (`create_mcp_app`, `auth_from_env`, `DocumentJobStore`, `DocumentIngestJob`, `GLiNERProvider`, `start_server`) are unchanged; downstream plans (01-03 onward, and the later `tests/test_gliner_provider.py` split in 01-05) can rely on `gliner_provider_http.py`/`gliner_provider_extraction.py` module names matching what 01-05's plan already anticipates (`test_gliner_provider_http.py`/`test_gliner_provider_extraction.py`).
- **E2E score gate deferred to orchestrator Docker run** — `scripts/e2e_score.py` requires `turingdb`, which is Linux/macOS-only and not installable on this Windows execution host (`python scripts/e2e_score.py` and any `from turing_agentmemory_mcp.server import ...` at the interpreter level both fail at import for this environment-only reason, not a code regression). The Windows-side behavior gate used here was `pytest -q` (362 passed) + `ruff check` (clean) + the tracked file-size sweep (no violations). The orchestrator's `docker compose run --rm e2e` after this wave is the authoritative E2E confirmation.

---
*Phase: 01-ci-git-hook-discipline*
*Completed: 2026-07-11*

## Self-Check: PASSED

All 8 created/modified files verified present on disk; both task commits (`2c45d86`, `086b296`) verified present in git history.
