---
phase: 02-utcp-spike
plan: 01
subsystem: testing
tags: [utcp, pydantic-validation, conformance, spike]

# Dependency graph
requires:
  - phase: 01-ci-git-hook-discipline
    provides: no-skip-as-green pytest guard (tests/conftest.py), CI marker conventions
provides:
  - "scripts/spike/requirements.txt pinning the five spike-only UTCP packages out-of-tree"
  - "tests/test_utcp_conformance.py — committed, Docker-free, source-verified reproduction of SC#1 static gaps #1 and #3"
  - ".gitignore hardening against committed spike secrets/GGUF binaries"
affects: [02-02-utcp-live-roundtrip, 02-03-utcp-findings]

# Tech tracking
tech-stack:
  added: ["utcp==1.1.3 (spike-only)", "utcp-mcp==1.1.2 (spike-only)", "utcp-http==1.1.11 (spike-only)", "utcp-text==1.1.0 (spike-only)", "utcp-agent==1.0.3 (spike-only)", "langchain-openai>=0.3,<1.0 (spike-only, optional D-08a)"]
  patterns: ["pytest.importorskip module-level guard for optional heavyweight test deps", "verbatim turingdb sys.modules stub reused from tests/test_utcp_manual.py for Windows-safe imports"]

key-files:
  created: [scripts/spike/requirements.txt, tests/test_utcp_conformance.py]
  modified: [.gitignore]

key-decisions:
  - "Pinned langchain-openai to >=0.3,<1.0 instead of the plan-drafted >=1.0.0 — utcp-mcp transitively pins langchain<0.4.0 which caps langchain-core<1.0.0, and langchain-openai>=1.0.0 requires langchain-core>=1.4.9; the two are unresolvable together (verified via pip's resolver, dry-run confirmed langchain-openai-0.3.35 resolves cleanly)."
  - "Kept the test file to exactly the two conformance tests named in the plan's must_haves.artifacts, dropping an extra smoke test written during authoring to stay scoped to the documented deliverable."

patterns-established:
  - "Spike-only, out-of-tree pip pins live in scripts/spike/requirements.txt (flat pkg==version list), never in pyproject.toml — this is the first such file in the repo and sets the precedent for plan 02-02's harness scripts."

requirements-completed: [UTCP-01]

coverage:
  - id: D1
    description: "scripts/spike/requirements.txt pins the five UTCP packages out-of-tree; installs cleanly and imports without touching pyproject.toml"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "python -m pip install -r scripts/spike/requirements.txt && python -c \"import utcp, utcp_mcp, utcp_http, utcp_text, utcp_agent\""
        status: pass
      - kind: unit
        ref: "grep for utcp package names in pyproject.toml — absent"
        status: pass
    human_judgment: false
  - id: D2
    description: "tests/test_utcp_conformance.py::test_manual_with_auth_fails_current_utcp_pydantic_validation reproduces SC#1 gap #1 (api_key auth vs McpCallTemplate.auth: Optional[OAuth2Auth]) as an observed pydantic ValidationError, with no dummy-token leak"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "tests/test_utcp_conformance.py::test_manual_with_auth_fails_current_utcp_pydantic_validation"
        status: pass
    human_judgment: false
  - id: D3
    description: "tests/test_utcp_conformance.py::test_readme_utcp_config_example_is_stale reproduces SC#1 gap #3 (README's text/file_path example rejected by the current TextCallTemplateSerializer)"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "tests/test_utcp_conformance.py::test_readme_utcp_config_example_is_stale"
        status: pass
    human_judgment: false
  - id: D4
    description: "Conformance test module stays unmarked and skips cleanly under CI when spike deps are absent, never tripping the Phase-1 no-skip-as-green guard"
    requirement: UTCP-01
    verification:
      - kind: unit
        ref: "tests/conftest.py no-skip-as-green guard enforces only integration/gpu markers; grep confirms no pytestmark in tests/test_utcp_conformance.py"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 01: UTCP Static Conformance Spike Summary

**Committed pytest that feeds `utcp.py`'s real output through the installed python-utcp pydantic serializers and observes both documented SC#1 gaps as genuine `UtcpSerializerValidationError` failures — zero Docker, zero `src/` changes.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2
- **Files modified:** 3 (`scripts/spike/requirements.txt` created, `tests/test_utcp_conformance.py` created, `.gitignore` modified)

## Accomplishments

- Pinned the five spike-only UTCP packages (`utcp`, `utcp-mcp`, `utcp-http`, `utcp-text`, `utcp-agent`) at their PyPI-latest versions in `scripts/spike/requirements.txt`, confirmed installable and importable, and confirmed zero footprint in `pyproject.toml`.
- Hardened `.gitignore` against committing spike secrets (`scripts/spike/.env`, `*.local`) or the GGUF model binary (`scripts/spike/*.gguf`) referenced by the optional D-08a full-agent-chat spike.
- Wrote `tests/test_utcp_conformance.py` with two tests, both observed (not reasoned) to reproduce SC#1's documented gaps against the currently-installed `utcp`/`utcp-text` packages:
  - Gap #1: `utcp_manual_from_env()`'s auth-enabled output raises `UtcpSerializerValidationError` when validated by `UtcpManualSerializer` — `api_key` auth does not satisfy `McpCallTemplate.auth: Optional[OAuth2Auth]`. Verified the dummy token never leaks into the dumped manual JSON.
  - Gap #3: README's `UTCP_CONFIG_FILE` example (`call_template_type: "text"` + `file_path`) is rejected by the installed `TextCallTemplateSerializer`, which now requires the separate `utcp-file` plugin's `file` call-template type.
- Confirmed the test module is unmarked (no `integration`/`gpu` pytest markers) and gated only by `pytest.importorskip`, so it never trips the Phase-1 no-skip-as-green CI guard when spike deps are absent.
- Ran the full repo test suite (374 passed) and full ruff check (clean) after the change — no regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Pin spike-only UTCP dependencies out-of-tree + harden .gitignore** - `2d5bd1d` (feat)
2. **Task 2: Committed static-conformance pytest reproducing SC#1 gaps #1 and #3** - `40600bd` (test)

**Plan metadata:** (this commit, docs: complete plan)

_Note: Task 2 is a "characterization test" per the plan's own documented RED/GREEN semantics — it passes because the real python-utcp library genuinely rejects our current output, not because a src/ implementation was added afterward. A single `test(...)` commit is the correct artifact; there is no accompanying `feat(...)` GREEN commit because SC#3 forbids any src/ change this plan._

## Files Created/Modified

- `scripts/spike/requirements.txt` - Flat pinned list of the five spike-only UTCP packages, plus optional `langchain-openai`/`python-dotenv` for the D-08a full-agent-chat path (plan 02-02). Never referenced from `pyproject.toml`.
- `tests/test_utcp_conformance.py` - Two committed, Docker-free tests reproducing SC#1 gaps #1 and #3 against the real installed python-utcp serializers.
- `.gitignore` - Added a `# Phase 2 UTCP spike (throwaway)` block ignoring `scripts/spike/*.gguf`, `scripts/spike/.env`, `scripts/spike/*.local`.

## Decisions Made

- **`langchain-openai` pin corrected to `>=0.3,<1.0`** (plan drafted `>=1.0.0`): `pip install -r scripts/spike/requirements.txt` failed with `ResolutionImpossible` under the plan's literal draft. Root cause: `utcp-mcp==1.1.2` transitively requires `langchain<0.4.0,>=0.3.27`, which pins `langchain-core<1.0.0`; `langchain-openai>=1.0.0` requires `langchain-core>=1.4.9`. These two constraints cannot both hold. Verified `langchain-openai>=0.3,<1.0` resolves cleanly (installs `langchain-openai-0.3.35`) alongside the other four pinned packages with no conflicts. This affects only the optional D-08a color path (full-agent chat); the five core packages required for `test_utcp_conformance.py` were unaffected either way.
- **Dropped a third smoke test** (`test_build_utcp_manual_is_importable_without_docker`) that was written during authoring but not in the plan's `must_haves.artifacts` — removed to keep the file scoped to exactly the two documented deliverables.
- **Re-verified all five core package pins** against live PyPI (`pip index versions`) immediately before implementation, per the plan's freshness instruction: `utcp==1.1.3`, `utcp-mcp==1.1.2`, `utcp-http==1.1.11`, `utcp-text==1.1.0`, `utcp-agent==1.0.3` are all still PyPI-latest — no changes needed to those five pins.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed unresolvable `langchain-openai>=1.0.0` pin in `scripts/spike/requirements.txt`**
- **Found during:** Task 1 verification (`pip install -r scripts/spike/requirements.txt`)
- **Issue:** The plan's literal draft (`langchain-openai>=1.0.0`) is mathematically unresolvable alongside `utcp-mcp`'s transitive `langchain<0.4.0` pin (which caps `langchain-core<1.0.0`), producing a `ResolutionImpossible` error on `pip install`.
- **Fix:** Re-pinned to `langchain-openai>=0.3,<1.0` with an inline comment explaining the constraint chain. Verified via `pip install --dry-run` that this resolves cleanly to `langchain-openai-0.3.35`, then confirmed the full install succeeds.
- **Files modified:** `scripts/spike/requirements.txt`
- **Verification:** `python -m pip install -r scripts/spike/requirements.txt` succeeds; `python -c "import utcp, utcp_mcp, utcp_http, utcp_text, utcp_agent"` succeeds.
- **Committed in:** `2d5bd1d` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — Rule 1)
**Impact on plan:** Necessary correctness fix; the plan's exact pin as drafted would have made Task 1's own acceptance criterion (`pip install` succeeds) unsatisfiable. No scope creep — only the optional D-08a color-path pin changed; the five core spike deps are exactly as researched.

## Issues Encountered

None beyond the dependency-resolution fix documented above.

## Next Phase Readiness

- `scripts/spike/requirements.txt` is ready for plan 02-02 to reuse for the live Docker round-trip harness and D-06 native-http prototype.
- SC#1's static-evidence half (gaps #1 and #3) is committed and reproducible; plan 02-02 supplies the live-round-trip half (D-01/D-02/D-07/D-08) and plan 02-03 writes the D-09 `FINDINGS.md` verdict weighing both.
- No blockers. `scripts/spike/*.gguf`/`.env`/`*.local` ignores are in place ahead of plan 02-02's optional D-08a Gemma sidecar work.

---
*Phase: 02-utcp-spike*
*Completed: 2026-07-12*

## Self-Check: PASSED

- FOUND: scripts/spike/requirements.txt
- FOUND: tests/test_utcp_conformance.py
- FOUND: .planning/phases/02-utcp-spike/02-01-SUMMARY.md
- FOUND commit: 2d5bd1d
- FOUND commit: 40600bd
- FOUND commit: f19b3ec
