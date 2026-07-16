---
phase: 05-per-tenant-arcadedb-isolation
plan: 12
subsystem: testing
tags: [tenant-isolation, observability, governance, arcadedb, telemetry, security]

# Dependency graph
requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: "_StoreCore._span/_audit as sanitizing choke points; sanitize_tenant_attributes key-based identity stripping (05-11)"
provides:
  - "_RecordingAuditSink: thread-safe audit sink exposing captured events for live-harness inspection"
  - "live_environment_context wires a shared InMemorySpanRecorder + _RecordingAuditSink into the assembly store via observer=/audit_sink=, replacing NoopAuditSink()"
  - "_PhysicalIsolationProof.span_event_count/audit_event_count/telemetry_text fields; telemetry_text folded into diagnostic_text"
  - "Live assertions in test_arcadedb_physical_tenant_isolation.py proving zero exact-identifier leakage in real span/audit events, with anti-vacuity non-zero-count guards and an opaque-correlation presence check"
  - "Locally verified (not committed) mutation proof: reverting 05-11's store_rebuild.py resource_id fix makes the live gate genuinely fail"
  - "Full green Definition-of-Done gate: pytest (825 passed, 1 skipped), ruff, docker compose config, file-size cap, e2e_score.py (19/19, score 10.0, VALIDATED_10_10)"
affects: [05-VERIFICATION, 06-parity-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Telemetry-aware live leakage harness: the recorder pair (span + audit) that a store already emits into is captured and folded into the same diagnostic_text scan that already covered caplog/errors/reprs/status/manifests, so an assertion surface cannot silently stop observing a channel it claims to cover"
    - "Anti-vacuity guard: assert non-zero event counts before asserting absence of an identifier, so a harness that silently stopped recording cannot pass the absence check trivially"

key-files:
  created: []
  modified:
    - tests/_arcadedb_physical_isolation_support.py
    - tests/test_arcadedb_physical_tenant_isolation.py

key-decisions:
  - "Plan frontmatter named the test file tests/test_arcadedb_physical_isolation.py; the actual, pre-existing file (created in 05-08) is tests/test_arcadedb_physical_tenant_isolation.py. Edited the real file rather than creating a duplicate -- no file was renamed or added."
  - "telemetry_text serializes {\"spans\": [...], \"audits\": [...]} via json.dumps(..., ensure_ascii=False, sort_keys=True, default=str) and is folded into diagnostic_text (not asserted as a wholly separate surface), so the existing per-identifier diagnostic_text scan automatically covers it -- this is also what made the mutation-check assertion fail at the pre-existing diagnostic_text line rather than only at the new telemetry-specific assertion."
  - "Mutation-check target: store_rebuild.py's rebuild_vector_projection resource_id fix (05-11), not one of the 6 mixin span-attribute call sites. The 6 mixin sites are key-named (user_identifier=...) and are already caught by _StoreCore._span's central key-based sanitize_tenant_attributes even if reverted (05-11's own documented decision: mixin cleanup is defense-in-depth honesty, not the safety net). The store_rebuild.py leak is different in kind: resource_id is a positional _audit() argument written directly into the audit event dict, never passed through sanitize_tenant_attributes, so it is the one 05-11 fix whose reversion this harness can actually observe failing live. Verified locally by reverting the fix plus a temporary one-line rebuild_vector_projection() call in the workload, confirming a genuine test failure, then fully restoring both files before committing Task 2 (git diff confirmed clean)."
  - "E2E gate run via the documented 'Windows retained-dependency shim': turingdb==1.35 is a legacy dependency scripts/e2e_score.py imports only for a version string (pip install turingdb==1.35 fails -- no distribution exists for this platform, consistent with 05-07/05-08/05-09-SUMMARY.md's identical finding). Stubbed sys.modules['turingdb'] with a SimpleNamespace before running the script, mirroring the same pattern already used at the top of ~47 test files in this repo. No pyproject.toml or product code changed to work around this -- it is a local-environment limitation, not a product change."

patterns-established:
  - "A live leakage scan is only as good as what it captures: this plan's whole purpose was closing the specific gap where an assertion surface (diagnostic_text) existed but the channel that actually leaked (span/audit events) was never wired into it."

requirements-completed: [ARC-07, TEST-05]

coverage:
  - id: D1
    description: "The live isolation harness captures real span-recorder events and a real (non-noop) audit sink via a shared InMemorySpanRecorder + _RecordingAuditSink wired into the assembly store's observer=/audit_sink="
    requirement: "ARC-07"
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_physical_tenant_isolation.py::test_physical_three_tenant_database_and_predicate_isolation (proof.span_event_count > 0, proof.audit_event_count > 0)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The live leakage scan fails if any exact tenant identifier (including the case-variant and Cyrillic lookalike) appears in captured span or audit events"
    requirement: "TEST-05"
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_physical_tenant_isolation.py::test_physical_three_tenant_database_and_predicate_isolation (per-_IDENTITY_VARIANTS absence assertion over telemetry_text and diagnostic_text)"
        status: pass
      - kind: other
        ref: "Local mutation check: reverting store_rebuild.py's resource_id=\"\" fix (05-11) to resource_id=user_identifier makes the test fail on the diagnostic_text assertion with the leaked identifier visible in the serialized audit event -- verified live, then fully restored (git diff clean) before commit"
        status: pass
    human_judgment: false
  - id: D3
    description: "Live concurrent A/B/C isolation, foreign-ID denial, and lifecycle behavior still pass with binding enforcement and telemetry sanitization in place"
    requirement: "TEST-05"
    verification:
      - kind: integration
        ref: "tests/test_arcadedb_physical_tenant_isolation.py::test_physical_three_tenant_database_and_predicate_isolation"
        status: pass
      - kind: integration
        ref: "tests/test_arcadedb_physical_tenant_isolation.py::test_lifecycle_chaos_preserves_tenant_binding_and_durable_data"
        status: pass
    human_judgment: false
  - id: D4
    description: "The phase closes green on the full project Definition-of-Done gate: pytest, ruff, compose validation, file-size cap, and the deterministic E2E score threshold"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "python -m pytest -q (825 passed, 1 skipped)"
        status: pass
      - kind: other
        ref: "python -m ruff check src tests scripts"
        status: pass
      - kind: other
        ref: "docker compose config --quiet"
        status: pass
      - kind: other
        ref: "bash scripts/check-file-size.sh"
        status: pass
      - kind: e2e
        ref: "python scripts/e2e_score.py --out e2e-results.json (Windows retained-dependency shim) -- 19/19 checks, score 10.0, VALIDATED_10_10"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-16
status: complete
---

# Phase 05 Plan 12: Live Telemetry Leakage Closure (ARC-07 Gap 2) Summary

**The live isolation harness now captures real span-recorder and audit-sink events through a shared `InMemorySpanRecorder`/`_RecordingAuditSink` pair, folds them into the existing diagnostic scan, and asserts zero exact-identifier leakage — closing the assertion-surface blind spot that let ARC-07's telemetry gap ship, with the full project gate green (pytest 825/1-skip, ruff, compose, file-size, E2E 10/10 VALIDATED_10_10).**

## Performance

- **Duration:** 20 min
- **Started:** 2026-07-16T09:04:46+02:00 (prior plan's final commit)
- **Completed:** 2026-07-16T09:24:00+02:00 (approx, after Task 3 gate verification)
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Added `_RecordingAuditSink` to `tests/_arcadedb_physical_isolation_support.py`: a thread-safe sink (lock-guarded `record`, mirroring `JsonlAuditSink`) exposing captured `events`.
- `live_environment_context` now constructs one `InMemorySpanRecorder()` and one `_RecordingAuditSink()` and passes them to the assembly `TuringAgentMemory` as `observer=`/`audit_sink=`, replacing `NoopAuditSink()`. Because `shared_dependencies()` propagates both across every routed tenant store, all three concurrent tenants' telemetry now lands in one observable pair. Removed the now-unused `NoopAuditSink` import.
- Added `observer`/`audit_sink` fields to `_LiveEnvironment` and `span_event_count`/`audit_event_count`/`telemetry_text` to `_PhysicalIsolationProof`.
- `_run_physical_isolation_contract` snapshots both recorders after the workload and adversarial sections, serializes them (`json.dumps(..., ensure_ascii=False, sort_keys=True, default=str)`), and folds `telemetry_text` into the existing `diagnostic_text` join alongside `caplog.text`, error strings, view reprs, router status, and manifests.
- Extended `test_physical_three_tenant_database_and_predicate_isolation` with anti-vacuity guards (`span_event_count > 0`, `audit_event_count > 0`) before per-`_IDENTITY_VARIANTS` absence assertions over `telemetry_text`, plus a presence assertion that at least one opaque `expected_databases` name survives in telemetry — proving correlation is retained, not merely stripped to nothing.
- Locally proved the harness genuinely observes the channel it previously missed: reverted 05-11's `store_rebuild.py` `resource_id=""` fix back to `resource_id=user_identifier` (the one 05-11 fix that is a positional `_audit()` argument written straight into the audit event, never passed through the key-based `sanitize_tenant_attributes` choke point) plus a temporary one-line `rebuild_vector_projection()` call in the workload, ran the live test, and it failed on the pre-existing `diagnostic_text` assertion with the leaked `Tenant-A`/`Tenant-C` identifiers visible in the serialized audit events. Fully restored both files afterward; `git diff` confirmed clean before the Task 2 commit.
- Ran the full Definition-of-Done gate: `pytest -q` (825 passed, 1 skipped — matches the pre-change baseline exactly, zero new skips), `ruff check` clean, `docker compose config --quiet` clean, `scripts/check-file-size.sh` clean (harness file at 543/600 LOC), and `scripts/e2e_score.py --out e2e-results.json` at 19/19 checks, score 10.0, `VALIDATED_10_10`.

## Task Commits

1. **Task 1: Capture real span and audit events in the live leakage harness** - `8cb9f61` (feat)
2. **Task 2: Assert live telemetry pseudonymity** - `2cd6558` (test)
3. **Task 3: Close the phase on the full Definition-of-Done gate** - no code changes required (all gates green as-is); verification evidence recorded below and in this SUMMARY's coverage block.

## Files Created/Modified

- `tests/_arcadedb_physical_isolation_support.py` - `_RecordingAuditSink`, `_LiveEnvironment.observer`/`.audit_sink`, `_PhysicalIsolationProof.span_event_count`/`.audit_event_count`/`.telemetry_text`, telemetry capture in `_run_physical_isolation_contract`; 508 -> 543 LOC (92 -> 57 lines free under the 600 cap)
- `tests/test_arcadedb_physical_tenant_isolation.py` - anti-vacuity count guards + per-identifier telemetry absence/opaque-correlation presence assertions in `test_physical_three_tenant_database_and_predicate_isolation`

## Decisions Made

- Edited the actual pre-existing test file (`tests/test_arcadedb_physical_tenant_isolation.py`, created in 05-08) rather than the plan frontmatter's `tests/test_arcadedb_physical_isolation.py` name — no such file exists; this is the correct, already-established harness the plan's `<interfaces>` describes verbatim.
- `telemetry_text` is folded into the existing `diagnostic_text` scan rather than kept as a fully separate assertion surface, so the pre-existing per-identifier `diagnostic_text` check automatically covers it. This is also why the mutation-check failure surfaced at the original `diagnostic_text` assertion line, not only at the new telemetry-specific one — confirming the two scans are genuinely unified, not duplicated.
- Chose `store_rebuild.py`'s `resource_id` fix as the mutation-check target instead of one of the 6 mixin span-attribute sites, because the mixin sites are key-named and already caught by `_StoreCore._span`'s central `sanitize_tenant_attributes` even when reverted (05-11's own documented decision). `resource_id` is a positional `_audit()` argument that goes directly into the audit event dict unsanitized by design (it's meant to hold a resource identifier, not raw tenant identity), so it is the one 05-11 fix this harness's audit-capture can actually prove itself against.
- Ran `scripts/e2e_score.py` via the same `sys.modules['turingdb']` stub pattern already used in ~47 test files in this repo (documented in 05-07/05-08/05-09-SUMMARY.md as the "Windows retained-dependency shim"), since `turingdb==1.35` has no distribution available for this platform (`pip install turingdb==1.35` returns "No matching distribution found"). No repository or dependency-pin state was changed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan frontmatter named a test file that does not exist**
- **Found during:** Task 1 read_first
- **Issue:** Plan frontmatter/`<interfaces>` reference `tests/test_arcadedb_physical_isolation.py`; the actual file created in 05-08 is `tests/test_arcadedb_physical_tenant_isolation.py`.
- **Fix:** Edited the real, pre-existing file. No file was created or renamed.
- **Files modified:** `tests/test_arcadedb_physical_tenant_isolation.py`
- **Verification:** `python -m pytest tests/test_arcadedb_physical_tenant_isolation.py -q` — 2 passed
- **Committed in:** `2cd6558` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 stale plan reference, no code/behavior impact)
**Impact on plan:** Purely a file-path correction; no scope creep, no weakened assertions.

## Issues Encountered

- `turingdb==1.35` (declared in `pyproject.toml`, imported by `scripts/e2e_score.py` only for a version-string metadata field) is not installable on this Windows machine (`pip install turingdb==1.35` -> "No matching distribution found for turingdb==1.35 (from versions: none)"). This is a pre-existing, previously documented environment limitation (identical finding recorded in 05-07/05-08/05-09-SUMMARY.md), not introduced by this plan. Ran `scripts/e2e_score.py` via the established local `sys.modules['turingdb']` stub workaround (the same pattern used at the top of ~47 test files in this repo) to produce real evidence rather than skipping the gate. No product code or dependency pin was changed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both verifier gaps from `05-VERIFICATION.md` are now closed across plans 05-09 through 05-12: ARC-07 gap 1 (binding enforcement/reachability, 05-09/05-10) and ARC-07 gap 2 (pseudonymous telemetry, both the sanitization mechanism in 05-11 and the harness's ability to observe that mechanism in this plan).
- The live physical-isolation and lifecycle-chaos tests, the full pytest suite, ruff, compose validation, the file-size cap, and the deterministic E2E score gate are all green with real evidence captured in this SUMMARY's `coverage:` block.
- Phase 05 (per-tenant-arcadedb-isolation) is ready to close; `06-parity-gate` can proceed on the assumption that tenant isolation, binding enforcement, and telemetry pseudonymity are all proven live, not just unit-tested.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-16*

## Self-Check: PASSED

Both modified files (`tests/_arcadedb_physical_isolation_support.py`,
`tests/test_arcadedb_physical_tenant_isolation.py`) and this SUMMARY.md
verified present on disk; both task commit hashes (`8cb9f61`, `2cd6558`)
verified present in `git log --oneline --all`.
