---
phase: 04-arcadedb-direct-port
reviewed: 2026-07-14T00:00:00Z
depth: deep
files_reviewed: 21
files_reviewed_list:
  - src/turing_agentmemory_mcp/arcadedb_client.py
  - src/turing_agentmemory_mcp/arcadedb_schema.py
  - src/turing_agentmemory_mcp/sparse_encoder.py
  - src/turing_agentmemory_mcp/store_core.py
  - src/turing_agentmemory_mcp/store_memory_write.py
  - src/turing_agentmemory_mcp/store_memory_read.py
  - src/turing_agentmemory_mcp/store_memory_queries.py
  - src/turing_agentmemory_mcp/store_documents.py
  - src/turing_agentmemory_mcp/store_chunking.py
  - src/turing_agentmemory_mcp/store_documents_queries.py
  - src/turing_agentmemory_mcp/store_search.py
  - src/turing_agentmemory_mcp/store_evidence.py
  - src/turing_agentmemory_mcp/store_retrieval_queries.py
  - src/turing_agentmemory_mcp/store_rebuild.py
  - src/turing_agentmemory_mcp/store_rebuild_queries.py
  - src/turing_agentmemory_mcp/store_rebuild_sparse.py
  - src/turing_agentmemory_mcp/ids.py
  - src/turing_agentmemory_mcp/store_utils.py
  - src/turing_agentmemory_mcp/server.py
  - src/turing_agentmemory_mcp/benchmark_stages.py
  - scripts/e2e_score.py
findings:
  critical: 1
  high: 3
  medium: 3
  low: 3
  total: 10
status: resolved
---

# Phase 04 (arcadedb-direct-port): Code Review Report

**Reviewed:** 2026-07-14
**Depth:** deep (cross-file, including query-builder → traversal → caller chains)
**Files Reviewed:** 21 (`compose.yaml` also read; no findings against it beyond one Low note)
**Status:** issues_found

## Summary

This is a substantial, well-organized rewrite: `ids.stable_id()` is consistently the sole
cross-record identifier (no `vector_id`/RID leakage found anywhere in the reviewed
surface), every `*_queries.py` builder binds data values as `?`/`:named` params with zero
residual string interpolation of *data*, `run_in_transaction`'s MVCC-conflict-vs-generic-retry
split is correctly implemented, and the both-channels lexical design (shared
`sparse_encoder.sparse_vector()` on write and query side, Lucene special-char escaping via
`escape_lucene_query`) is applied consistently and matches the spike findings. `ruff check`
is clean on the whole file set and no file exceeds the 600-LOC cap.

The review did surface a real, load-bearing gap in the area the phase brief specifically
asked about: **tenant scoping is not uniformly explicit past the first graph hop**. Because
this milestone runs one shared ArcadeDB database with `user_identifier`-property scoping as
the *only* isolation mechanism (confirmed by the project's own tenant-isolation test
docstring: "no DB-level defense-in-depth this phase"), any query that reaches a second
record via a graph traversal or an `IN`-list without re-asserting `user_identifier` is a
structural risk even where current data-shape guarantees (tenant-namespaced `stable_id()`
hashes, edges only ever created within a single tenant's write batch) keep it from being
exploitable today. Three concrete instances of this pattern are below (C1/H1/H2). A separate,
unrelated transaction-atomicity regression in `reindex_document_text` (H3) and a few
medium/low completeness and dead-code items round out the findings.

## Structural Findings (fallow)

None provided for this review (no `<structural_findings>` block was supplied upstream).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Two-hop entity→fact→memory MATCH leaves the intermediate hops unscoped by `user_identifier`

**File:** `src/turing_agentmemory_mcp/store_retrieval_queries.py:121-151` (`entity_traversal_statement`), consumed by `src/turing_agentmemory_mcp/store_evidence.py:407-445` (`_expand_entity_evidence`, the default `bm25`/`entity_dense`/`graph` seed path for every fused `search_memory`/`memory_get_context` call).

**Issue:** The generated `MATCH` pattern is:

```
{type: Entity, as: e, where: (id IN :entity_ids AND user_identifier = :user_identifier AND status = 'active')}
[.both(){as: n, where: (status = 'active')}]
.out('SUBJECT_OF'|'OBJECT_OF'){as: f, where: (status = 'active')}
.out('SUPPORTED_BY'){as: m, where: (status = 'active')}
RETURN m.id AS memory_id, f.id AS fact_id, f.confidence AS confidence, e.id AS entity_id
```

Only the seed vertex `e` is filtered on `user_identifier`. The optional intermediate
entity `n` (hop=2, `.both()` — any edge type, any direction), the `Fact` vertex `f`, and
the `Memory` vertex `m` are filtered only by `status = 'active'`. This is precisely the
"a MATCH/TRAVERSE that could cross tenants" pattern the review brief called out. It is
**not currently exploitable** — every `Entity`/`Fact` id is `stable_id()`-hashed with
`user_identifier` baked in, and `SUBJECT_OF`/`OBJECT_OF`/`SUPPORTED_BY`/`MENTIONS` edges are
only ever created inside a single tenant's own write batch (`store_memory_write.py`'s
`_create_memories_batch`, `store_rebuild.py`'s `_replace_community_graph`) — so no
cross-tenant edge can exist under the current write paths. But the query itself provides
**zero defense-in-depth**: this is the ONE mechanism CLAUDE.md invariant #1 calls
"non-negotiable," and in a single-shared-database model it is the *only* backstop. A future
write-path bug, an admin script, or a bulk-import tool that ever creates a cross-tenant edge
would leak another tenant's fact/memory content silently through this exact query, with no
test anywhere (`tests/test_arcadedb_tenant_isolation.py` only exercises the
CREATE VERTEX/SELECT/UPDATE memory paths, not this MATCH) that would catch it.

**Fix:** Add `user_identifier` to every stage's `where:` clause, not just the seed:

```python
pattern = (
    "{type: Entity, as: e, where: (id IN :entity_ids "
    "AND user_identifier = :user_identifier AND status = 'active')}"
)
if hop == 2:
    pattern += (
        ".both(){as: n, where: (user_identifier = :user_identifier AND status = 'active')}"
    )
pattern += (
    f".out('{edge_kind}'){{as: f, where: "
    "(user_identifier = :user_identifier AND status = 'active')}}"
    ".out('SUPPORTED_BY'){as: m, where: "
    "(user_identifier = :user_identifier AND status = 'active')}"
)
```

Add a regression test that creates a cross-tenant `SUBJECT_OF`/`SUPPORTED_BY` edge directly
(bypassing the normal write path, simulating "the invariant that currently prevents this
breaks") and asserts `_expand_entity_evidence`/`search_memory` for tenant A never returns
tenant B's fact/memory.

## High Issues

### HI-01: `chunk_context_statement`'s NEXT_CHUNK traversal has no `user_identifier` filter at all

**File:** `src/turing_agentmemory_mcp/store_documents_queries.py:299-304`, consumed by `src/turing_agentmemory_mcp/store_chunking.py:93-107` (`_chunk_context`, called by every `search_documents` hit to build citation context).

**Issue:**

```python
def chunk_context_statement(*, chunk_id: str) -> Statement:
    return (
        "SELECT id AS chunk_id, locator, text FROM "
        "(SELECT expand(out('NEXT_CHUNK')) FROM Chunk WHERE id = :id) WHERE status = 'active'",
        {"id": chunk_id},
    )
```

No `user_identifier` bound or filtered anywhere in this statement or its only caller. Same
"safe today because `chunk_id` is a tenant-namespaced `stable_id()` hash and `NEXT_CHUNK`
edges are only ever created within one tenant's own `_create_document` batch, but zero
query-level backstop" pattern as CR-01. Every citation context returned to a caller
implicitly trusts that `chunk_id` was already tenant-validated upstream — true today, but
undocumented and unenforced at this call site.

**Fix:** Thread `user_identifier` through `_chunk_context`/`chunk_context_statement` and add
it to both the outer and inner `WHERE`:

```python
def chunk_context_statement(*, chunk_id: str, user_identifier: str) -> Statement:
    return (
        "SELECT id AS chunk_id, locator, text FROM "
        "(SELECT expand(out('NEXT_CHUNK')) FROM Chunk "
        "WHERE id = :id AND user_identifier = :user_identifier) "
        "WHERE status = 'active' AND user_identifier = :user_identifier",
        {"id": chunk_id, "user_identifier": user_identifier},
    )
```

### HI-02: `memory_delete_statements`'s Fact soft-delete has no `user_identifier` filter

**File:** `src/turing_agentmemory_mcp/store_memory_queries.py:298-312`, consumed by `src/turing_agentmemory_mcp/store_memory_read.py:220-262` (`delete_memory`).

**Issue:**

```python
if fact_ids:
    statements.append(
        ("UPDATE Fact SET status = 'deleted' WHERE id IN :fact_ids", {"fact_ids": fact_ids})
    )
```

`fact_ids` is produced by `_fact_ids_for_memory` (`store_rebuild_queries.py:202-207`), which
*is* correctly `user_identifier`-scoped, so this is not exploitable through the current
call graph. But the statement itself — the thing that actually mutates data — carries no
tenant assertion, unlike every sibling delete/update statement in this same file
(`memory_delete_statements`'s own Memory-status UPDATE two lines above IS scoped). This is
an inconsistency within the same function, not just a theoretical gap.

**Fix:** Add the same scope the sibling statement already has:

```python
(
    "UPDATE Fact SET status = 'deleted' WHERE id IN :fact_ids "
    "AND user_identifier = :user_identifier",
    {"fact_ids": fact_ids, "user_identifier": user_identifier},
)
```

### HI-03: `reindex_document_text` hard-deletes and recreates in two separate managed transactions — not atomic

**File:** `src/turing_agentmemory_mcp/store_documents.py:174-241` (`reindex_document_text`).

**Issue:** The method calls `self._write_many([document_hard_delete_statement(...), chunk_hard_delete_statement(...)])` (one `run_in_transaction`), then separately calls `self._create_document(...)` which issues its own, independent `self._write_many(statements)` (a second `run_in_transaction`). These are two distinct commits, not one. Between them:

- A concurrent `get_document`/`search_documents` call for the same `document_id` observes the document and every one of its chunks as completely gone (not "old version," not "new version" — absent).
- If the process crashes/is killed between the two transactions (e.g., OOM from HI-adjacent finding MD-01 below, or a container restart), the document is left permanently deleted with no recreate, and re-running `reindex_document_text` would then hit the normal (non-hard-delete) create path since `get_document` would return `None` — recoverable, but only via a second explicit call; the tool's caller has no signal that a partial failure occurred beyond a raised exception on the second `_write_many`.

This is exactly the "partial-write / non-atomic multi-node CREATE path" the review brief
asked to be checked for. The 04-09 fix this docstring documents (avoiding
`DuplicatedKeyException` on same-id recreate) is real and necessary, but the fix reintroduced
a different atomicity gap than the one it closed.

**Fix:** Either (a) fold the hard-delete statements into the *same* statement list that
`_create_document` builds and pass them to a single `_write_many` call (ArcadeDB's
session-header read-your-writes model already guarantees a `CREATE VERTEX` for the same `id`
in the same transaction sees the just-issued `DELETE` — this needs verifying live, since it's
delete-then-recreate of the *same* unique-indexed `id`, not create-then-read), or (b) if intra-transaction delete+recreate-same-unique-key is not safe on 26.7.1, document the
narrow inconsistency window explicitly and add a test asserting `get_document` during that
window returns a clearly-labeled "reindexing" state rather than silently `None`.

## Medium Issues

### MD-01: `document_graph_batch_chunks`/`document_graph_batch_bytes` are validated and env-wired but never consulted — every document is committed as one unbounded transaction

**File:** `src/turing_agentmemory_mcp/store_core.py:82-103`; `src/turing_agentmemory_mcp/store_documents.py:266-349` (`_create_document`); also wired end-to-end via `src/turing_agentmemory_mcp/server.py:182-187` and `compose.yaml:232-233` (`AGENTMEMORY_DOCUMENT_GRAPH_BATCH_CHUNKS`/`_BYTES`).

**Issue:** `store_core.py`'s docstring states these two constructor params are "repurposed as
transaction-size (host-RAM) hygiene under this model, not a workaround for a
submit-before-match visibility gap" (i.e., they're meant to still bound how much a single
managed transaction holds). But `self.document_graph_batch_chunks`/`self.document_graph_batch_bytes` are stored on `self` and never read anywhere else in the reviewed
files — `_create_document` builds the *entire* document's statement list (1 Document vertex +
N Chunk vertices + N `HAS_CHUNK` edges + up to N-1 `NEXT_CHUNK` edges) and passes it to one
`self._write_many(statements)` call with no chunking by count or byte size. An operator
setting `AGENTMEMORY_DOCUMENT_GRAPH_BATCH_CHUNKS=50` expecting a 5,000-chunk document to be
split into ~100 transactions gets no such behavior — a single document of any size is held
entirely in the ArcadeDB session's host RAM until one commit, which is exactly the risk the
docstring says this configuration exists to bound.

**Fix:** Either wire `document_graph_batch_chunks`/`document_graph_batch_bytes` into
`_create_document` to actually split `statements` into bounded `_write_many` calls (accepting
that this reintroduces a partial-document-visible-mid-ingest window, which would need its own
"searchable only once fully committed" status guard), or remove the now-dead knobs/env vars
and the misleading docstring claim if unbounded-per-document is the accepted design for this
milestone.

### MD-02: `store_rebuild_sparse.py`'s legacy rebuild still issues Cypher-shaped queries through the SQL-only `_query()` seam — `rebuild_sparse_projection()` is broken against the live ArcadeDB backend

**File:** `src/turing_agentmemory_mcp/store_rebuild_sparse.py:104-185` (`_canonical_sparse_documents`, `_sparse_rebuild_rows`).

**Issue:** This module is explicitly, deliberately left un-ported per its own docstring and
`04-VERIFICATION.md`. But `store_core.py::_query` (the only path this module's
`_sparse_rebuild_rows` calls) submits every statement with `language="sql"` by default
(`self.client.query(query, params=params)` → `ArcadeDBClient.query(..., language: str = "sql", ...)`). The strings this module builds are openCypher literals
(`'MATCH (m:Memory) WHERE m.status = "active" RETURN m.id, ...'`), which ArcadeDB's SQL
parser will reject as a syntax error, not as the `"Unknown label: {label}"` error the narrow
`except` clause in `_sparse_rebuild_rows` was written to swallow. Concretely: any caller of
`store.rebuild_sparse_projection()` against the live ArcadeDB backend with
`fusion_enabled=True` (the `compose.yaml` default — `AGENTMEMORY_FUSION_ENABLED=1`) will get
an unhandled `RuntimeError` from the SQL parse failure, not the empty-fallback the exception
handler was designed for.

**Fix:** Either port this module in the deferred later wave (as already planned), or — at
minimum for this milestone — guard the public `rebuild_sparse_projection()` entry point with
an explicit `NotImplementedError`/feature-flag check so a caller gets a clear "not yet ported"
message instead of an opaque SQL-parse `RuntimeError` surfaced from deep inside `_query`.

### MD-03: `ArcadeDBClient._request`'s response decoding can raise outside the method's own error-translation/retry contract

**File:** `src/turing_agentmemory_mcp/arcadedb_client.py:279-287`.

**Issue:**

```python
with urlopen(req, timeout=self.timeout_s) as resp:
    raw = resp.read()
    returned_session = resp.headers.get(_SESSION_HEADER)
    decoded = json.loads(raw.decode("utf-8")) if raw else {}
```

`raw.decode("utf-8")` and `json.loads(...)` are not wrapped by any of the surrounding
`except` clauses (`HTTPError`; `URLError, TimeoutError, OSError`). A malformed or non-UTF-8
2xx response (e.g., a proxy/load-balancer health page returned instead of ArcadeDB JSON, or a
truncated read) raises `UnicodeDecodeError`/`json.JSONDecodeError` directly out of `_request`,
bypassing both the transport retry loop (module docstring: "raise-hard on exhaustion... no
soft degrade") and — more importantly — `run_in_transaction`'s `except RuntimeError` guard, so
no `rollback()` is attempted and the ArcadeDB-side session is left dangling until it times out
server-side.

**Fix:** Wrap the decode in the same try block and re-raise as `RuntimeError`:

```python
try:
    decoded = json.loads(raw.decode("utf-8")) if raw else {}
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise RuntimeError(f"ArcadeDB {path} returned an undecodable response") from exc
```

## Low Issues

### LO-01: Dead code — `_ensure_vector_index`/`_ensure_tenant_vector_index` have no remaining callers

**File:** `src/turing_agentmemory_mcp/store_core.py:254-271`.

**Issue:** Both methods were an explicit "back-compat shim for unported mixins (Wave 4)" per
their own docstrings. Wave 4 (04-05 through 04-08) is now complete and no mixin in the
reviewed set calls either method (confirmed via repo-wide grep — only definitions and stale
docstring/test-comment references remain). Per CLAUDE.md's "DEEP REFACTOR ON TOUCH" /
dead-code-removal-on-touch discipline, these should have been deleted alongside the rest of
the 04-09 "close the port" cleanup (which did delete the `vector_id` machinery in the same
spirit).

**Fix:** Delete `_ensure_vector_index` and `_ensure_tenant_vector_index` (and
`_tenant_vector_index` if nothing outside tests still calls it directly — confirm before
removing, since `test_batch_memory.py::test_tenant_vector_index_names_are_deterministic_and_isolated` calls `_tenant_vector_index` directly).

### LO-02: Non-fused `search_memory` still full-scans every active memory for lexical scoring

**File:** `src/turing_agentmemory_mcp/store_search.py:100-131`.

**Issue:** The fused path (`store_evidence.py`) now sources lexical candidates from the
native `SEARCH_INDEX`/`sparseNeighbors` channels. The non-fused path (used whenever
`AGENTMEMORY_FUSION_ENABLED` is unset/false — the default in `store_from_env`, distinct from
the `compose.yaml` docker-stack default which does enable it) still does:

```python
for row in self._active_memory_rows(user_identifier):
    memory_id = str(row.get("id", ""))
    if memory_id and memory_id not in rows_by_id:
        rows_by_id[memory_id] = row
```

i.e., an unconditional full active-memory table scan for the tenant, then computes
`lexical_score(...)` against every row in Python — the exact "old full active-chunk-rows
table scan" pattern `store_documents.py`'s docstring says "the port fixes for free," except
that fix was only applied to `search_documents`, not to non-fused `search_memory`. Flagged as
Low since it's a completeness/performance-adjacent inconsistency rather than a correctness
bug (out of this review's stated performance scope), but it contradicts the phase's own
stated intent and is worth a follow-up ticket.

### LO-03: `ARCADEDB_PASSWORD` dev default is baked into `compose.yaml` in three places

**File:** `compose.yaml:83`, `:189`, `:649`.

**Issue:** `${ARCADEDB_PASSWORD:-agentmemory-arcadedb-dev}` appears in the `arcadedb`
service, the `turing-agentmemory-mcp` service, and the `e2e` profile service. This matches
the spike's already-accepted risk posture (127.0.0.1-only publish, root password required at
all, not a "default-open" instance) — not a new regression from this port — but three
independent copies of the same fallback literal is a minor duplication/quality nit worth
consolidating into one `.env`-documented default, and worth a one-line comment noting it MUST
be overridden for any non-loopback deployment (the `arcadedb`/`turingdb` services already
carry similar 127.0.0.1-only guards; this is consistent, just undocumented at the point of
use).

---

## Fix Outcomes

All 10 findings resolved (9 fixed this pass; MD-02 was already resolved by 04-10 and
re-verified here). Full test suite green throughout (final: 514 passed, 0 failed —
up from the 502-passed baseline, +12 regression tests added across these fixes).
`ruff check src tests scripts`, `bash scripts/check-file-size.sh`, and
`docker compose config --quiet` all pass after every commit.

| ID | Disposition | Commit | Summary |
|----|-------------|--------|---------|
| CR-01 | fixed | `ff08398` | `entity_traversal_statement` now binds `user_identifier` on every hop (seed `e`, intermediate `n`, `f`, `m`), not just the seed. Regression test plants a cross-tenant `SUBJECT_OF`/`SUPPORTED_BY` edge directly at hop=1 and hop=2 and asserts `_expand_entity_evidence`/`search_memory` never leak it. |
| HI-01 | fixed | `cf3b082` | `chunk_context_statement`/`_chunk_context` now thread and bind `user_identifier` in both the inner and outer `WHERE`. Regression test plants a cross-tenant `NEXT_CHUNK` edge and asserts no leak. Split `test_store_arcadedb_documents.py`'s fake-client fixture into `_documents_arcadedb_shared.py` to stay under the 600-LOC cap. |
| HI-02 | fixed | `c911c01` | `memory_delete_statements`'s Fact soft-delete `UPDATE` now binds `AND user_identifier = :user_identifier`, matching its sibling Memory-status `UPDATE`. Regression test forces `_fact_ids_for_memory` to return a cross-tenant fact id and asserts `delete_memory` never touches that row. |
| HI-03 | fixed | `b3005c2` | `reindex_document_text`'s hard-delete + `_create_document`'s recreate now run in ONE managed transaction (`extra_statements` param prepended into the same `_write_many` call), not two separate commits. Live-verified against a real ArcadeDB 26.7.1 container (docker compose `arcadedb` service) that intra-transaction delete-then-recreate of the same UNIQUE-indexed `id` succeeds, and that the full ingest → reindex → get_document → search_documents path round-trips correctly — the 04-09 `DuplicatedKeyException` fix is unaffected. Regression test asserts exactly one begin/commit cycle. |
| MD-01 | fixed | `f2f1942` | Investigated wiring `document_graph_batch_chunks`/`_bytes` into real batch splitting first: document visibility has no status guard beyond the transaction boundary (the async job's status is a job-level concept, not a per-document readiness gate), so splitting would open a partial-document-visible-mid-ingest window. Removed the dead knobs, their validation, `server.py`'s env wiring, `compose.yaml`'s env vars, and the stale `docs/` references instead — documented as the lower-risk correct option in `CHANGELOG.md`'s Removed section and `store_core.py`'s docstring. |
| MD-02 | already resolved (verified) | n/a | Confirmed `store_rebuild_sparse.py` is deleted (04-10) and `rebuild_sparse_projection` has zero live callers in `src/`/`tests/` (repo-wide grep: only historical `.planning/` docs and a test asserting the module's absence remain). `TuringAgentMemory`'s MRO carries only `_RebuildMixin`, which itself documents the sparse-outbox rebuild retirement. No orphaned caller found. |
| MD-03 | fixed | `efbf927` | `ArcadeDBClient._request`'s response decode is now wrapped in its own try/except, re-raising `UnicodeDecodeError`/`json.JSONDecodeError` as `RuntimeError` so a malformed 2xx response flows through `run_in_transaction`'s rollback contract instead of escaping it. Unit tests with a scripted fake response returning non-UTF-8/non-JSON bytes cover both standalone `query()` and inside `run_in_transaction` (asserting rollback fires, commit never does). Split `test_arcadedb_client.py`'s mocked-HTTP section into a new sibling `test_arcadedb_client_transport.py` to stay under the 600-LOC cap. |
| LO-01 | fixed | `bea86a7` | Deleted the dead `_ensure_vector_index`/`_ensure_tenant_vector_index` back-compat shims (confirmed zero live callers via repo-wide grep). Kept `_tenant_vector_index`, confirmed still called directly by `test_batch_memory.py::test_tenant_vector_index_names_are_deterministic_and_isolated`. |
| LO-02 | fixed | `080a56d` | Non-fused `search_memory`'s lexical candidate supplement now reads the native `SEARCH_INDEX` Lucene channel (`lucene_search_statement`) instead of an unconditional full active-memory-rows table scan, mirroring `search_documents`' precedent. Regression test crowds the dense over-fetch top-k with near-identical-length noise (clamping their semantic score to zero) so a target memory with a very different length can only be found through the native lexical channel, proving equivalence with the old full-scan's "find it regardless of dense proximity" behavior. |
| LO-03 | fixed | `70ca43f` | `.env.example` is now the explicit single documented source of the `ARCADEDB_PASSWORD` dev default, with a "MUST be overridden for any non-loopback deployment" caveat. Each of `compose.yaml`'s three occurrences (Compose's `${VAR:-default}` interpolation has no cross-referencing mechanism, so the literal value is still repeated) now carries a comment pointing back to it. Added a test asserting all three stay byte-identical to each other and to `.env.example`. `docker compose config --quiet` passes. |

---

_Reviewed: 2026-07-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
_Fixed: 2026-07-14_
_Fixer: Claude (gsd-code-fixer)_
