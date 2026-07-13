# Phase 4: ArcadeDB Direct Port - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 12 (1 new client, 1 new schema-bootstrap, 9 ported store mixins, 1 compose service)
**Analogs found:** 12 / 12 (all have a same-repo analog; ArcadeDB-specific syntax remains a spike unknown per D-02 — no analog can resolve that, only the SC#1 spike can)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `src/turing_agentmemory_mcp/arcadedb_client.py` (NEW) | service (HTTP client) | request-response | `src/turing_agentmemory_mcp/embeddings.py` (`OpenAICompatibleEmbedder`) + `src/turing_agentmemory_mcp/rerank.py` (`OpenAICompatibleReranker`) | exact (convention match: stdlib `urllib.request`, retry loop, `from_env()` factory) |
| `src/turing_agentmemory_mcp/arcadedb_schema.py` (NEW, or folded into client) | config / bootstrap | idempotent batch | `src/turing_agentmemory_mcp/store_core.py` `_ensure_vector_index` / `bootstrap` | role-match (idempotent CREATE + dimension-mismatch `ValueError` pattern to port, not copy verbatim) |
| `src/turing_agentmemory_mcp/store_core.py` (PORTED) | service (choke-point / infra mixin) | request-response + transactional batch | itself (pre-port version) | exact (in-place port; `_query`/`_write`/`_write_many`/`load_graph_after_restart`/`_ensure_vector_index` all rewritten against `arcadedb_client`) |
| `src/turing_agentmemory_mcp/store_documents.py` (PORTED) | service (CRUD + search) | CRUD + request-response | itself (pre-port version); secondary analog `store_memory_write.py` for the sqlscript/LET batch shape | exact, but **LOC-budget risk** (597→ grows with sqlscript+LET; extract query-builder helpers to a new sibling module, e.g. `store_documents_queries.py`, before this file crosses 600 LOC) |
| `src/turing_agentmemory_mcp/store_memory_write.py` (PORTED) | service (CRUD write) | CRUD + transactional batch | itself (pre-port version) | exact, same LOC-budget risk (599 LOC pre-port) |
| `src/turing_agentmemory_mcp/store_search.py` (PORTED) | service (retrieval fusion) | request-response | itself (pre-port version) | exact — `_search_memory_fused`'s RRF glue is unchanged; only the per-channel query strings (vector/BM25/graph/community) are re-expressed in ArcadeDB SQL |
| `src/turing_agentmemory_mcp/store_chunking.py` (PORTED) | service (batch query builder) | CRUD + batch | itself (pre-port version) | exact — `_chunk_context`/`NEXT_CHUNK` MATCH traversal ports to SQL MATCH/TRAVERSE (D-05) |
| `src/turing_agentmemory_mcp/store_evidence.py` (PORTED) | service (graph traversal) | request-response | itself (pre-port version) | exact — `_expand_entity_evidence`'s string-built OR-list becomes bound `IN :ids` array param (Pattern 4) |
| `src/turing_agentmemory_mcp/store_rebuild.py` (PORTED) | service (batch rebuild) | batch + transactional | itself (pre-port version) | exact — `_replace_community_graph`'s multi-node CREATE becomes sqlscript+LET; vector rebuild gains D-07 versioned-index atomic swap (new behavior, no in-repo analog for the swap itself — see "No Analog Found") |
| `src/turing_agentmemory_mcp/store_utils.py` (PORTED — deletions) | utility (pure helpers) | transform | itself (pre-port version) | exact — delete the 5 `_*_vector_id()` staticmethods (lines 198-216) and their `vector_id` import (line 15) |
| `src/turing_agentmemory_mcp/ids.py` (PORTED — deletions) | utility | transform | itself (pre-port version) | exact — delete `vector_id()` (lines 15-18); retire `quote()` (lines 29-36) in favor of bound params; keep `stable_id()`/`cypher_var()` |
| `compose.yaml` (new `arcadedb` service block) | config | request-response (HTTP healthcheck) | `turingdb`/`turingdb-volume-init` service pair (lines 4-75) | exact — same non-root user, `tmpfs: /tmp,/run`, `security_opt: no-new-privileges`, `deploy.resources.limits`, healthcheck-with-retries shape |
| `.env.example` / `pyproject.toml` (new `ARCADEDB_*` vars) | config | — | existing `TURINGDB_*` block (`compose.yaml` lines 143-150) | exact — same `${VAR:-default}` templating convention, additive not replacing |

## Pattern Assignments

### `src/turing_agentmemory_mcp/arcadedb_client.py` (service, request-response)

**Analogs:** `src/turing_agentmemory_mcp/embeddings.py` (`OpenAICompatibleEmbedder`), `src/turing_agentmemory_mcp/rerank.py` (`OpenAICompatibleReranker`)

**Imports pattern** (`embeddings.py` lines 1-22):
```python
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from turing_agentmemory_mcp.provider_config import (
    api_key_header_value,
    provider_api_key_header,
    provider_api_key_scheme,
    provider_env,
    provider_error_code,
    provider_optional_int,
    provider_secret,
    retryable_provider_code,
)
```
Copy this shape directly: `arcadedb_client.py` needs no new import beyond stdlib `urllib` + the same `provider_config` helpers (`provider_env`, `provider_secret` for basic-auth credentials if ArcadeDB security is enabled — see Runtime State Inventory in RESEARCH.md).

**`from_env()` factory pattern** (`embeddings.py` lines 84-101):
```python
@classmethod
def from_env(cls, *, dimensions: int | None = None) -> OpenAICompatibleEmbedder:
    configured_dimensions = dimensions or int(provider_env("EMBED_DIMENSIONS", default="768"))
    return cls(
        base_url=provider_env("EMBED_BASE_URL", default="http://127.0.0.1:8081"),
        ...
        timeout_s=float(provider_env("EMBED_TIMEOUT_SECONDS", default="60")),
        max_attempts=int(provider_env("EMBED_MAX_ATTEMPTS", default="3")),
        retry_base_s=float(provider_env("EMBED_RETRY_BASE_SECONDS", default="0.5")),
    )
```
Mirror for `arcadedb_client.py`: `ArcadeDBClient.from_env()` reading `ARCADEDB_URL`, `ARCADEDB_TIMEOUT_SECONDS`, `ARCADEDB_MAX_ATTEMPTS`, `ARCADEDB_RETRY_BASE_SECONDS`, plus credential env vars if the spike finds ArcadeDB requires basic auth by default.

**HTTP request + retry-with-backoff pattern** (`embeddings.py` lines 120-162, near-identical in `rerank.py` lines 163-200):
```python
body = json.dumps(payload).encode("utf-8")
req = Request(
    self.base_url.rstrip("/") + "/v1/embeddings",
    data=body,
    method="POST",
    headers={"Content-Type": "application/json"},
)
if self.api_key:
    req.add_header(
        self.api_key_header, api_key_header_value(self.api_key, self.api_key_scheme)
    )
decoded: object = None
for attempt in range(self.max_attempts):
    try:
        with urlopen(req, timeout=self.timeout_s) as resp:
            decoded = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if retryable_provider_code(exc.code) and attempt + 1 < self.max_attempts:
            time.sleep(self.retry_base_s * (2**attempt))
            continue
        raise RuntimeError(f"embedding provider HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        if attempt + 1 < self.max_attempts:
            time.sleep(self.retry_base_s * (2**attempt))
            continue
        raise RuntimeError(f"embedding provider unavailable at {self.base_url}") from exc
    break
```
This is the exact shape for `ArcadeDBClient.query()`/`.command()`/`.begin()`/`.commit()`/`.rollback()`: build `Request`, `urlopen` with timeout, exponential backoff on `HTTPError`/`URLError`/`OSError`, raise `RuntimeError` on exhaustion. The **retry-N wrapper for MVCC conflicts (D-08)** is a *second*, narrower retry loop layered on top of this transport retry — catch the ArcadeDB-specific conflict HTTP status/error code (spike must confirm which) separately from generic transport retries, following the same `retryable_provider_code`-style predicate-function convention rather than inlining the check.

**Error handling / raise-vs-degrade split**: `embeddings.py` raises `RuntimeError` on failure (embedding is load-bearing, no soft fallback). `rerank.py` instead returns a `RerankResult` with a `status` field (`"provider_error"`, `"invalid_response"`, `"disabled"`) and falls back to `identity(documents)`/`lexical_rerank` — because rerank is allowed to degrade gracefully. **For `arcadedb_client.py`: follow the `embeddings.py` raise-hard convention** — ArcadeDB is the canonical backend this phase (invariant #2 superseded in its favor), so a query/command failure must raise, not silently degrade the caller into stale/wrong data. Reserve a soft/degraded path only for the D-10 readiness probe (`/health` reporting unhealthy, not raising into request handlers).

**Validation-in-`__post_init__` pattern** (`embeddings.py` lines 72-82, `rerank.py` lines 97-101):
```python
def __post_init__(self) -> None:
    if isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
        raise ValueError("... max attempts must be positive")
    if self.retry_base_s < 0:
        raise ValueError("... retry base seconds must not be negative")
```
Copy for any new `@dataclass(frozen=True)` config object in `arcadedb_client.py`/`arcadedb_schema.py` (e.g. a `SchemaBootstrapConfig`).

---

### `src/turing_agentmemory_mcp/arcadedb_schema.py` (config / bootstrap, idempotent batch)

**Analog:** `src/turing_agentmemory_mcp/store_core.py` — `bootstrap()` (lines 194-206) and `_ensure_vector_index()` (lines 241-268)

**Idempotent bootstrap pattern** (`store_core.py` lines 194-206):
```python
def bootstrap(self) -> None:
    self.turing_home.mkdir(parents=True, exist_ok=True)
    self.data_dir.mkdir(parents=True, exist_ok=True)
    self._ensure_graph_loaded()
    self._ensure_vector_index(self.memory_index)
    self._ensure_vector_index(self.document_index)
    self._ensure_vector_index(self.entity_index)
    self._ensure_vector_index(self.fact_index)
    self._ensure_vector_index(self.community_index)
    if self.sparse_index is not None:
        self.sparse_index.initialize()
        self.sparse_index.replay()
    self.runtime_signals.configure_stage("graph", ready=True, identity={"graph": self.graph})
```
Model for D-09: an `arcadedb_schema.bootstrap(client, ...)` that idempotently CREATEs vertex/edge types + `LSM_VECTOR` index + full-text index + UNIQUE `stable_id` index, all versioned/namespaced (D-07), then flips a `RuntimeSignals` stage to ready — reuse `RuntimeSignals.configure_stage` verbatim rather than inventing a new readiness mechanism (this is also the D-10 "extend, don't invent" hook).

**Dimension-mismatch fail-fast pattern** (`store_core.py` lines 241-268, the exact model cited in CONTEXT.md D-09):
```python
def _ensure_vector_index(self, name: str) -> None:
    ...
    try:
        self._query(
            f"CREATE VECTOR INDEX {name} WITH DIMENSION {self.dimensions} METRIC COSINE",
            operation="vector_index.ensure",
        )
    except Exception:
        pass
    rows = self._records(self._query("SHOW VECTOR INDEXES", operation="vector_index.verify"))
    if not rows:
        ensured.add(name)
        return
    matching = [row for row in rows if str(row.get("name") or "") == name]
    if not matching:
        raise RuntimeError(f"vector index {name} was not created")
    actual = int(matching[0].get("dimension") or 0)
    if actual != self.dimensions:
        raise RuntimeError(
            f"vector index {name} dimension mismatch: "
            f"expected {self.dimensions}, found {actual}"
        )
    ensured.add(name)
```
Port shape: attempt idempotent `CREATE ... IF NOT EXISTS` (or catch a benign "already exists" error), then a verification `SELECT`/`SHOW`-equivalent query against ArcadeDB's schema introspection, comparing declared dims to `EMBED_DIMENSIONS` and raising `ValueError` (not `RuntimeError` — CONTEXT.md D-09 explicitly says "raises the existing `ValueError`") on mismatch. Exact ArcadeDB introspection query is a D-02 spike unknown — do not write this against a guessed syntax.

**Tenant-namespaced index naming** (`store_core.py` lines 270-282):
```python
@staticmethod
def _tenant_vector_index(base_name: str, user_identifier: str) -> str:
    digest = hashlib.blake2b(user_identifier.encode("utf-8"), digest_size=8).hexdigest()
    return cypher_var(f"{base_name}_tenant_{digest}")

def _ensure_tenant_vector_index(self, base_name: str, user_identifier: str) -> str:
    name = self._tenant_vector_index(base_name, user_identifier)
    self._ensure_vector_index(name)
    return name
```
Extend (don't replace) with a version suffix per D-07: e.g. `_tenant_vector_index(base_name, user_identifier, version)` appending `_v{version}` before the `cypher_var()` sanitize call, so the same blake2b-digest tenant-namespacing survives the port unchanged and only gains a version component.

---

### `src/turing_agentmemory_mcp/store_core.py` (PORTED — the choke point)

**Analog:** itself, pre-port

**`_query`/`_write`/`_write_many` seam** (lines 331-359) — this is the single place all nine mixins route through; port in place, do not duplicate the seam elsewhere:
```python
def _query(self, query: str, *, operation: str) -> Any:
    statement = query.lstrip().split(None, 1)[0].upper() if query.strip() else ""
    with self._span(
        "turingdb.query",
        {"operation": operation, "statement": statement, "graph": self.graph},
    ):
        return self.client.query(query)

def _write(self, query: str) -> None:
    with self._span("turingdb.write_transaction", {"graph": self.graph}):
        self.client.new_change()
        try:
            self._query(query, operation="write")
            self._query("CHANGE SUBMIT", operation="write.submit")
        finally:
            self.client.checkout()

def _write_many(self, queries: list[str]) -> None:
    if not queries:
        return
    with self._span(
        "turingdb.write_batch",
        {"graph": self.graph, "statement_count": len(queries)},
    ):
        # Later chunk batches MATCH nodes created by earlier batches. TuringDB
        # only exposes those nodes after CHANGE SUBMIT, so each bounded batch
        # is its own transaction.
        for query in queries:
            self._write(query)
```
**Port shape (D-08):** `_write_many` collapses from "one `_write` (submit) per batch" to **one managed `begin`/`command(sqlscript)`/`commit retry N`** — the per-batch-submit comment above (invariant #4) becomes stale under D-08 and must be replaced with a comment explaining the new read-your-writes-within-one-tx model. Keep the `self._span(...)` observability wrapper unchanged — it is backend-agnostic. Rename the span names from `turingdb.*` to `arcadedb.*` (cosmetic but keeps observability accurate).

**`load_graph_after_restart` / readiness (D-10 supersedes invariant #6)** (lines 208-210, 226-239):
```python
def load_graph_after_restart(self) -> None:
    self.client.load_graph(self.graph, raise_if_loaded=False)
    self.client.set_graph(self.graph)

def _ensure_graph_loaded(self) -> None:
    try:
        loaded_graphs = self.client.list_loaded_graphs()
    except Exception:
        loaded_graphs = []
    if self.graph not in loaded_graphs:
        try:
            self.client.load_graph(self.graph, raise_if_loaded=False)
        except Exception:
            try:
                self.client.create_graph(self.graph)
            except Exception:
                pass
    self.client.set_graph(self.graph)
```
Port shape: replace with `arcadedb_client.probe()`/`is_ready()` wired into `RuntimeSignals.configure_stage("graph", ...)` (D-10) — this whole "list loaded graphs, try to load, fall back to create" dance is TuringDB-specific and retires; ArcadeDB databases don't need an explicit load-after-restart step, only a reachability probe + reconnect. Do not port the try/except-swallow shape (`except Exception: pass`) verbatim — D-10 wants an observable degraded state, not a silent no-op.

---

### `src/turing_agentmemory_mcp/store_documents.py` / `store_memory_write.py` (PORTED — CRUD, sqlscript+LET batches)

**Analog:** each other (both build multi-node graph-write literals) plus `store_utils.py`'s `_projection_edge_literals`/`_cypher_value` (lines 22-41) for the value-quoting pattern being retired

**Current multi-node write literal being replaced** (`store_utils.py` lines 22-41):
```python
@classmethod
def _projection_edge_literals(cls, edges: tuple[EdgeProjection, ...]) -> list[str]:
    literals: list[str] = []
    for edge in edges:
        source_var = cypher_var(edge.source_id)
        target_var = cypher_var(edge.target_id)
        properties = {"id": edge.id, **edge.properties}
        property_text = ", ".join(
            f"{cypher_var(name)}: {cls._cypher_value(value)}"
            for name, value in properties.items()
        )
        literals.append(f"({source_var})-[:{edge.kind} {{{property_text}}}]->({target_var})")
    return literals

@staticmethod
def _cypher_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return f'"{quote(str(value))}"'
```
**Do not port `_cypher_value`'s double-quote-escaping unchanged** (Pitfall 2 in RESEARCH.md) — ArcadeDB SQL uses single-quoted literals and this project locks bound params as the replacement (RESEARCH.md Pattern 4, Don't Hand-Roll table). Replace with a params-dict builder: collect `{name: value}` pairs and bind them as named params on the `command`/`sqlscript` call instead of interpolating `_cypher_value(value)` into the literal string.

**`ingest_document_text` structure** (lines 74-110) — the ingest-path shape to preserve (validate → chunk → hash-dedup → write):
```python
def ingest_document_text(
    self, *, user_identifier: str, title: str, text: str, document_id: str | None = None, ...
) -> IngestedDocument:
    with self._span("document.ingest_text", {...}):
        self._require_user(user_identifier)
        if not title.strip():
            raise ValueError("title is required")
        if not text.strip():
            raise ValueError("text is required")
        text, metadata = self._process_text_for_storage(text, metadata)
        document_id = document_id or stable_id("doc", user_identifier, title, text[:128])
        text_hash = self._document_text_hash(text)
        chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
        self._ensure_user(user_identifier)
        existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
        ...
```
Preserve this exact validation/dedup/stable_id-generation sequence — only the graph-write call at the end (currently a Cypher `CREATE` literal, per RESEARCH.md's Pattern 1) changes to a `sqlscript` + `LET` batch through `arcadedb_client`.

**LOC-budget action (critical):** both files are pre-port at 597/599 LOC against the 600-LOC no-allowlist cap. The sqlscript+LET query-building code is *more* verbose per operation than the current Cypher literal (RESEARCH.md, Anti-Patterns). **Do not add the new query-builder inline** — extract a new sibling module (e.g. `store_documents_queries.py` alongside `store_documents.py`, or a shared `arcadedb_queries.py` if multiple mixins share shape) before `check-file-size.sh` fails on commit.

---

### `src/turing_agentmemory_mcp/store_search.py` (PORTED — RRF fusion, request-response)

**Analog:** itself, pre-port; `rerank.py`'s `blend_rerank_orders`/`apply_rerank_guard` (lines 271-334) for the "keep the Python-side algorithm, only the upstream candidate-fetch changes" pattern

**What's unchanged:** `apply_rerank_guard` (lines 271-303) and `blend_rerank_orders` (lines 323-334) in `rerank.py` are pure Python over already-fetched candidate lists — no ArcadeDB-specific code touches them; the port only changes how the seed candidate list is built (vector/BM25/graph/community channel queries), never the fusion/rerank-guard math itself. Use this file as the model for "leave `retrieval_fusion.py`'s weighted-RRF completely alone (CONTEXT.md: 'out of scope / preserved')."

**Filtered-ANN over-fetch pattern to keep (D-03)** — RESEARCH.md Pattern 3 confirms the existing `max(limit * 4, limit)`-style over-fetch-then-filter in `store_search.py`/`store_documents.py` stays; do not delete it speculatively even though native HNSW returns record+score together (deleting `vector_id` int-join is separate from deleting the over-fetch guard).

---

### `src/turing_agentmemory_mcp/store_evidence.py` (PORTED — graph traversal, request-response)

**Analog:** itself, pre-port (the string-built OR-list call sites)

**Pattern to replace (RESEARCH.md Pattern 4, Don't Hand-Roll table):** every call site building `WHERE (a.id = "x" OR a.id = "y" OR ...)` via `quote()`-escaped string-joining (`_expand_entity_evidence`, `_fact_sources_by_ids`, `_community_sources_by_ids`, `_memory_rows_for_ids`, `_existing_entity_ids`) becomes a bound `WHERE id IN :ids` with a JSON array parameter:
```sql
-- target shape (RESEARCH.md, confirm exact ArcadeDB array-param support in spike)
SELECT id, source_memory_id, confidence FROM Fact
WHERE user_identifier = :user_identifier AND id IN :fact_ids AND status = 'active'
```
This removes the manual escaping entirely — no analog needed beyond `provider_config`'s existing "never hand-build what a library gives you" ethos already followed in `embeddings.py`/`rerank.py` for HTTP param encoding (they use `json.dumps` on structured payloads rather than string-building JSON by hand).

---

### `src/turing_agentmemory_mcp/store_chunking.py` (PORTED — batch query builder)

**Analog:** itself, pre-port

Small file (180 LOC pre-port, most headroom of the group) — the `NEXT_CHUNK` MATCH traversal ports per D-05's SQL-vs-Cypher spike choice; no LOC-budget risk here, safe to inline the ported query builder without extracting a sibling module.

---

### `src/turing_agentmemory_mcp/store_rebuild.py` (PORTED — vector projection rebuild, batch)

**Analog:** itself, pre-port for the graph-write shape; `store_core.py`'s `_load_vectors` (lines 361-379) for the "write vectors as a distinct load step, not inline with graph writes" convention:
```python
def _load_vectors(
    self, index_name: str, rows: list[tuple[int, list[float]]], stem: str
) -> None:
    if not rows:
        return
    self._ensure_vector_index(index_name)
    with self._span("vector.load", {...}):
        filename = f"{cypher_var(stem)}_{int(time.time() * 1000)}.csv"
        path = self.data_dir / filename
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for vid, vec in rows:
                handle.write(str(vid))
                ...
        self._query(f'LOAD VECTOR FROM "{filename}" IN {index_name}', operation="vector.load")
```
**This entire CSV-file-based vector-load mechanism is TuringDB-specific and retires** (server-side CSV loading was a TuringDB constraint per `.claude/CLAUDE.md`'s Constraints section — "no longer applies"). ArcadeDB's `LSM_VECTOR` stores vectors as record properties written inline via `CREATE VERTEX ... CONTENT {"embedding": [...]}` or `UPDATE ... SET embedding = [...]` — no separate CSV-load step. **No same-repo analog exists for the D-07 versioned atomic-swap mechanism itself** (see "No Analog Found" below) — this is new logic, not a port.

---

### `src/turing_agentmemory_mcp/store_utils.py` / `ids.py` (PORTED — deletions)

**Analog:** itself — this is a deletion-only mapping, not a rewrite

**Dead code to delete** (`store_utils.py` lines 15, 198-216):
```python
from turing_agentmemory_mcp.ids import cypher_var, quote, vector_id   # drop `vector_id`

@staticmethod
def _memory_vector_id(user_identifier: str, memory_id: str) -> int:
    return vector_id("memory", f"{user_identifier}:{memory_id}")

@staticmethod
def _entity_vector_id(user_identifier: str, entity_id: str) -> int:
    return vector_id("entity", f"{user_identifier}:{entity_id}")

@staticmethod
def _fact_vector_id(user_identifier: str, fact_id: str) -> int:
    return vector_id("fact", f"{user_identifier}:{fact_id}")

@staticmethod
def _community_vector_id(user_identifier: str, community_id: str) -> int:
    return vector_id("community", f"{user_identifier}:{community_id}")

@staticmethod
def _document_vector_id(user_identifier: str, chunk_id: str) -> int:
    return vector_id("chunk", f"{user_identifier}:{chunk_id}")
```
And `ids.py` lines 15-18 (`vector_id()` itself). **Keep** `stable_id()` (lines 9-12) and `cypher_var()` (lines 21-26) unchanged — both stay canonical (invariant #3, D-07/D-09 naming). `quote()` (lines 29-36) is retired in favor of bound params per Pitfall 2 — delete only once every call site (`store_core.py:288-302`, `store_documents.py:15`, `store_utils.py:15,41`) has migrated to bound params; do not delete it first and break the pre-port callers mid-refactor.

---

### `compose.yaml` — new `arcadedb` service (config, request-response healthcheck)

**Analog:** `turingdb`/`turingdb-volume-init` (lines 4-75)

**Hardening pattern to inherit verbatim:**
```yaml
turingdb:
  ...
  environment:
    - HOME=/tmp
    - XDG_CACHE_HOME=/tmp/.cache
    - PYTHONPYCACHEPREFIX=/tmp/pycache
  user: "10001:10001"
  init: true
  restart: unless-stopped
  security_opt:
    - no-new-privileges:true
  tmpfs:
    - /tmp
    - /run
  healthcheck:
    test: ["CMD-SHELL", "python - <<'PY'\nfrom turingdb import TuringDB\nTuringDB(...).try_reach(timeout=2)\nPY"]
    interval: 5s
    timeout: 3s
    retries: 80
    start_period: 30s
  deploy:
    resources:
      limits:
        cpus: "4.0"
        memory: 8g
```
Port shape: same non-root `user:`, same `tmpfs: /tmp,/run` for the ArcadeDB cache/temp dirs (Pitfall 3's "/tmp-pinned cache pattern"), same `security_opt`/`init`/`restart` policy, same `deploy.resources.limits` structure (tune values for ArcadeDB, don't copy TuringDB's numbers blind), and an analogous healthcheck — but the healthcheck body must call `arcadedb_client`'s own probe/reachability method (mirrors the `TuringDB(...).try_reach(timeout=2)` idiom) once `arcadedb_client.py` exists, not a TuringDB import. **Add, do not remove** the `turingdb` block (Runtime State Inventory: coexistence through Phase 6, removal is Phase 7/ARC-10).

**Env-wiring pattern to inherit** (`compose.yaml` lines 143-150, inside the `turing-agentmemory-mcp` service):
```yaml
- TURINGDB_URL=http://turingdb:6666
- TURINGDB_HOME=/turing
- TURINGDB_GRAPH=agent_memory
- TURINGDB_MEMORY_INDEX=${TURINGDB_MEMORY_INDEX:-agent_memory_episode_vectors_768}
- TURINGDB_DOCUMENT_INDEX=${TURINGDB_DOCUMENT_INDEX:-agent_memory_document_vectors_768}
```
Add analogous `ARCADEDB_URL`, `ARCADEDB_*_INDEX` (or a single versioned/namespaced-index-prefix var per D-07) entries using the same `${VAR:-default}` templating — additive, never replacing the `TURINGDB_*` block.

## Shared Patterns

### stdlib-only HTTP client convention
**Source:** `src/turing_agentmemory_mcp/embeddings.py` (whole file), `src/turing_agentmemory_mcp/rerank.py` (whole file)
**Apply to:** `arcadedb_client.py` exclusively — this is the *entire* client-construction pattern (dataclass config + `from_env()` + `urllib.request` + exponential-backoff retry loop). No other file in this phase needs this pattern; it is not "shared" in the cross-file sense so much as "this is the one template to clone once."

### `_span(...)` observability wrapper
**Source:** `src/turing_agentmemory_mcp/store_core.py` lines 331-359 (`self._span("turingdb.query", {...})` / `self._span("turingdb.write_transaction", {...})`)
**Apply to:** every ported `store_*.py` mixin and the new `arcadedb_client.py` — every query/command/transaction call must remain wrapped in `self._span(...)` (or an equivalent client-level span if added inside `arcadedb_client.py` itself) so `observability.py`'s span recording keeps working unchanged. Rename span name strings from `turingdb.*` to `arcadedb.*` for accuracy, but do not drop the wrapper.

### `RuntimeSignals.configure_stage(...)` readiness pattern
**Source:** `src/turing_agentmemory_mcp/store_core.py` lines 126-172 (the `self.runtime_signals.configure_stage("graph"/"sparse"/"fusion"/"embedding"/"rerank"/"community", ready=..., identity={...})` calls in `__init__`)
**Apply to:** D-10's readiness/reconnect work and D-09's schema bootstrap — extend this existing stage-registry pattern (add/rewire a `"graph"` stage keyed on ArcadeDB reachability) rather than inventing a parallel health-check mechanism (RESEARCH.md Don't Hand-Roll table, explicitly calls this out).

### Bound-parameter querying (retiring `quote()`)
**Source:** `src/turing_agentmemory_mcp/embeddings.py` lines 123-126 / `rerank.py` lines 155-162 (`json.dumps(payload)` — structured payload building, never hand-escaped string interpolation)
**Apply to:** every ported `store_*.py` query builder — replace every `f'"{quote(value)}"'`-style literal interpolation with a bound `?`/`:named` parameter passed alongside the query string to `arcadedb_client.command()`/`.query()`. This is both an injection-surface fix (Pitfall 2) and matches the existing HTTP-payload-building convention already used for embed/rerank calls.

### Fail-fast dimension validation
**Source:** `src/turing_agentmemory_mcp/store_core.py` lines 241-268 (`_ensure_vector_index`)
**Apply to:** `arcadedb_schema.py`'s D-09 bootstrap routine — same "attempt idempotent create, then verify, raise `ValueError` on mismatch" shape.

## No Analog Found

Files/behaviors with no close in-repo match — genuinely new logic, not a port; planner should treat RESEARCH.md's Architecture Patterns (1-4) and the capabilities doc as the primary reference, gated by the D-02 spike, not this pattern map:

| File/Behavior | Role | Data Flow | Reason |
|----------------|------|-----------|--------|
| D-07 versioned/namespaced index name + atomic-swap-on-rebuild | service (index lifecycle) | batch | No existing code atomically swaps a live index; today's `_load_vectors`/`rebuild_vector_projection` mutate in place (the very bug D-07 fixes) — nothing to copy from, only to replace |
| D-08 `begin`/`command(sqlscript)`/`commit retry N` transaction wrapper with MVCC-conflict retry | service (transaction control) | transactional batch | TuringDB's model (`new_change()`/`CHANGE SUBMIT`/`checkout()`) has no optimistic-concurrency retry concept; the retry-N wrapper is new code, only the *outer* HTTP-retry shape (embeddings.py/rerank.py) is reusable as a convention, not the MVCC-conflict semantics themselves |
| D-02 spike smoke test itself (`arcadedb_client.py`'s committed test harness for the 5 capability unknowns) | test | request-response | No existing spike/smoke-test harness in the repo targets a *new* backend's undocumented syntax; closest precedent is `scripts/e2e_score.py`'s "spin up a temp stack and assert" shape, but that tests the whole MCP surface, not a single client's capability matrix — use it as a *structural* inspiration (temp container + assertions + JSON output) only |
| ArcadeDB native Lucene/`LSM_SPARSE_VECTOR` full-text query syntax (D-04 candidate channels) | service (query builder) | request-response | `sparse_index.py`'s SQLite-FTS5 queries are the closest *conceptual* analog (both are lexical-channel query builders feeding the same RRF), but the SQL/API surface is entirely different — read `sparse_index.py` for the *shape* of "how a lexical channel plugs into `retrieval_fusion.py`," not for syntax to copy |

## Metadata

**Analog search scope:** `src/turing_agentmemory_mcp/` (all `store_*.py` mixins, `embeddings.py`, `rerank.py`, `ids.py`, `store_core.py`, `store_utils.py`), `compose.yaml`, `.planning/research/ARCADEDB-capabilities-for-port.md` (cross-referenced, not treated as a code analog per Pitfall 1)
**Files scanned:** embeddings.py, rerank.py, store_core.py, ids.py, store_documents.py (partial), store_utils.py (full), store_search.py/store_evidence.py/store_chunking.py/store_rebuild.py/store_memory_write.py (LOC-only, sized against the 600-LOC cap), compose.yaml (lines 1-75, 130-150)
**Pattern extraction date:** 2026-07-13
