---
phase: 05-per-tenant-arcadedb-isolation
plan: 11
subsystem: database
tags: [tenant-isolation, observability, governance, arcadedb, tdd, security]

# Dependency graph
requires:
  - phase: 05-per-tenant-arcadedb-isolation
    provides: "TenantBinding.correlation() returning {tenant_database: ...}; instance-bound _StoreCore._require_user reachable-and-ordered on all 18 public methods (05-09/05-10)"
provides:
  - "tenant_binding.sanitize_tenant_attributes(attributes, binding): key-based identity stripping (top-level + nested dict values) plus opaque correlation merge"
  - "_StoreCore._span/_audit as the central sanitizing choke points every store telemetry emission passes through"
  - "6 mixin span-attribute call sites cleaned of raw user_identifier entries (defense in depth, honest call sites)"
  - "A real, previously-unenumerated audit leak fixed: store_rebuild.py's rebuild_vector_projection passed resource_id=user_identifier directly"
  - "A comprehensive full-public-surface leak-proof test (18 store methods driven against real InMemorySpanRecorder + audit sink)"
  - "Documented pseudonymous span/audit contract in docs/architecture.md Trust Boundaries + CHANGELOG.md"
affects: [05-VERIFICATION, 05-close]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Central choke-point sanitization: _span/_audit sanitize centrally so a mixin call site cannot leak tenant identity even if it still passes it; mixin cleanup is defense-in-depth honesty, not the safety net itself"
    - "In-place dict mutation preserved through sanitization: _span mutates the caller's attributes dict object in place (clear+update) rather than handing the observer a detached copy, because at least one caller mutates the dict after entering the span but before it exits (InMemorySpanRecorder reads attributes at span-exit, not span-entry)"

key-files:
  created:
    - tests/test_tenant_telemetry_pseudonymity.py
  modified:
    - src/turing_agentmemory_mcp/tenant_binding.py
    - src/turing_agentmemory_mcp/store_core.py
    - src/turing_agentmemory_mcp/store_rebuild.py
    - src/turing_agentmemory_mcp/store_memory_write.py
    - src/turing_agentmemory_mcp/store_documents.py
    - src/turing_agentmemory_mcp/store_search.py
    - tests/_store_arcadedb_core_shared.py
    - tests/test_governance.py
    - docs/architecture.md
    - CHANGELOG.md

key-decisions:
  - "sanitize_tenant_attributes is a pure function (returns a new dict) for its documented public contract, but _StoreCore._span mutates the caller's original dict object in place (clear+update with the sanitized result) to preserve store_chunking.py's document.chunk span, which mutates attributes[\"chunk_count\"] after entering the span but before it exits -- InMemorySpanRecorder only reads attributes at span-exit (yield-return), so a detached copy silently zeroed chunk_count (caught live before commit)."
  - "_audit sanitizes `details` with binding=None (strip identity keys only, no correlation re-merge) rather than passing the real binding, so tenant_database does not appear duplicated both at the event's top level and inside details."
  - "Fixed store_rebuild.py's rebuild_vector_projection audit call (resource_id=user_identifier) even though it was not among the plan's 6 enumerated span-attribute sites -- found live via this task's own full-surface leak test, in scope of ARC-07/D-07 and Task 2's own remit (\"prove no operation leaks\")."
  - "Extended tests/_store_arcadedb_core_shared.py's FakeArcadeDBClient with a minimal sqlscript() stub (records the call, no-op) so the full-surface drive test can call rebuild_communities() after other content exists in the same store -- no prior test combined committed non-Community content with a rebuild_communities() call."

patterns-established:
  - "A rejected/leaked identifier check is proven with a JSON-serialized haystack search (json.dumps(..., default=str)) across both observer.events and audit.events after asserting both are non-empty, so the check cannot be vacuously green."

requirements-completed: [ARC-07]

coverage:
  - id: D1
    description: "sanitize_tenant_attributes strips user_identifier/identifier keys (top-level and nested dict values) and merges in the opaque tenant_database correlation when bound; omits it entirely when unbound"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_telemetry_pseudonymity.py::test_sanitizer_strips_identity_keys_from_nested_attributes"
        status: pass
    human_judgment: false
  - id: D2
    description: "_StoreCore._span and _audit are the central sanitizing choke points: a bound store's span/audit events carry opaque tenant_database correlation and never a raw user_identifier; an unbound store omits tenant identity entirely"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_telemetry_pseudonymity.py::test_bound_store_emits_opaque_tenant_correlation"
        status: pass
      - kind: unit
        ref: "tests/test_tenant_telemetry_pseudonymity.py::test_unbound_store_omits_tenant_identity"
        status: pass
    human_judgment: false
  - id: D3
    description: "Audit events retain operation/resource_type/resource_id/success/details after sanitization -- audit utility survives pseudonymization"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_telemetry_pseudonymity.py::test_audit_retains_operation_and_resource_fields"
        status: pass
    human_judgment: false
  - id: D4
    description: "Driving all 18 public store methods on a bound tenant-A store produces non-empty span/audit event lists containing zero occurrences of the exact tenant identifier anywhere in serialized JSON"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_telemetry_pseudonymity.py::test_no_store_operation_emits_raw_identifier_to_spans_or_audits"
        status: pass
    human_judgment: false
  - id: D5
    description: "The 6 mixin span-attribute call sites the plan enumerated no longer pass raw user_identifier; the previously-unenumerated store_rebuild.py resource_id=user_identifier leak is also fixed"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_tenant_telemetry_pseudonymity.py::test_no_store_operation_emits_raw_identifier_to_spans_or_audits"
        status: pass
      - kind: other
        ref: "grep -c sanitize_tenant_attributes src/turing_agentmemory_mcp/store_core.py (>=3: import, _span, _audit)"
        status: pass
    human_judgment: false
  - id: D6
    description: "tests/test_governance.py's audit contract reflects the pseudonymous correlation (justified contract-change rewrite, not a weakened assertion)"
    requirement: "ARC-07"
    verification:
      - kind: unit
        ref: "tests/test_governance.py::test_store_message_applies_redaction_before_embedding_and_audits_without_content"
        status: pass
    human_judgment: false
  - id: D7
    description: "docs/architecture.md's Trust Boundaries names spans and audits among the pseudonymous channels; CHANGELOG.md documents the consumer-visible contract change"
    requirement: "ARC-07"
    verification:
      - kind: other
        ref: "grep -c tenant_database docs/architecture.md CHANGELOG.md (both >=1); grep ARC-07 CHANGELOG.md"
        status: pass
    human_judgment: false

# Metrics
duration: 15min
completed: 2026-07-16
status: complete
---

# Phase 05 Plan 11: Store Telemetry Pseudonymity (ARC-07 Gap 2) Summary

**`_StoreCore._span`/`_audit` now sanitize every attribute dict and audit event through a new `tenant_binding.sanitize_tenant_attributes` choke point, replacing raw `user_identifier` with the opaque `tenant_database` correlation (or omitting it entirely when unbound) before it reaches the shared process-wide observer or audit sink.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-16T08:47:34+02:00 (first commit)
- **Completed:** 2026-07-16T09:02:02+02:00 (last commit)
- **Tasks:** 3
- **Files modified:** 10 (1 created, 9 modified)

## Accomplishments

- `tenant_binding.py` gains `TENANT_IDENTITY_KEYS` and `sanitize_tenant_attributes(attributes, binding)`: strips any top-level or nested-dict key whose lowercase form is `user_identifier`/`identifier`, then merges in `binding.correlation()` (the opaque `tenant_database` name) when bound.
- `_StoreCore._span` sanitizes centrally and mutates the caller's original attributes dict object in place (not a detached copy) -- required because `store_chunking.py`'s `_chunk_document_text` mutates `attributes["chunk_count"]` after entering the span but before it exits, and `InMemorySpanRecorder` only reads `attributes` at span-exit. A detached copy silently zeroed `chunk_count`; caught live by `tests/test_observability.py` before the fix landed.
- `_StoreCore._audit` no longer forwards the raw `user_identifier`; it merges the opaque correlation at the event's top level when bound and sanitizes `details` (identity-strip only, no duplicate correlation merge) so a caller-supplied `details` dict cannot smuggle identity through.
- Found and fixed a real leak outside the plan's 6 enumerated span-attribute sites: `store_rebuild.py`'s `rebuild_vector_projection` passed `resource_id=user_identifier` directly into its audit call. Caught live by this task's own comprehensive full-surface leak test, not by the plan's line-number enumeration.
- Removed the raw `"user_identifier": user_identifier` entries from the 6 mixin span-attribute dicts the plan named (`store_message`/`store_messages`, `ingest_document_text`/`reindex_document_text`/`search_documents`, `search_memory`) -- defense in depth and honest call sites, since the central choke point was already the real backstop.
- New `tests/test_tenant_telemetry_pseudonymity.py` (5 tests): sanitizer unit test, bound/unbound `_span`/`_audit` behavior, audit-field-retention, and a comprehensive drive of all 18 public store methods against real `InMemorySpanRecorder`/audit-sink recorders proving zero raw-identifier leakage anywhere in the serialized JSON.
- Rewrote `tests/test_governance.py`'s stale `audit.events[-1]["user_identifier"] == "alice"` assertion (justified contract-change rewrite per CLAUDE.md, not a weakened assertion) to assert the identity key is absent.
- Documented the pseudonymous telemetry contract in `docs/architecture.md`'s Trust Boundaries and Canonical Store and Retrieval sections, and added the `ARC-07`/consumer-visible-change entry to `CHANGELOG.md`.

## Task Commits

Each task was committed atomically (TDD RED then GREEN, then a refactor commit for Task 2's honesty cleanup):

1. **Task 1: Central span and audit sanitization** - `cde5a28` (test, RED: 4/5 new tests fail against the unmodified `_span`/`_audit`) then `f3f4eba` (feat, GREEN: `sanitize_tenant_attributes` + sanitizing choke points + the `store_rebuild.py` resource_id fix + the in-place-mutation fix for `document.chunk`)
2. **Task 2: Remove raw identity from mixins and prove no operation leaks** - `3b520d8` (refactor: 6 mixin call sites cleaned + `tests/test_governance.py`'s stale assertion rewritten; the new full-surface leak test was written and committed alongside Task 1's GREEN commit since it was needed to discover the `store_rebuild.py` leak in the first place)
3. **Task 3: Document the pseudonymous telemetry contract** - `74710e4` (docs: `docs/architecture.md` + `CHANGELOG.md`)

## Files Created/Modified

- `tests/test_tenant_telemetry_pseudonymity.py` - new: sanitizer unit test, bound/unbound `_span`/`_audit` tests, audit-field-retention test, and the 18-method full-surface leak-proof test
- `src/turing_agentmemory_mcp/tenant_binding.py` - `TENANT_IDENTITY_KEYS` + `sanitize_tenant_attributes(attributes, binding)`
- `src/turing_agentmemory_mcp/store_core.py` - `_span`/`_audit` sanitizing choke points
- `src/turing_agentmemory_mcp/store_rebuild.py` - `rebuild_vector_projection`'s audit `resource_id` no longer echoes the raw identifier
- `src/turing_agentmemory_mcp/store_memory_write.py` - raw `user_identifier` removed from `store_message`/`store_messages` span attributes
- `src/turing_agentmemory_mcp/store_documents.py` - raw `user_identifier` removed from `ingest_document_text`/`reindex_document_text`/`search_documents` span attributes
- `src/turing_agentmemory_mcp/store_search.py` - raw `user_identifier` removed from `search_memory` span attributes
- `tests/_store_arcadedb_core_shared.py` - `FakeArcadeDBClient.sqlscript()` stub added (needed for the full-surface test's `rebuild_communities()` call after other content exists)
- `tests/test_governance.py` - stale raw-identity audit assertion rewritten to assert absence
- `docs/architecture.md` - Trust Boundaries + Canonical Store and Retrieval updated
- `CHANGELOG.md` - `ARC-07` telemetry-contract entry added

## Decisions Made

- `sanitize_tenant_attributes` stays a pure function (new dict) for its documented public contract, but `_span` mutates the caller's original dict object in place to preserve `store_chunking.py`'s post-yield mutation pattern -- see the D-07/`document.chunk` regression caught and fixed before committing GREEN.
- `_audit` sanitizes `details` with `binding=None` (strip-only) rather than the real binding, so `tenant_database` is not duplicated inside `details` in addition to the event's top level.
- Fixed `store_rebuild.py`'s `resource_id=user_identifier` leak even though it fell outside the plan's 6 enumerated sites, because it is squarely within ARC-07/D-07 scope and Task 2's own title ("prove no operation leaks").
- Extended the shared `FakeArcadeDBClient` test fixture with a minimal `sqlscript()` stub rather than reordering the full-surface test to avoid calling `rebuild_communities()` after other content exists -- the stub is a faithful (if simplified) analog of the real client's self-contained `sqlscript` semantics and unblocks any future test that needs the same combination.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_span`'s new sanitizer broke `document.chunk`'s post-yield attribute mutation**
- **Found during:** Task 1 verification (`tests/test_observability.py`)
- **Issue:** The initial `_span` implementation passed `sanitize_tenant_attributes(attributes, self.tenant_binding)` -- a freshly built dict -- to `self.observer.span(...)`. `store_chunking.py`'s `_chunk_document_text` keeps its own reference to the `attributes` dict and mutates `attributes["chunk_count"] = len(chunks)` after entering the span but before it exits; `InMemorySpanRecorder` only reads `attributes` at span-exit (yield-return), so it must be the SAME object the caller mutates. The detached copy silently recorded `chunk_count: 0`.
- **Fix:** `_span` now mutates `payload` (the caller's dict, or a fresh `{}` if `None`) in place via `payload.clear(); payload.update(sanitized)`, preserving object identity while still sanitizing.
- **Files modified:** `src/turing_agentmemory_mcp/store_core.py`
- **Verification:** `python -m pytest tests/test_observability.py -q` -- 14 passed (was 1 failed before the fix)
- **Committed in:** `f3f4eba` (Task 1 GREEN commit)

**2. [Rule 1 - Bug] `store_rebuild.py`'s `rebuild_vector_projection` leaked the raw identifier via `resource_id`**
- **Found during:** Task 1/2 (writing the full-surface leak test)
- **Issue:** `rebuild_vector_projection`'s `self._audit(...)` call passed `resource_id=user_identifier` directly -- a genuine ARC-07/D-07 violation the plan's 6-site enumeration did not name (it is an audit call, not a span attribute dict).
- **Fix:** `resource_id` is now `""` (no single sub-resource exists for a tenant-wide rebuild; the opaque `tenant_database` correlation `_audit` adds already identifies the tenant).
- **Files modified:** `src/turing_agentmemory_mcp/store_rebuild.py`
- **Verification:** `tests/test_tenant_telemetry_pseudonymity.py::test_no_store_operation_emits_raw_identifier_to_spans_or_audits` passes; full suite green (825 passed, 1 skipped)
- **Committed in:** `f3f4eba` (Task 1 GREEN commit)

**3. [Rule 3 - Blocking] `FakeArcadeDBClient` had no `sqlscript()` method**
- **Found during:** writing the full-surface leak test (Task 1/2)
- **Issue:** Driving `rebuild_communities()` after other content (memories, entities, facts, documents) already existed on the same store caused `store_rebuild.py::_replace_community_graph` to reach `self.client.sqlscript(...)`, which `tests/_store_arcadedb_core_shared.py`'s `FakeArcadeDBClient` never implemented -- no prior test had combined committed non-Community content with a `rebuild_communities()` call, so the gap was never exercised.
- **Fix:** Added a minimal `sqlscript()` stub (records the call, no-op) to `FakeArcadeDBClient`.
- **Files modified:** `tests/_store_arcadedb_core_shared.py`
- **Verification:** `tests/test_tenant_telemetry_pseudonymity.py -q` passes; no other test's behavior changed (the method was previously unreachable, so adding it is purely additive)
- **Committed in:** `cde5a28` (Task 1 RED commit, alongside the new test file)

---

**Total deviations:** 3 auto-fixed (2 real telemetry bugs found live via the new comprehensive test, 1 test-fixture gap)
**Impact on plan:** All three are corrections essential to ARC-07 correctness or to writing the plan's own required test; no scope creep beyond the plan's stated objective (closing verifier gap 2).

## Issues Encountered

None beyond the three documented deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ARC-07 verifier gap 2 (BLOCKER) is closed: `_span`/`_audit` are proven sanitizing choke points, the full public store surface is proven leak-free by a comprehensive test that also caught a real, previously-unenumerated leak, and the documented Trust Boundaries contract now matches the code.
- Full repository test suite (825 passed, 1 skipped), `ruff check`, `scripts/check-file-size.sh`, and `docker compose config --quiet` all green after this plan.
- The one pre-existing test intentionally changed (`tests/test_governance.py`'s raw-identity assertion) is the plan's own documented, justified contract-change exception -- no other assertion was weakened.

---
*Phase: 05-per-tenant-arcadedb-isolation*
*Completed: 2026-07-16*

## Self-Check: PASSED

All 11 created/modified files verified present on disk; all 4 commit hashes
(`cde5a28`, `f3f4eba`, `3b520d8`, `74710e4`) verified present in
`git log --oneline --all`.
