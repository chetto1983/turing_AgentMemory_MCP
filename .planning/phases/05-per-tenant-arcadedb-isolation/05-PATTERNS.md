# Phase 5: Per-Tenant ArcadeDB Isolation - Pattern Map

**Mapped:** 2026-07-14
**Files classified:** 32 expected new/modified files
**Primary analog search:** 5 strong sources
**Analog coverage:** 31 / 32 files have an exact, self-extension, role, or test-harness match

## Scope Extraction

The file set below is derived from the locked decisions in 05-CONTEXT.md and the
component/test decomposition in 05-RESEARCH.md. A planner may combine a small helper
with its owning module, but must not combine identity, registry, provisioning, and
routing into one file: the repository has a hard 600-line Python limit and these
concerns have different failure boundaries.

## File Classification

### Production code

| New/Modified File | Role | Data Flow | Closest Existing Analog | Match Quality |
|---|---|---|---|---|
| src/turing_agentmemory_mcp/tenant_identity.py | utility/config | transform | src/turing_agentmemory_mcp/provider_config.py; document_jobs.py:176-186 | role-match |
| src/turing_agentmemory_mcp/tenant_registry.py | model/store | CRUD, batch | src/turing_agentmemory_mcp/document_jobs.py | exact role/data-flow |
| src/turing_agentmemory_mcp/tenant_provisioning.py | service | request-response, CRUD | src/turing_agentmemory_mcp/arcadedb_client.py plus arcadedb_schema.py | role-match |
| src/turing_agentmemory_mcp/tenant_router.py | provider/service | request-response, event-driven | src/turing_agentmemory_mcp/document_job_manager.py | partial role-match |
| src/turing_agentmemory_mcp/arcadedb_client.py | service | request-response | existing file | self-extension |
| src/turing_agentmemory_mcp/arcadedb_schema.py | migration/service | batch | existing bootstrap() | self-extension |
| src/turing_agentmemory_mcp/store_core.py | provider/store | request-response, batch | existing constructor/query choke points | self-extension |
| src/turing_agentmemory_mcp/server.py | config/provider | request-response | existing store_from_env()/create_mcp_app() | self-extension |
| src/turing_agentmemory_mcp/server_memory_tools.py | route/controller | request-response | existing tool registration closure | self-extension |
| src/turing_agentmemory_mcp/server_document_tools.py | route/controller | request-response, file-I/O | existing tool registration closure | self-extension |
| src/turing_agentmemory_mcp/document_job_manager.py | service | event-driven, file-I/O | existing per-job process path | self-extension |
| src/turing_agentmemory_mcp/document_jobs.py | model/store | CRUD, batch | existing short SQLite transactions | self-extension |
| src/turing_agentmemory_mcp/file_upload.py | service/store | file-I/O, CRUD | existing tenant-owned upload sessions | self-extension |
| src/turing_agentmemory_mcp/store_memory_queries.py | utility | transform, CRUD | existing safe scoped mutations in same file | self-extension |
| src/turing_agentmemory_mcp/store_documents_queries.py | utility | transform, CRUD | existing safe scoped mutations in same file | self-extension |
| src/turing_agentmemory_mcp/store_rebuild_queries.py | utility | transform, batch | existing user-scoped rebuild statements | self-extension |
| src/turing_agentmemory_mcp/store_retrieval_queries.py | utility | transform, request-response | existing user-scoped retrieval statements | audit/modify-if-gap |

### Tests

| New/Modified File | Role | Data Flow | Closest Existing Analog | Match Quality |
|---|---|---|---|---|
| tests/test_tenant_identity.py | test | transform | tests/test_ids.py plus provider config tests | role-match |
| tests/test_tenant_registry.py | test | CRUD, concurrent batch | tests/test_document_jobs.py | exact role/data-flow |
| tests/test_tenant_provisioning.py | test | request-response, fault injection | tests/test_arcadedb_client_transport.py | exact harness style |
| tests/test_tenant_router.py | test | concurrent request-response | tests/test_arcadedb_tenant_isolation.py | role-match |
| tests/test_tenant_query_scope.py | test | transform, request-response | tests/test_arcadedb_tenant_isolation.py and test_arcadedb_client_transport.py | role-match |
| tests/test_arcadedb_physical_tenant_isolation.py | integration test | concurrent CRUD, request-response | no single analog; combine existing isolation fake with Phase 4 live harness | no complete analog |
| tests/test_document_jobs.py | test | CRUD | existing file | self-extension |
| tests/test_document_job_manager.py | test | event-driven, file-I/O | existing file | self-extension |
| tests/test_document_file_pipe.py | test | file-I/O, request-response | existing DocumentUploadStore coverage | self-extension |
| tests/test_arcadedb_client_transport.py | test | request-response | existing scripted transport | self-extension |
| tests/test_compose_config.py | test | config | existing compose contract assertions | self-extension |

### Deployment and documentation

| New/Modified File | Role | Data Flow | Closest Existing Analog | Match Quality |
|---|---|---|---|---|
| .env.example | config | config | existing ARCADEDB_* block | self-extension |
| compose.yaml | config | config | existing MCP environment/volume wiring | self-extension |
| docs/architecture.md | documentation | transform | existing backend and tenant-scope sections | self-extension |
| CHANGELOG.md | documentation | transform | existing milestone entries | self-extension |

## Pattern Assignments

### src/turing_agentmemory_mcp/tenant_identity.py

**Primary analog:** src/turing_agentmemory_mcp/provider_config.py

Use the package's small typed-function style and explicit environment injection. The
naming key is not an optional provider secret, so copy the direct environment access
shape but replace fallback behavior with fail-fast base64 parsing and length checks.

**Environment helper pattern** (provider_config.py:8-16):

~~~python
def provider_env(name: str, *, default: str = "") -> str:
    return os.environ.get(name, default)


def provider_secret(prefix: str, suffix: str = "API_KEY") -> str:
    specific = os.environ.get(f"{prefix}_{suffix}")
    if specific:
        return specific
    return os.environ.get(f"PROVIDER_{suffix}", "")
~~~

**Deterministic byte-material pattern** (document_jobs.py:176-186):

~~~python
@staticmethod
def idempotency_key(
    *,
    user_identifier: str,
    document_id: str,
    filename: str,
    sha256: str,
) -> str:
    identity = document_id or Path(filename).name
    material = "\0".join((user_identifier, identity, sha256)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
~~~

Copy the explicit UTF-8 byte construction, not the unkeyed hash. Phase 5 must use the
research-locked HMAC-SHA-256 construction and full name format
agentmem_t_v1_<64 lowercase hex characters>. Keep validation, key parsing,
fingerprinting, and derivation in this one module.

**Do not copy:** provider defaults or any call to strip() on user_identifier. The
central validator must reject leading/trailing whitespace, control-category code
points, and lone surrogates without returning a transformed string.

### src/turing_agentmemory_mcp/tenant_registry.py

**Analog:** src/turing_agentmemory_mcp/document_jobs.py

The registry should copy the connection-per-operation, explicit transaction, durable
WAL, schema metadata, and fail-fast version-check conventions.

**Initialization and metadata binding** (document_jobs.py:26-88):

~~~python
class DocumentJobStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS document_job_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            version_row = connection.execute(
                "SELECT value FROM document_job_meta WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is not None and int(version_row["value"]) != DOCUMENT_JOB_SCHEMA_VERSION:
                connection.rollback()
                raise RuntimeError(...)
            connection.commit()
~~~

For tenant_registry.py, the singleton metadata comparison must cover both naming
version and naming-key fingerprint before any tenant row can be created. The tenant
table stores only opaque database name/digest, provisioning|ready state, and
timestamps. Never add raw user_identifier.

**Atomic transaction and connection lifecycle** (document_jobs.py:531-552):

~~~python
@contextmanager
def _transaction(self):
    with self._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        connection.commit()

@contextmanager
def _connection(self):
    connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    try:
        yield connection
    finally:
        connection.close()
~~~

**Test structure to copy** (tests/test_document_jobs.py:32-44):

~~~python
def test_enqueue_is_idempotent_and_get_is_tenant_scoped(tmp_path: Path) -> None:
    store = DocumentJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()

    first = enqueue_job(store)
    duplicate = enqueue_job(store, staged_path="/different/temporary/path.pdf")
    other_tenant = enqueue_job(store, user_identifier="bob")

    assert duplicate.job_id == first.job_id
    assert other_tenant.job_id != first.job_id
    assert store.get(first.job_id, user_identifier="alice") == first
    assert store.get(first.job_id, user_identifier="bob") is None
~~~

Adapt this to initialize/reopen/corruption/key-drift/state-transition tests and add a
raw-byte assertion that exact test identifiers never occur in the SQLite file.

### src/turing_agentmemory_mcp/tenant_provisioning.py

**Analogs:** src/turing_agentmemory_mcp/arcadedb_client.py and arcadedb_schema.py

Derive a client with dataclasses.replace(base_client, database=database_name); do not
mutate the shared client. The existing frozen client establishes the configuration
convention.

**Immutable client configuration** (arcadedb_client.py:75-115):

~~~python
@dataclass(frozen=True)
class ArcadeDBClient:
    base_url: str = DEFAULT_BASE_URL
    database: str = "agent_memory"
    username: str = "root"
    password: str = ""
    timeout_s: float = 30.0
    max_attempts: int = 3
    retry_base_s: float = 0.5
    commit_retries: int = 3

    @classmethod
    def from_env(cls) -> ArcadeDBClient:
        return cls(
            base_url=provider_env("ARCADEDB_URL", default=DEFAULT_BASE_URL),
            database=provider_env("ARCADEDB_DATABASE", default="agent_memory"),
            ...
        )
~~~

**Existing create primitive** (arcadedb_client.py:248-257):

~~~python
def ensure_database(self) -> None:
    decoded, _session = self._server_command("list databases")
    existing = decoded.get("result")
    if isinstance(existing, list) and self.database in existing:
        return
    self._server_command(f"create database {self.database}")
~~~

Do not treat ensure_database() returning as tenant readiness. Extend the client with
the narrow server-level existence/create primitives the provisioner needs, while the
provisioner owns registry reconciliation, create-race interpretation, bootstrap,
manifest verification, and ready-last promotion.

**Idempotent schema pattern** (arcadedb_schema.py:194-218, 286-291):

~~~python
def bootstrap(client: SchemaClient, *, dimensions: int, version: int = 1) -> SchemaBootstrapConfig:
    config = SchemaBootstrapConfig(dimensions=dimensions, version=version)
    for vertex_type in VERTEX_TYPES:
        _create_type_if_missing(client, "VERTEX", vertex_type)
    for edge_type in EDGE_TYPES:
        _create_type_if_missing(client, "EDGE", edge_type)
    _bootstrap_user_identity(client)
    for type_name in STABLE_ID_TYPES:
        _bootstrap_stable_id(client, type_name)
    for type_name in VECTOR_TYPES:
        _bootstrap_vector_channel(client, type_name, config)
        _bootstrap_lexical_channel(client, type_name)
        _bootstrap_full_text_channel(client, type_name)
    return config

def _create_index_idempotent(client: SchemaClient, statement: str) -> None:
    try:
        client.command(statement)
    except Exception as exc:
        if _ALREADY_EXISTS_MARKER not in str(exc).lower():
            raise
~~~

Add the manifest type/property/index bootstrap here only if it is part of the common
schema contract. Keep manifest read/write/compare policy in tenant_provisioning.py.
The manifest insert is the final tenant-database durable step and a duplicate insert
is a race requiring exact re-read comparison.

**Retry/error pattern** (arcadedb_client.py:299-317):

~~~python
except HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
    if (
        exc.code in _RETRYABLE_HTTP_CODES
        and not is_mvcc_conflict(detail)
        and attempt + 1 < self.max_attempts
    ):
        time.sleep(self.retry_base_s * (2**attempt))
        continue
    raise RuntimeError(f"ArcadeDB HTTP {exc.code} at {path}: {detail}") from exc
except (URLError, TimeoutError, OSError) as exc:
    if attempt + 1 < self.max_attempts:
        time.sleep(self.retry_base_s * (2**attempt))
        continue
    raise RuntimeError(f"ArcadeDB unavailable at {self.base_url}") from exc
~~~

Provisioning retries must add bounded jitter and must not retry identity, registry
metadata, manifest, or schema-version mismatches. Ensure new errors expose opaque
database identity only, never the exact tenant identifier.

**Scripted fault-test pattern** (tests/test_arcadedb_client_transport.py:144-174):

~~~python
transport = _ScriptedUrlopen(
    [
        _FakeResponse(status=204, session_id="AS-1"),
        _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),
        _http_error(503, _CONFLICT_BODY),
        _FakeResponse(status=204),
        _FakeResponse(status=204, session_id="AS-2"),
        _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),
        _FakeResponse(status=204),
    ]
)
monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
~~~

Use the same ordered script/call-capture style for a fault after every provisioning
boundary and assert the next request resumes or fails closed according to registry
state.

### src/turing_agentmemory_mcp/tenant_router.py and store_core.py

**Closest analog:** src/turing_agentmemory_mcp/document_job_manager.py

The manager demonstrates constructor validation, injected factories, thread state,
and content-free runtime status:

~~~python
# document_job_manager.py:25-57
class DocumentIngestManager:
    def __init__(
        self,
        jobs: DocumentJobStore,
        *,
        staging_root: str | Path,
        store_factory: StoreFactory,
        ...
    ) -> None:
        ...
        self.store_factory = store_factory
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
~~~

Copy dependency injection and explicit thread ownership. Do not copy the background
worker's process-global store cache:

~~~python
# document_job_manager.py:291-300 -- anti-pattern for Phase 5
def _run(self) -> None:
    memory: Any | None = None
    while not self._stop.is_set():
        try:
            if memory is None:
                memory = self.store_factory()
            processed = self.process_next(worker_id=self.worker_id, memory=memory)
        except Exception:
            memory = None
            processed = None
~~~

Change the manager contract to a tenant resolver and resolve the exact
job.user_identifier for each claimed job. Tests already inject lightweight memory
objects; preserve that seam with a Resolver Protocol/static adapter.

No existing module implements the required per-key Future single-flight plus bounded
LRU/idle TTL. Use the algorithm in 05-RESEARCH.md as the canonical pattern:

- protect only cache metadata and the in-flight map with one RLock;
- key both structures by opaque database name;
- wait on Future.result() outside the lock;
- provision outside the lock;
- remove the exact in-flight Future in finally;
- eviction only removes the router's reference.

store_core.py currently mixes tenant-local and shared state:

- client, _schema_bootstrapped, runtime_signals, readiness: tenant-local;
- embedder, reranker, entity/memory processors, community detector, observer,
  redactor, audit sink: shared.

Extract a frozen shared dependency/config bundle or equivalent explicit factory. A
tenant view must receive a permanently bound client and its own schema/readiness
latch. Never reassign self.client after construction.

### server.py, server_memory_tools.py, and server_document_tools.py

The current assembly is a singleton closure:

~~~python
# server.py:187-199
def create_mcp_app(
    store: TuringAgentMemory | None = None,
    *,
    upload_store: DocumentUploadStore | None = None,
    document_manager: DocumentIngestManager | None = None,
    start_document_worker: bool | None = None,
) -> FastMCP:
    production_store = store is None
    memory = store or store_from_env()
    uploads = upload_store or document_upload_store_from_env()
    manager = document_manager
    if manager is None and production_store:
        manager = document_ingest_manager_from_env(store_factory=store_from_env)
~~~

~~~python
# server_memory_tools.py:13-17
def register_memory_tools(
    app: FastMCP,
    memory: TuringAgentMemory,
    tool_span: Callable[[str], Any],
) -> None:
~~~

~~~python
# server_document_tools.py:15-20
def register_document_tools(
    app: FastMCP,
    memory: TuringAgentMemory,
    uploads: DocumentUploadStore,
    document_manager: Callable[[], DocumentIngestManager],
    tool_span: Callable[[str], Any],
) -> None:
~~~

Replace the singleton memory argument with a resolver protocol whose resolve(exact
identifier) method returns an immutable tenant-bound view. Every tool resolves once
at the operation boundary, then passes the same unchanged identifier to the existing
store method. Preserve direct test injection by wrapping an injected static store.

Global health must call base server reachability plus router key/config/registry
readiness. Tenant health/diagnostics must be an explicit non-provisioning router
operation; do not call resolve() from a health probe.

There is no Phase 5 auth/guard analog to add. Existing bearer-token auth remains
unchanged, and OIDC principal-to-tenant derivation is explicitly deferred to Phase
10. Do not infer tenant identity from auth claims in this phase.

### document_jobs.py, document_job_manager.py, and file_upload.py

These exact-identity anti-patterns must all route through tenant_identity.validate:

~~~python
# document_jobs.py:108
tenant = user_identifier.strip()

# document_job_manager.py:83-88
key = self.jobs.idempotency_key(
    user_identifier=user_identifier.strip(),
    ...
)

# file_upload.py:67
tenant = user_identifier.strip()

# file_upload.py:177-182
session = self._sessions.get(upload_id)
if session is None:
    raise ValueError("upload_id is unknown")
if session.user_identifier != user_identifier.strip():
    raise ValueError("upload tenant does not match user_identifier")
~~~

Validate at each public persistence/lookup boundary and retain the exact unchanged
string. The registry remains pseudonymous, but document jobs and canonical records
still carry exact user_identifier because application-layer predicates are mandatory.

Preserve the manager's safe error translation pattern (document_job_manager.py:
197-215, 259-266): deterministic invalid input becomes a stable non-retryable error;
availability failures become bounded retryable errors; raw exception messages do not
escape.

### Query builder files

Copy the safe same-file pattern: every stable record ID is paired with exact
user_identifier in both statement and bound params.

~~~python
# store_memory_queries.py:291-294
"UPDATE Memory SET "
+ ", ".join(set_terms)
+ " WHERE id = :id AND user_identifier = :user_identifier",
params,
~~~

~~~python
# store_documents_queries.py:258-260
"UPDATE Document SET status = 'deleted', updated_at = :updated_at "
"WHERE id = :id AND user_identifier = :user_identifier",
{"id": document_id, "user_identifier": user_identifier, "updated_at": updated_at},
~~~

Repair the current edge endpoint gaps:

~~~python
# store_memory_queries.py:106-108 -- target Memory lacks tenant predicate
"CREATE EDGE HAS_MEMORY FROM (SELECT FROM User WHERE identifier = :identifier) "
"TO (SELECT FROM Memory WHERE id = :id)",
{"identifier": user_identifier, "id": memory_id},

# store_documents_queries.py:174-176 -- both endpoints lack tenant predicate
"CREATE EDGE HAS_CHUNK FROM (SELECT FROM Document WHERE id = :document_id) "
"TO (SELECT FROM Chunk WHERE id = :chunk_id) SET ordinal = :ordinal",
{"document_id": document_id, "chunk_id": chunk_id, "ordinal": ordinal},

# store_rebuild_queries.py:334-335 -- Entity endpoint lacks tenant predicate
f"CREATE EDGE IN_COMMUNITY FROM (SELECT FROM Entity WHERE id = :{member_param}) "
f"TO {community_var};"
~~~

Apply the same rule to document_edge_statement, next_chunk_edge_statement,
projection edge builders, community replacement, and record-ID staging updates.
FROM and TO subqueries must each bind the same exact tenant; checking only the outer
statement is insufficient.

tests/test_tenant_query_scope.py should maintain an explicit catalog of query-builder
callables with a narrow exemption list for schema, manifest, and server lifecycle
commands. A new unclassified builder must fail the test. Pair static/catalog checks
with a spy transport assertion on params and adversarial A-uses-B-ID execution.

### Concurrent and live isolation tests

**Fake client pattern** (tests/test_arcadedb_tenant_isolation.py:61-110):

~~~python
class _ConcurrentFakeArcadeDBClient:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: list[dict[str, object]] = []

    def run_in_transaction(self, body: Any, *, commit_retries: int | None = None) -> Any:
        with self._lock:
            return body("session")

    def query(...):
        with self._lock:
            return self._select(statement, params or {})
~~~

**Interleaved workload pattern** (tests/test_arcadedb_tenant_isolation.py:216-248):

~~~python
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = [
        pool.submit(reader, "alice"),
        pool.submit(reader, "bob"),
        pool.submit(writer, "alice"),
        pool.submit(writer, "bob"),
    ]
    for future in futures:
        future.result()

for tenant, seen_identifiers in observed:
    assert all(identifier == tenant for identifier in seen_identifiers)
~~~

Retain this deterministic layer and extend it for same-tenant single flight,
different-tenant overlap, waiter error fan-out, eviction, active references, manifest
mismatch, and missing-ready failures.

There is no single complete analog for
tests/test_arcadedb_physical_tenant_isolation.py. Build it from:

- the concurrent workload/assertion pattern above;
- the pinned-container lifecycle and CI skip convention identified in
  tests/test_arcadedb_chaos_restart.py and tests/conftest.py;
- the database-qualified transport assertions in
  tests/test_arcadedb_client_transport.py:89-115;
- the mandatory A/B/C, identical payload, unique canary, foreign-ID, direct database
  inspection, manifest, registry-byte, log, diagnostic, eviction, and restart
  contract in 05-RESEARCH.md.

## Shared Patterns

### Validation

**Apply to:** every MCP tool resolver, store public method, document job persistence,
upload session operation, router, provisioner.

One central function returns the unchanged valid str or raises ValueError. Do not
normalize, trim, case-fold, or Unicode-normalize. Validate before registry, cache,
logs, or server mutation.

### Database binding

**Source:** arcadedb_client.py:75-90

ArcadeDBClient is frozen and request-scoped. Derive a per-database instance with
dataclasses.replace. The opaque database name is the cache/in-flight/diagnostic key;
the exact user identifier remains the application-layer predicate value.

### Transaction and durability

**Sources:** document_jobs.py:531-552; arcadedb_schema.py:194-218

Use short SQLite BEGIN IMMEDIATE transactions and connection-per-operation. Database
creation/schema/manifest reconciliation is idempotent. Ready manifest is written last;
registry ready is promoted only after exact manifest re-read.

### Error handling and retries

**Sources:** arcadedb_client.py:299-317; document_job_manager.py:197-215

Retry only classified network/conflict/retryable-5xx failures with a finite budget.
Validation, key/version, registry corruption, missing-ready database, wrong client,
and manifest mismatch fail deterministically. Public errors and new logs expose only
opaque database identity/fingerprint.

### Test dependency policy

Local live tests may issue an explicit Docker-unavailable skip. Under CI=true,
tests/conftest.py converts skips into failures. Reuse this existing gate; do not add
a second skip policy.

## No Complete Analog Found

| File/Pattern | Role | Data Flow | Reason / Planner Source |
|---|---|---|---|
| tenant_identity.py HMAC naming contract | utility | transform | No keyed tenant-name implementation exists; use 05-RESEARCH.md and Python stdlib hmac/hashlib |
| tenant_router.py single-flight + LRU/TTL | service/provider | concurrent request-response | Existing manager has threading/factory seams but no per-key Future coordination or bounded cache; use 05-RESEARCH.md algorithm |
| test_arcadedb_physical_tenant_isolation.py | integration test | concurrent CRUD | No current test combines three physical databases, direct inspection, IDOR, leakage, cache, and restart proof |

## Planner Warnings

- ARCADEDB_DATABASE=agent_memory is legacy input, not a tenant-data fallback.
- A duplicate create response proves existence only; bootstrap and manifest
  reconciliation remain mandatory.
- A ready registry row plus missing database is data-loss evidence and must not
  silently create a new empty database.
- Cache eviction must never close, drop, or mutate the database/view.
- Tenant diagnostics must not provision.
- Physical separation never removes _require_user or query predicates.
- Do not store raw user_identifier in registry, cache keys, provisioning logs, or
  tenant diagnostics.
- Preserve exact user_identifier in canonical records, job rows, upload ownership,
  and all bound query params.

## Metadata

**Analog search scope:** src/turing_agentmemory_mcp and tests
**Files scanned:** 129 (63 package files, 66 tests)
**Primary analogs selected:**

1. src/turing_agentmemory_mcp/provider_config.py
2. src/turing_agentmemory_mcp/document_jobs.py
3. src/turing_agentmemory_mcp/arcadedb_client.py
4. src/turing_agentmemory_mcp/document_job_manager.py
5. tests/test_arcadedb_tenant_isolation.py

Corresponding tests and modification targets were inspected for exact line-level
patterns. Primary analog search stopped after these five strong families.

**Pattern extraction date:** 2026-07-14
**Mode:** generic-agent workaround for gsd-pattern-mapper
