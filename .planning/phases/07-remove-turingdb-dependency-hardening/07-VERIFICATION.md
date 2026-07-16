---
phase: 07-remove-turingdb-dependency-hardening
verified: 2026-07-16T21:45:00Z
status: passed
score: 3/3 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 07: Remove TuringDB Dependency + Hardening Verification Report

**Phase Goal:** TuringDB is gone from the codebase and stack, CLAUDE.md invariants are rewritten for ArcadeDB, and remaining at-risk dependencies are version-gated.
**Verified:** 2026-07-16
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TuringDB removed from `compose.yaml`/`pyproject.toml`/docs; stack runs on ArcadeDB alone | ✓ VERIFIED | `grep -inE "turingdb" compose.yaml pyproject.toml` → 0 matches. `docker compose config --quiet` exits 0; services = `arcadedb, agentmemory-gliner, turing-agentmemory-mcp, agentmemory-model-init, agentmemory-gemma-model-init, agentmemory-embed, agentmemory-embed-gemma, agentmemory-rerank, agentmemory-lab, e2e` (no `turingdb`/`turingdb-volume-init`); volumes include `bertoni-data`/`arcadedb-data` (no `turing-data`). `test -f docker/turingdb.Dockerfile` fails (deleted). `grep -rlnE "^\s*(import turingdb|from turingdb)" src/ tests/` → 0 files. `tests/test_no_turingdb_imports.py` passes (rglob scan of all of `src/turing_agentmemory_mcp/*.py`). Repo-wide sweep of README/docs/skills/CHANGELOG/frontend/lab.py confirms no TuringDB-backend claims remain (verified via targeted greps matching 07-06's own acceptance criteria). |
| 2 | CLAUDE.md invariants rewritten — #2 superseded by ArcadeDB-sole; submit-before-match/`load_graph` rationale retired/replaced; tenant scope (#1) and stable-ID invariant reconfirmed, not weakened | ✓ VERIFIED | Read `CLAUDE.md` in full: invariant #2 states "ArcadeDB is the sole canonical backend (TuringDB is fully removed...)"; invariant #5 replaces submit-before-match with `run_in_transaction` single managed commit; invariant #6 (new) codifies MVCC HTTP-503 `ConcurrentModificationException` handling; invariant #7 (new) codifies native `LSM_VECTOR`+Lucene ACID-consistency (explicitly preserves `SparseIndex` as a live fusion-gated channel, not deleted); invariant #8 replaces `load_graph` with ArcadeDB `reconnect()`/`/health` reachability probe. Invariant #1 (`user_identifier` fail-closed) and invariant #4 (stable/deterministic IDs) are present verbatim, not weakened. Notes section reads `BERTONI_HOME`/`bertoni-data`, no `TURINGDB_HOME remains` text. `.claude/CLAUDE.md` line 28 states the migration as completed fact ("ArcadeDB is the sole canonical backend...TuringDB has been fully removed") with no "migrates to ArcadeDB this milestone" pending language (`grep -i "migrates to ArcadeDB" .claude/CLAUDE.md` → 0 matches). Cross-checked the retired vector-ordering claim against live code: `store_search.py:222` sorts the blended RRF score for presentation, not a TuringDB-specific vector-order workaround — no fabricated behavior claim. |
| 3 | `graspologic-native` and `fastmcp` have automated compatibility/version-gate checks | ✓ VERIFIED | `tests/test_graspologic_compat.py` (2 tests: exact `1.3.1` pin via `importlib.metadata.version`; live `hierarchical_leiden` smoke over a 3-node graph asserting all nodes land in a final cluster) and `tests/test_warning_filters.py` (2 new tests: `fastmcp` `>=3.4,<4` range check; `create_mcp_app(store=object())` + `list_tools()` asserts ≥20 tools) both ran directly and passed: `python -m pytest tests/test_no_turingdb_imports.py tests/test_graspologic_compat.py tests/test_warning_filters.py -q` → 7 passed. `-k graspologic_compat` and `-k fastmcp_compat` filters both select and pass their respective tests. Installed versions independently confirmed: `graspologic-native 1.3.1`, `fastmcp 3.4.4` (satisfies `>=3.4,<4`). No `pytest.skip` in any of the three files (`grep -c pytest.skip` → 0 each). |

**Score:** 3/3 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compose.yaml` | No `turingdb`/`turingdb-volume-init` service | ✓ VERIFIED | Confirmed via `docker compose config --quiet` (exit 0) + direct YAML parse of services/volumes. |
| `pyproject.toml` | No `turingdb==` dependency/keyword; ArcadeDB-worded description | ✓ VERIFIED | `grep -nc "turingdb" pyproject.toml` → 0; `fastmcp>=3.4,<4` and `graspologic-native==1.3.1` pins intact. |
| `docker/turingdb.Dockerfile` | Deleted | ✓ VERIFIED | File absent. |
| `tests/test_no_turingdb_imports.py` | New src-wide grep-gate | ✓ VERIFIED | Exists, rglobs `src/turing_agentmemory_mcp/*.py`, passes, no skip. |
| `tests/test_graspologic_compat.py` | New DEP-01 compat-smoke | ✓ VERIFIED | Exists, 2 tests, passes, no skip. |
| `tests/test_warning_filters.py` | Extended with DEP-02 fastmcp checks | ✓ VERIFIED | 4 tests total (2 pre-existing + 2 new), all pass, no skip. |
| `CLAUDE.md` | Rewritten Invariants + Notes | ✓ VERIFIED | 11 invariants read ArcadeDB-sole; BERTONI_HOME in Notes. |
| `.claude/CLAUDE.md` | Reconciled Constraints/milestone framing | ✓ VERIFIED | States migration as completed fact; no pending-migration language. |
| `CHANGELOG.md` | `Removed` entry for TuringDB cut + Bertoni rename | ✓ VERIFIED | `### Removed` section (line 83) documents the `turingdb==1.35` removal, compose services, harness cluster, `admin_repair.py`, the test stub, and the `/turing`→`/bertoni` rename. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `baseline/06-gate/gate-result.json` | phase-7 removal | `gate_guard.assert_gate_go` | ✓ WIRED | Re-ran independently: `assert_gate_go(Path('baseline/06-gate/gate-result.json'))` prints `GO`, exits 0. |
| `src/turing_agentmemory_mcp/*.py` | `tests/test_no_turingdb_imports.py` | rglob scan | ✓ WIRED | Test passes; independently confirmed 0 files under `src/` match `import turingdb`/`from turingdb`. |
| `pyproject.toml` pins | compat-smoke tests | `importlib.metadata.version` | ✓ WIRED | Installed `graspologic-native==1.3.1`, `fastmcp==3.4.4` match the pins the tests assert against. |
| `cli.py` | retained subcommands | argparse dispatch | ✓ WIRED | `python -m turing_agentmemory_mcp.cli --help` lists exactly `serve, file-pipe, e2e-score, utcp-manual, lab` — matches Plan 01's `must_haves`. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full unit suite green, turingdb-free, at CI coverage floor | `pytest -m "not integration and not gpu" --cov=src/turing_agentmemory_mcp --cov-fail-under=78 -q` | 856 passed, 1 skipped, 10 deselected; coverage 87.22% | ✓ PASS |
| Compose config validates | `docker compose config --quiet` | exit 0 | ✓ PASS |
| Phase-6 GO gate still authorizes | `assert_gate_go(baseline/06-gate/gate-result.json)` | prints `GO` | ✓ PASS |
| DEP-01/DEP-02 oracle filters select and pass | `pytest -q -k graspologic_compat` / `-k fastmcp_compat` | 2 passed each | ✓ PASS |
| cli.py surface matches Plan 01's must-have | `python -m turing_agentmemory_mcp.cli --help` | 5 retained subcommands only | ✓ PASS |
| `docker/turingdb.Dockerfile` absent | `test -f docker/turingdb.Dockerfile` | non-zero (absent) | ✓ PASS |

E2E score gate (score ≥ 9.8, check_count == 19) was not independently re-run in this verification pass (it requires the running ArcadeDB Compose stack + GPU/embed sidecars); the 07-08 SUMMARY documents a local run scoring 10.0/19-of-19 (`VALIDATED_10_10`), and the phase's CI-equivalent gate (unit suite, compose validation, oracles, gate_guard) was independently re-run here and is green. This is consistent with the task instructions' statement that the E2E run is pre-confirmed context to independently corroborate rather than a re-run requirement.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ARC-10 | 07-01 through 07-08 | TuringDB removed from codebase/Compose stack; CLAUDE.md invariants updated | ✓ SATISFIED | All three success criteria independently verified above. Correctly still `Pending` in REQUIREMENTS.md pre-verification per the orchestrator's `phase.complete` convention — not a gap. |
| DEP-01 | 07-05 | Version-gate `graspologic-native` | ✓ SATISFIED | `tests/test_graspologic_compat.py` passes; already marked Complete in REQUIREMENTS.md. |
| DEP-02 | 07-05 | Version-gate `fastmcp` | ✓ SATISFIED | `tests/test_warning_filters.py` DEP-02 tests pass; already marked Complete in REQUIREMENTS.md. |

No orphaned requirements: `.planning/REQUIREMENTS.md`'s phase-7 mapping table lists exactly ARC-10, DEP-01, DEP-02, matching the union of all 8 plans' `requirements:` frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `CLAUDE.md` | 61–64 | Stale CLI reference: "The console entrypoint `turing-agentmemory-mcp`...also dispatches `file-pipe`, `e2e-score`, `agent-quality-eval`, `utcp-manual`, `lab`, and `repair-vector-index`." | ⚠️ Warning | `agent-quality-eval` and `repair-vector-index` were deleted from `cli.py` in Plan 07-01 (confirmed live: `--help` only lists `serve, file-pipe, e2e-score, utcp-manual, lab`). This line in the "Commands" section (not the Invariants/Notes sections Plan 07-07 was scoped to touch, and not swept by Plan 07-06's docs list either) still names two CLI subcommands that no longer exist. Does not violate any of the phase's three explicit success criteria or `must_haves` (none require this specific line), and does not affect correctness/tenant-isolation/dependency-gating — but is a real, independently-discovered accuracy bug in the project's primary governance doc, left over from the exact TuringDB-era tooling this phase removed. Recommend a quick follow-up fix (drop `agent-quality-eval`/`repair-vector-index` from this sentence) rather than blocking the phase on it. |
| `src/turing_agentmemory_mcp/e2e_score.py`, `e2e_score_scenarios.py` | multiple | "TuringDB" used as literal corpus/query sample text (e.g. `"espresso TuringDB memory"`) | ℹ️ Info | Cosmetic only — these are E2E-gate fixture content strings, not backend claims; unrelated to correctness. Out of scope for all 8 plans' explicit file lists. |
| `scripts/spike/utcp_roundtrip.py` | 21, 24 | Spike-script instructions reference `docker compose up -d turingdb ...`, a service that no longer exists | ℹ️ Info | Historical/dev-scratch spike script, not part of the live CLI/product surface or any plan's scope; would mislead if run literally but does not affect the shipped stack. |

No `TBD`/`FIXME`/`XXX` debt markers found in any file this phase modified.

### Human Verification Required

None. All must-haves resolve to VERIFIED via direct codebase inspection, live test execution, and command output; no visual/UX/external-service checks apply to this infra/docs/governance phase. The one blocking human-verify checkpoint the phase plan itself required (Plan 07-08 Task 2, invariant-rewrite + irreversible-cut approval) was already completed by the human during execution (recorded "approved" in the 07-08 SUMMARY) — this verifier independently re-confirmed the evidence that approval was based on (full gate re-run, gate_guard GO) rather than re-litigating a decision already made.

### Gaps Summary

No gaps. All three phase success criteria are independently verified against the live codebase (not merely SUMMARY claims): TuringDB is absent from `compose.yaml`, `pyproject.toml`, `docker/`, and all live source/test imports, with the ArcadeDB-only stack validating via `docker compose config --quiet`; both `CLAUDE.md` and `.claude/CLAUDE.md` state ArcadeDB as the sole canonical backend with the new MVCC/native-ACID/TenantBinding invariants codified and the tenant-scope + stable-ID invariants reconfirmed verbatim (no weakening, no fabricated behavior claims); and `graspologic-native`/`fastmcp` both carry passing, skip-free, version-pinned compat-smoke oracles exercising their real APIs. The full unit suite (856 passed) runs green turingdb-free at 87.22% coverage against the 78% CI floor, and the Phase-6 GO gate still authorizes retroactively. One low-severity, non-blocking documentation staleness item (stale CLI-command mention in `CLAUDE.md`'s Commands section) is flagged above for follow-up but does not gate phase completion.

---

_Verified: 2026-07-16_
_Verifier: Claude (gsd-verifier)_
