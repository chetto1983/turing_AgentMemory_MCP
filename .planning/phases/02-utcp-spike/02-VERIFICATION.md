---
phase: 02-utcp-spike
verified: 2026-07-12T19:40:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: UTCP Spike Verification Report

**Phase Goal:** A findings verdict on whether to natively serve tools over UTCP (vs. the current manual export) exists and gates any future UTCP build work.
**Verified:** 2026-07-12T19:40:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

This is a findings-only spike phase (roadmap SC#3 explicitly forbids production build work). Success
is judged by: (a) a defensible, evidence-backed verdict exists, (b) SC#1 gaps are documented against
a real UTCP client (not reasoned), (c) the SC#3 hard gate holds (zero build work leaked into `src/`
or `compose.yaml`), and (d) UTCP-01 traceability is coherent. All four were independently
re-executed against the live codebase — not read from SUMMARY narrative.

### Observable Truths (Roadmap Success Criteria)

| # | Truth (Roadmap SC) | Status | Evidence |
|---|------|--------|----------|
| 1 | The current `utcp.py`/`utcp-manual` export is exercised against a real UTCP client/spec and its gaps are documented | ✓ VERIFIED | `tests/test_utcp_conformance.py` re-run live: `2 passed` against the real installed `utcp`/`utcp_text` pydantic serializers (gaps #1 auth-type, #3 README `file_path`). `scripts/spike/utcp_roundtrip.py --dry-run` re-run live: prints the corrected `McpCallTemplate` JSON, confirming gap #2 (command/args shape). `02-FINDINGS.md` documents a 4th gap (tool-name double-prefixing) observed only via the live round-trip per 02-02-SUMMARY.md's captured Docker+GPU run. |
| 2 | A written verdict recommends native UTCP serving, staying on manual export, or deferring — with rationale | ✓ VERIFIED | `.planning/phases/02-utcp-spike/02-FINDINGS.md` contains a `## Verdict` heading naming exactly one option — **stay-manual** — with rationale grounded in the D-04 empirical section (live round-trip succeeded end-to-end) weighed against the D-06 native-http prototype's demonstrated integration cost. A `## Trigger Conditions` section is present for future revisit. |
| 3 | No UTCP build work is committed by this phase; any follow-on work is explicitly gated on the verdict | ✓ VERIFIED | Independently re-ran all three SC#3 guard commands (not trusted from FINDINGS.md): `grep -rl "HttpCallTemplate\|utcp_http\|http_call_template" src/` → empty, exit 1. `git diff --stat d3fd272..HEAD -- src/` → empty. `git diff --stat d3fd272..HEAD -- compose.yaml` → empty. `git log --oneline d3fd272..HEAD` shows only test/docs/scripts/spike commits. PROJECT.md line 114 has a Key Decisions row recording the stay-manual verdict citing `02-FINDINGS.md`; ROADMAP.md is correctly unmodified (no gated backlog entry, since verdict ≠ build, per D-10 rule). |

### Additional Plan-Level Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 4 | Spike deps install out-of-tree, never in pyproject.toml | ✓ VERIFIED | `scripts/spike/requirements.txt` contains the 5 pinned UTCP packages + optional `langchain-openai`/`python-dotenv`. `grep -i utcp pyproject.toml` → no output (zero footprint). Deps confirmed already installed in `.venv` (tests import and pass live). |
| 5 | UTCP-01 requirement traceability is coherent with delivered evidence | ✓ VERIFIED | REQUIREMENTS.md line 93 defines UTCP-01 as "spike... produces a verdict — any build work is gated on it"; line 180 marks it Complete, mapped 1:1 to Phase 2 (line 191, coverage table: 55/55 mapped, 0 unmapped). Delivered FINDINGS.md verdict + D-10 gating matches the requirement text exactly. |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/spike/requirements.txt` | Pinned spike-only UTCP deps | ✓ VERIFIED | 12 lines, 5 `==` pins + optional D-08a deps with documented resolver-conflict comment. Exists, substantive, not referenced by pyproject.toml (correctly out-of-tree). |
| `tests/test_utcp_conformance.py` | Committed static-conformance pytest (SC#1 static evidence) | ✓ VERIFIED | 58 lines. Re-ran live: `python -m pytest tests/test_utcp_conformance.py -v` → 2 passed. Real assertions against real `utcp`/`utcp_text` pydantic serializers, no stub logic, no-leak assertion present (`assert "throwaway-dummy-token" not in json.dumps(manual)`). Unmarked, `pytest.importorskip`-gated (confirmed no `integration`/`gpu` marker — never trips CI's no-skip-as-green guard). |
| `scripts/spike/utcp_roundtrip.py` | Live mcp round-trip harness, `main() -> int` | ✓ VERIFIED | 198 lines. `--dry-run` re-run live: exits 0, prints corrected `McpCallTemplate` (`command` string + separate `args` list). 02-02-SUMMARY.md documents the full live run (Docker + GPU) with real evidence (26 tools discovered, `memory_store_message`/`memory_search` round-trip succeeded) — this session did not re-run the Docker/GPU path (would require standing up the full compose stack) but the dry-run half + the SUMMARY's structured evidence (memory ID `mem_3257ccf8a5843684`, rerank model name) is consistent with a genuine run, not a fabricated narrative. |
| `scripts/spike/native_http_prototype.py` | Throwaway http prototype, `main()` with `--self-test` | ✓ VERIFIED | 232 lines. Re-ran live: `--self-test` → full start→register→call→teardown cycle against the real `UtcpClient` succeeded, printed the integration-surface enumeration and backing-mode disclosure. Grep confirms no `0.0.0.0` binding (127.0.0.1 only, 3 occurrences). Not referenced in compose.yaml. |
| `scripts/spike/full_agent_chat.py` | Optional agent chat, `main()` with GPU/endpoint probe + `--check` | ✓ VERIFIED | 156 lines. Re-ran live: `--check` → "GPU (nvidia-smi) available: True" / "llama.cpp endpoint reachable: False" / explicit "full-agent chat NOT exercised (no GPU / endpoint unavailable)" — matches the required non-silent-skip behavior exactly. |
| `.planning/phases/02-utcp-spike/02-FINDINGS.md` | D-09 verdict deliverable | ✓ VERIFIED | 282 lines. Contains `## SC#1 — Documented Gaps` (4 gaps with source citations), `## D-05`, `## D-04`, `## Verdict` (stay-manual), `## SC#3 — No Build Work Committed` (audit trail incl. a transparently-investigated false-positive grep match), `## Trigger Conditions`. Self-contained, cites RESEARCH source lines and SUMMARY evidence throughout. |
| PROJECT.md Key Decisions row | Records the UTCP verdict | ✓ VERIFIED | Line 114: `UTCP: stay-manual (keep mcp-call-template manual export; no native http/cli serving build)` row present with rationale + outcome columns, correctly scoped edit (not a whole-file rewrite). |
| ROADMAP.md gated backlog entry | Conditional — only if verdict=build | ✓ VERIFIED (correctly absent) | Verdict is stay-manual, not build; `git diff --stat d3fd272..HEAD -- .planning/ROADMAP.md` shows no diff for this phase's plans (Phase 2 entry itself was already present pre-phase from planning). No gated UTCP-build phase entry added, consistent with D-10's conditional rule. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `tests/test_utcp_conformance.py` | `src/turing_agentmemory_mcp/utcp.py` | `from turing_agentmemory_mcp.utcp import utcp_manual_from_env`, behind the turingdb sys.modules stub | ✓ WIRED | Import present at line 21; live test run exercises `utcp_manual_from_env()` output against real serializers. |
| `02-FINDINGS.md` | 02-01/02-02 evidence | Cites `tests/test_utcp_conformance.py`, `scripts/spike/utcp_roundtrip.py`, `02-01-SUMMARY.md`, `02-02-SUMMARY.md` by name with specific line/commit references | ✓ WIRED | FINDINGS.md gap sections cite exact test names, source file paths/lines, and commit hashes (e.g. `7f48022`) traceable to the actual git log. |
| ROADMAP.md gated entry | FINDINGS.md verdict | N/A — no entry added since verdict ≠ build | ✓ CORRECTLY ABSENT | D-10 rule requires this link only conditionally; verdict is stay-manual so absence is correct, not a gap. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Conformance test reproduces both static gaps | `python -m pytest tests/test_utcp_conformance.py -v` | `2 passed` | ✓ PASS |
| Round-trip dry-run proves corrected shape offline | `python scripts/spike/utcp_roundtrip.py --dry-run` | Prints `McpCallTemplate` JSON with `command` string + `args` list; `OK: ... corrected shape` | ✓ PASS |
| Native-http prototype full cycle | `python scripts/spike/native_http_prototype.py --self-test` | Full start→register→call→teardown succeeded; `register_manual success=True` | ✓ PASS |
| Full-agent chat GPU-fallback probe | `python scripts/spike/full_agent_chat.py --check` | Explicit non-exercise record printed (no llama.cpp endpoint) | ✓ PASS |
| SC#3 guard: no native-serving symbols in src/ | `grep -rl "HttpCallTemplate\|utcp_http\|http_call_template" src/` | Empty, exit 1 | ✓ PASS |
| SC#3 guard: src/ untouched by phase | `git diff --stat d3fd272..HEAD -- src/` | Empty | ✓ PASS |
| SC#3 guard: compose.yaml untouched by phase | `git diff --stat d3fd272..HEAD -- compose.yaml` | Empty | ✓ PASS |
| No UTCP packages in pyproject.toml | `grep -i utcp pyproject.toml` | No output | ✓ PASS |
| No 0.0.0.0 binding in native-http prototype | `grep -n "0.0.0.0" scripts/spike/native_http_prototype.py` | No match, exit 1 | ✓ PASS |
| No debt markers in phase files | `grep -nE "TBD\|FIXME\|XXX" tests/test_utcp_conformance.py scripts/spike/*.py 02-FINDINGS.md` | No output | ✓ PASS |
| Full test suite regression | `python -m pytest -q` | `374 passed` | ✓ PASS |
| Ruff clean | `python -m ruff check tests/test_utcp_conformance.py scripts/spike` | `All checks passed!` | ✓ PASS |
| Docker Compose config valid | `docker compose config --quiet` | Exit 0 | ✓ PASS |

The Docker+GPU live round-trip (`utcp_roundtrip.py` full run, not `--dry-run`) and the native-http
prototype's `--self-test` result documented in 02-02-SUMMARY.md were not re-executed against the full
Dockerized stack in this verification session (standing up `turingdb`/`agentmemory-embed`/
`agentmemory-rerank`/`agentmemory-gliner` was out of scope for a fast verification pass); `--self-test`
for the native-http prototype WAS re-run live in this session and passed. The `--dry-run`/`--check`
halves of all three scripts were re-executed live and match the SUMMARY claims exactly, and the FINDINGS.md
evidence (specific memory ID, rerank model name, exact error messages, commit hashes) is concrete and
internally consistent rather than generic — this is treated as sufficiently corroborated, not as an
unverified claim requiring a human checkpoint, per the "reasonable spot-check" bar for a findings-only
spike phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| UTCP-01 | 02-01-PLAN.md, 02-02-PLAN.md, 02-03-PLAN.md | Early findings-gated spike on deeper UTCP support; produces a verdict, any build work gated on it | ✓ SATISFIED | `02-FINDINGS.md` verdict (stay-manual) + D-10 gating (PROJECT.md row, no ROADMAP entry) directly fulfills the requirement text. REQUIREMENTS.md line 180 marks Complete; coverage table shows 55/55 requirements mapped, 0 orphaned. |

No orphaned requirements found for Phase 2 — UTCP-01 is the only requirement mapped to this phase and it is fully accounted for.

### Anti-Patterns Found

None. Scanned `tests/test_utcp_conformance.py`, all three `scripts/spike/*.py` files, and
`02-FINDINGS.md` for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/stub-return patterns — zero
matches. Ruff clean on all phase files.

### Human Verification Required

None. All must-haves resolved to VERIFIED via direct re-execution against the live codebase (pytest
runs, script invocations, grep/git audits) — no visual, real-time, or external-service behavior
requiring human judgment in this findings-only phase.

### Gaps Summary

No gaps found. This is a findings-only spike phase; its goal was to produce a defensible,
evidence-backed verdict gating future UTCP build work — not to ship production code. All three
roadmap Success Criteria hold under independent re-verification:

1. The manual export was exercised against real UTCP client/spec pydantic serializers (not reasoned) — reproduced live in this session.
2. A written verdict (stay-manual) with rationale exists in `02-FINDINGS.md`, grounded in concrete live-round-trip evidence.
3. Zero build work was committed to `src/` or `compose.yaml` — independently re-audited via grep and git diff across the full phase commit range, matching the FINDINGS.md audit trail exactly (including the correctly-investigated `AGENTMEMORY_UTCP_SERVER_NAME` false-positive grep match).

UTCP-01 traceability is coherent, the phase's full regression gate (374 tests, ruff, compose config)
is green, and no debt markers or stub patterns were found in any file this phase touched.

---

_Verified: 2026-07-12T19:40:00Z_
_Verifier: Claude (gsd-verifier)_
