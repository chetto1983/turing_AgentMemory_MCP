---
phase: 05-per-tenant-arcadedb-isolation
reviewed: 2026-07-15T13:59:58Z
depth: standard
files_reviewed: 39
files_reviewed_list:
  - docs/architecture.md
  - docs/configuration.md
  - scripts/check-file-size.sh
  - src/turing_agentmemory_mcp/arcadedb_client.py
  - src/turing_agentmemory_mcp/arcadedb_schema.py
  - src/turing_agentmemory_mcp/document_job_manager.py
  - src/turing_agentmemory_mcp/document_jobs.py
  - src/turing_agentmemory_mcp/file_upload.py
  - src/turing_agentmemory_mcp/server.py
  - src/turing_agentmemory_mcp/server_document_tools.py
  - src/turing_agentmemory_mcp/server_memory_tools.py
  - src/turing_agentmemory_mcp/store_core.py
  - src/turing_agentmemory_mcp/store_documents.py
  - src/turing_agentmemory_mcp/store_documents_queries.py
  - src/turing_agentmemory_mcp/store_memory_queries.py
  - src/turing_agentmemory_mcp/store_memory_write.py
  - src/turing_agentmemory_mcp/store_rebuild.py
  - src/turing_agentmemory_mcp/store_rebuild_queries.py
  - src/turing_agentmemory_mcp/tenant_identity.py
  - src/turing_agentmemory_mcp/tenant_provisioning.py
  - src/turing_agentmemory_mcp/tenant_registry.py
  - src/turing_agentmemory_mcp/tenant_router.py
  - tests/_arcadedb_lifecycle_isolation_support.py
  - tests/_arcadedb_physical_isolation_support.py
  - tests/test_arcadedb_client_transport.py
  - tests/test_arcadedb_physical_tenant_isolation.py
  - tests/test_arcadedb_schema.py
  - tests/test_compose_config.py
  - tests/test_document_file_pipe.py
  - tests/test_document_ingest_file.py
  - tests/test_document_job_manager.py
  - tests/test_document_jobs.py
  - tests/test_store_arcadedb_core.py
  - tests/test_tenant_identity.py
  - tests/test_tenant_provisioning.py
  - tests/test_tenant_query_scope.py
  - tests/test_tenant_registry.py
  - tests/test_tenant_router.py
  - tests/test_tenant_server_routing.py
findings:
  critical: 2
  warning: 3
  info: 0
  total: 5
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-07-15T13:59:58Z
**Depth:** standard
**Files Reviewed:** 39
**Status:** issues_found

## Summary

The database naming, registry, ready-last manifest, router single-flight, cache bounds,
and SQL predicate coverage are generally coherent. However, the tenant store is not
actually bound to the exact tenant identifier, and shared telemetry records raw tenant
identities despite the phase's pseudonymous-diagnostics contract. Three concurrency and
recovery paths can also fail or remain stuck under valid concurrent/process-failure
conditions.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: A tenant database-bound store accepts a different tenant identifier

**Files:** `src/turing_agentmemory_mcp/tenant_router.py:122-131`,
`src/turing_agentmemory_mcp/store_core.py:468-469`

**Issue:** `TenantRouter.resolve()` constructs `TuringAgentMemory` with only the
database-bound client and shared dependencies. The exact identifier used to derive that
database is not bound to the store. `_require_user()` checks only that a later identifier
is syntactically valid. Therefore, code holding tenant A's view can call a public store
method with tenant B's valid identifier; `_ensure_user()` and subsequent writes then
create tenant B records inside tenant A's physical database. This violates ARC-07's
additive physical-plus-predicate isolation and turns any caller/resolver mismatch into
data misplacement rather than a fail-closed error. A direct diagnostic call reproduced a
tenant-B write while the client remained bound to a tenant-A database.

**Fix:** Bind the exact identifier (or a keyed digest that can be recomputed) when the
tenant store is created, and make every `_require_user()` call verify that binding before
query or mutation:

```python
memory = self.store_factory(
    provisioned.client,
    shared_dependencies=self.shared_dependencies,
    bound_user_identifier=exact_identifier,
)

def _require_user(self, user_identifier: str) -> None:
    exact = validate_user_identifier(user_identifier)
    if not hmac.compare_digest(exact.encode(), self._bound_user_identifier.encode()):
        raise ValueError("tenant store binding does not match")
```

Keep the bound value private and out of repr/status. Add adversarial tests that invoke a
tenant-A view with tenant B's identifier for read, write, update, delete, document, and
background-job paths and assert zero client activity.

### CR-02: Shared spans and audit records disclose raw tenant identifiers

**Files:** `src/turing_agentmemory_mcp/store_core.py:375-395`,
`src/turing_agentmemory_mcp/store_memory_write.py:54-56`,
`src/turing_agentmemory_mcp/store_documents.py:108-114`

**Issue:** Store operations pass raw `user_identifier` values to the shared observer and
audit sink. The configured JSONL/stderr recorders retain that attribute, and
`StoreSharedDependencies` deliberately shares those recorders across all tenant views.
This contradicts the Phase 05 requirement that routing diagnostics/logs expose only the
opaque database identity. It is especially sensitive because tenant identifiers are
expected to be emails/usernames. The live isolation harness scans caplog, errors, reprs,
and status, but it does not scan observer events or an enabled audit sink, so its current
"no raw identity" assertion misses the actual leak.

**Fix:** Sanitize centrally at the span/audit choke points and emit only the opaque bound
database name (or omit tenant identity):

```python
attributes.pop("user_identifier", None)
attributes["tenant_database"] = self.client.database
```

Apply the same rule to `_audit()` rather than recording the raw identifier. Extend the
live/unit leakage tests with `InMemorySpanRecorder` and a capturing audit sink, then scan
their serialized events for every exact tenant identifier.

## Warnings

### WR-01: Same-tenant idempotent creates use race-prone read-then-create sequences

**Files:** `src/turing_agentmemory_mcp/store_core.py:357-370`,
`src/turing_agentmemory_mcp/store_memory_write.py:356-394`,
`src/turing_agentmemory_mcp/store_documents.py:125-142`

**Issue:** User, memory, and document creation first query for existence and then issue a
separate UNIQUE-indexed `CREATE`. Two concurrent operations on the same tenant can both
observe absence and race the create. The managed transaction retry repeats the same
`CREATE`; it does not re-run the existence check, so a duplicate-key outcome still fails
one otherwise idempotent request. The concurrency suite single-flights view creation but
does not exercise concurrent first writes through that shared view.

**Fix:** Use a live-verified ArcadeDB idempotent create/upsert form, or catch only the
confirmed duplicate-key signal and re-read the exact tenant-scoped record before treating
the operation as a replay. Cover concurrent identical and conflicting first writes for
User, Memory, and Document.

### WR-02: An expired `cancel_requested` lease can never reach a terminal state

**File:** `src/turing_agentmemory_mcp/document_jobs.py:232-270`

**Issue:** `cancel()` changes a running job to `cancel_requested`, but `claim()` only
selects expired `running` jobs. If the owning worker dies after the cancellation request,
the expired row is never claimable or reaped and remains `cancel_requested` forever with
staged bytes retained. A diagnostic reproduction advanced past the lease and confirmed a
second worker received no job.

**Fix:** Reconcile expired `cancel_requested` rows atomically. Either claim them while
preserving the cancellation intent so the manager immediately calls `mark_canceled()` and
removes staging, or add a reaper that transitions them to `canceled` and returns their
staged paths for safe cleanup. Add a worker-crash-after-cancel lease-expiry test.

### WR-03: Upload session sequence and file mutation are not synchronized

**File:** `src/turing_agentmemory_mcp/file_upload.py:99-125`

**Issue:** `_sessions`, `next_sequence`, `received_bytes`, append writes, completion, and
discard are mutated without a lock. Concurrent FastMCP chunk calls can both pass the same
sequence/size checks before either increments the counters, append out of order, and leave
an otherwise valid upload unusable. Concurrent discard/complete can also race an append.

**Fix:** Protect session lookup, sequence/size validation, file append, counter updates,
complete, and discard with a per-session lock (plus a short global lock for the session
map). Add a barrier-based test proving that duplicate concurrent sequence numbers yield
one accepted append and one deterministic rejection.

---

_Reviewed: 2026-07-15T13:59:58Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
