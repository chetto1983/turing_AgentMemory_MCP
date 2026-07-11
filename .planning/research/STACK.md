# Stack Research

**Domain:** Backend/infra technology selection for a stabilization milestone on an existing TuringDB-backed Agent Memory MCP server (Python 3.11+, FastMCP, Docker Compose)
**Researched:** 2026-07-11
**Confidence:** MEDIUM overall (all findings are cross-checked web sources, not vendor-verified docs pulled via Context7 — see Sources). The ArcadeDB adequacy verdict (Q2) is the load-bearing finding; treat it as MEDIUM confidence and re-validate against the actual ArcadeDB version pinned at implementation time.

---

## THE Verdict: Does ArcadeDB's native HNSW vector + Lucene full-text subsume dedicated external search/vector systems?

**YES, for the ArcadeDB backend specifically — do not add a separate external search engine or vector DB when ArcadeDB is the selected driver.** Build the ArcadeDB driver to use native indexes for everything. Do not change the TuringDB driver's existing SQLite-FTS5-projection design (out of scope; see Scope note below).

**Evidence:**

1. **Full-text is not a bolt-on in ArcadeDB — it *is* Lucene.** ArcadeDB's full-text index is built directly on Apache Lucene: configurable analyzers (English stemming, stop-words), native tunable BM25 scoring with per-field boosts, and the full Lucene query syntax (boolean/phrase/wildcard/fuzzy) via `SEARCH_INDEX()`/`SEARCH_FIELDS()`. This is the same underlying library Elasticsearch/OpenSearch/Solr wrap — ArcadeDB just embeds it in-process instead of running it as a separate cluster. For a tenant-scoped agent-memory workload (not web-scale full-text search across billions of documents), the *retrieval quality ceiling* of embedded Lucene and clustered Lucene (via ES/OpenSearch) is the same; what differs is operational surface area, and embedded wins there. Critically, this index is **ACID-integrated** with the graph/vector writes — it eliminates the entire class of bug this project already has in the SQLite-FTS5 projection (`sparse_index.py` outbox prepare/commit/replay crash-consistency, flagged as a Fragile Area in CONCERNS.md).
2. **Vector search is real but younger — acceptable at this project's scale, not proven at hyperscale.** ArcadeDB uses JVector (HNSW or Vamana/DiskANN) with COSINE/DOT_PRODUCT/EUCLIDEAN similarity and INT8/BINARY quantization, ACID-integrated, queryable via `vector.neighbors()`/`vector.cosineSimilarity()` in SQL. Release v25.12.1 (Dec 2025) fixed critical INT8/BINARY quantization correctness bugs; v26.5.1 (2026) added a sparse vector index and hybrid retrieval. A community benchmark thread (GitHub `ArcadeData/arcadedb#3140`) shows the team was still validating correctness at ~1M vectors before moving to 10M-scale testing as of mid-2026. This is materially less battle-tested than a dedicated engine like Qdrant, but it is **not materially less mature than what this project already runs** — the current TuringDB integration already has known rough edges documented in CONCERNS.md (over-fetch-then-filter, no predicate pushdown, app-layer score sorting because "composed `VECTOR SEARCH ... MATCH ...` rows do not preserve vector order"). Swapping one young-but-native vector engine for another young-but-native vector engine, in exchange for gaining ACID integration and eliminating an entire external system, is a net win at this project's scale (tenant-scoped agent memories + document chunks, not a billion-vector consumer search product).
3. **Multi-tenancy makes the "subsumes" case stronger, not weaker.** ArcadeDB server mode is natively multi-database: one cluster serves many independent databases with unified security. If the ArcadeDB driver provisions **one database per tenant** (see Q1 below) rather than a shared database with a `user_identifier` column, every tenant's vector index and full-text index is **physically isolated by construction** — a guarantee that a shared-collection vector DB (Qdrant payload-filtering) or shared-cluster search engine (ES/OpenSearch index-per-tenant) has to engineer and continuously verify. This directly retires two CONCERNS.md scaling limits at once: "SQLite Single-File Limit" (all tenants' FTS in one file) and "Single TuringDB Graph Instance" (no multi-tenancy isolation at the DB level).
4. **Architectural simplification, not just feature parity.** Adding ArcadeDB as a coexisting backend already means running a second database technology. Also standing up Elasticsearch/OpenSearch *and* Qdrant/Weaviate/Milvus behind it would mean the "one-command Docker stack" goal (Thrust 1) ships 4+ stateful services instead of 1, each needing its own healthcheck, backup story, and tenant-isolation logic. That directly contradicts this milestone's own stated goal.

**Conditions on this verdict (must hold, or re-open the question):**

- **Scale ceiling:** if any single tenant is projected to exceed roughly 1–5M vectors or the full-text corpus exceeds what a single embedded Lucene segment set handles comfortably (very large multi-tenant document corpora, not just memories), re-evaluate — this is exactly the same "Scaling Limits" pattern CONCERNS.md already flags for the current TuringDB setup, so treat it as a documented future scaling limit for the ArcadeDB driver too, not a blocker now.
- **Filtered vector search correctness:** confirm ArcadeDB's filtered vector search (added in recent releases per `#3071`/`#3072`) supports the same status/expiry/tenant-predicate-then-rank pattern `store.py` uses today, before removing the SQLite FTS5 pattern for the ArcadeDB path.
- **This verdict is scoped to the ArcadeDB driver only.** TuringDB has no native full-text engine — that gap is *why* the SQLite FTS5 projection exists today — so the repository/driver interface must let each backend implement search differently: TuringDB driver keeps its existing SQLite-FTS5-projection + TuringDB-vector design unchanged (PROJECT.md explicitly puts "rewriting the retrieval-fusion algorithm" out of scope), ArcadeDB driver uses native Lucene FTS + native JVector instead of a separate projection.

**Confidence: MEDIUM.** Verdict rests on cross-checked but non-vendor-verified web sources (GitHub discussion threads, blog posts, official docs pages fetched via search snippets, not a hands-on benchmark run by this research). Recommend a cheap validation spike as the first task of the ArcadeDB phase: load a representative tenant's memory+document volume into a single-node ArcadeDB container and run the existing E2E score gate's retrieval assertions against it before committing further phases to this architecture.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| ArcadeDB | 26.7.1 (`arcadedata/arcadedb:26.7.1` Docker image) | Coexisting graph+vector+full-text backend, selectable alongside TuringDB via the new driver interface | Multi-model (graph/document/vector/full-text) in one ACID store; native Lucene FTS + JVector HNSW subsume separate search/vector systems for this workload (see verdict above); passed 34/34 Jepsen tests for HA correctness; natively multi-database for tenant isolation |
| ArcadeDB driver: HTTP/JSON API via stdlib `urllib` | N/A (own thin module) | Python↔ArcadeDB communication for the new driver | **Follow this codebase's existing convention exactly**: `embeddings.py` and `rerank.py` already talk to OpenAI-compatible HTTP endpoints using `urllib.request` with zero extra HTTP client dependency, not `httpx`/`requests`. Do the same for ArcadeDB — a thin `arcadedb_client.py` wrapping ArcadeDB's native HTTP/JSON API (`/api/v1/command`, `/api/v1/query`, `/api/v1/begin`/`/commit` for transactions) keeps dependency surface unchanged and matches CLAUDE.md's "follow existing patterns" and "at-risk dependencies" concerns (adding a third HTTP client library would itself become a new at-risk dependency) |
| Garage | 2.2.0+ (`dxflrs/garage` Docker image) | S3-compatible object storage for document staging (replaces local filesystem in `AGENTMEMORY_DOCUMENT_STAGING_ROOT`) | **MinIO Community Edition is no longer a safe default choice as of 2026** — see "What NOT to Use" below. Garage is a 30MB static Rust binary, actively maintained, boto3-compatible (`endpoint_url` override), designed exactly for this project's scale (small/medium self-hosted, single Docker Compose deployment), and its "per-access-key-per-bucket" permission model maps cleanly onto per-tenant or per-deployment staging buckets |
| boto3 | current (pip-resolved) | Python S3 client for Garage | Industry-standard S3 SDK; works unmodified against Garage by setting `endpoint_url`; no code changes needed if the team ever migrates to real AWS S3 later |
| Keycloak | 26.7.0 (`quay.io/keycloak/keycloak:26.7.0`) | Self-hosted OIDC identity provider for OAuth/OIDC auth | Most direct precedent with FastMCP specifically (working Medium/GitHub examples of FastMCP+Keycloak OIDC integration exist); mature, dockerizable, supports the standard `/.well-known/openid-configuration` discovery FastMCP's `OIDCProxy` consumes directly |
| fastmcp `OIDCProxy` / `RemoteAuthProvider` (built into the already-pinned `fastmcp>=3.4,<4`) | already in range | Replace static bearer tokens (`StaticTokenVerifier`) with real OAuth/OIDC | FastMCP already ships OAuth support (`OAuthProxy` since fastmcp 2.12, `OIDCProxy` extending it for discovery-capable IdPs, pre-built provider classes for GitHub/Google/Azure/Auth0/Okta/WorkOS) — **no new dependency needed**, only a `server.py` auth-wiring change. Verify the exact classes are importable in the pinned release range as the first task (see Version Compatibility) |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `arcadedb-python` (stevereiner) | latest on PyPI, Beta status | Optional faster-path Python client for ArcadeDB, wraps the same HTTP REST API | Only if implementation velocity matters more than dependency risk — it is explicitly "Development Status :: 4 - Beta", third-party (not ArcadeData-official), and would be a second at-risk dependency the CONCERNS.md pattern is trying to retire. Prefer the thin stdlib-`urllib` driver above; fall back to this only if the hand-rolled driver proves too costly to build against ArcadeDB's transaction API |
| `psycopg` (if Postgres-wire path chosen instead) | n/a — **not recommended**, listed for completeness | Alternative ArcadeDB connectivity via its Postgres wire-protocol plugin (port 5432) | Only relevant if the team wants to point generic BI tools (Grafana, Metabase, DBeaver) at ArcadeDB directly for ops visibility — not needed for the MCP server's own driver, and it would add a new heavyweight dependency + only expose SQL, not the Cypher/Gremlin/vector-function surface the HTTP/JSON API exposes uniformly |
| `authlib` | current | Only if a custom/non-standard OIDC flow is needed beyond what fastmcp's built-in `OIDCProxy` covers | fastmcp's auth providers already bundle what they need internally; do not add authlib as a direct dependency unless a specific gap is found when wiring Keycloak (verify during implementation, don't pre-add) |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Docker Compose service definitions for `arcadedb`, `garage`, `keycloak` | Extend the existing `compose.yaml` reference stack | Each needs a healthcheck matching the existing pattern (TuringDB/embed/rerank/GLiNER already have them); ArcadeDB and Garage are lightweight enough to run without GPU, so they don't inherit the GPU-dependency problem already flagged for embed/rerank in CI |
| `docker compose config --quiet` | Validates the extended compose file | Already part of the gate per CLAUDE.md; extend, don't replace |

## Installation

```bash
# Core (add to pyproject.toml dependencies, ArcadeDB driver has zero new deps if built on stdlib urllib)
python -m pip install -e ".[dev]"

# S3 client
python -m pip install "boto3>=1.34"

# ArcadeDB driver — no new dependency if hand-rolled on urllib.
# If choosing the beta third-party client instead:
python -m pip install "arcadedb-python"
```

```yaml
# compose.yaml additions (illustrative — flesh out during phase planning)
services:
  arcadedb:
    image: arcadedata/arcadedb:26.7.1
    ports: ["2480:2480", "5432:5432"]
    volumes: ["arcadedb-data:/opt/arcadedb/databases"]
  garage:
    image: dxflrs/garage:v2.2.0
    ports: ["3900:3900"]
    volumes: ["garage-meta:/var/lib/garage/meta", "garage-data:/var/lib/garage/data"]
  keycloak:
    image: quay.io/keycloak/keycloak:26.7.0
    command: start-dev
    ports: ["8180:8080"]
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| ArcadeDB native HNSW (JVector) + native Lucene FTS | Qdrant (dedicated vector DB) + OpenSearch (dedicated search engine) | If a single tenant's vector count is projected to exceed ~5–10M or the workload needs Qdrant's tiered-multitenancy sharding at scale — not the case for this stabilization milestone; revisit as a documented future scaling limit, same pattern as existing CONCERNS.md scaling entries |
| ArcadeDB HTTP/JSON API via stdlib `urllib` driver | ArcadeDB Postgres wire protocol (via `psycopg`) | If the team wants generic SQL-tool (Grafana/Metabase/DBeaver) connectivity to ArcadeDB for operational dashboards — orthogonal to the MCP server's own driver, can be added later without touching the driver interface |
| Garage | RustFS | RustFS (Apache-2.0, Rust, 2.3x MinIO's small-object throughput) is the most-watched MinIO replacement but only reached Beta in April 2026 with GA targeted July 2026 — re-evaluate once it has a GA release and a production track record; too early for a stabilization milestone that values reliability |
| Garage | Cloud S3 (AWS) | If the deployment target moves off self-hosted Docker Compose to a managed cloud environment — out of scope per this milestone's "one-command Docker stack" constraint, but boto3 code is portable either way |
| Keycloak | Authentik (2026.5.4) | If a lighter-weight IdP is preferred (Authentik has a smaller footprint and a more modern admin UX) — Keycloak is recommended primarily because it has more direct FastMCP integration precedent; Authentik is a reasonable substitute with no code-level difference since both speak standard OIDC discovery |
| Qdrant (if ever needed) | Weaviate, Milvus | Weaviate has a heavier resource footprint for this scale; Milvus requires etcd + Pulsar/Kafka + MinIO as its own dependency cluster — the opposite of "one-command Docker stack." If a dedicated vector DB is ever warranted, Qdrant is the only one of the three that fits a single-container-plus-volume deployment model matching this project's operational philosophy |
| OpenSearch (if ever needed) | Elasticsearch, MeiliSearch | Elasticsearch gates security/alerting features behind paid tiers that OpenSearch (Apache-2.0 fork of ES 7.10.2, API-compatible) includes free; MeiliSearch's self-hosted Community Edition is lighter (~512MB RAM, sub-50ms) but is explicitly not built for distributed/clustered scale-out (that's gated to MeiliSearch Cloud) — fine for a single-node deployment, weaker choice if multi-node HA search is ever required |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| **MinIO Community Edition** as a new S3-storage dependency | The self-hosted AGPLv3 server was put in maintenance mode Dec 2025, marked unmaintained Feb 2026, and the `minio/minio` GitHub repo was formally archived Apr 25 2026 — no more upstream patches, CVE fixes, or binary releases for the CE track. Adopting it now would mean deliberately introducing a new at-risk/unmaintained dependency in the same milestone that is trying to *retire* at-risk dependencies (CONCERNS.md) | Garage (actively maintained, purpose-built for this scale) |
| Milvus for a "one-command Docker stack" | Requires etcd + Pulsar/Kafka + its own MinIO instance as mandatory infrastructure dependencies — directly contradicts Thrust 1's one-command-stack goal and would itself introduce the now-deprecated MinIO CE as a transitive dependency | Qdrant, or (per the verdict above) nothing — ArcadeDB native vector for the ArcadeDB backend |
| `arcadedb-python` (third-party Beta client) as the *only* ArcadeDB integration path | Beta status, single external maintainer, not officially blessed by ArcadeData — repeats the exact "tightly coupled to a single client library" risk CONCERNS.md flags for `turingdb==1.35` today | Thin stdlib-`urllib` HTTP/JSON driver matching this codebase's existing provider-client pattern |
| Adding `httpx` or `requests` as a new dependency for the ArcadeDB driver | This codebase has a deliberate, established pattern of using stdlib `urllib.request` for all HTTP-based provider integrations (`embeddings.py`, `rerank.py`) — a new HTTP client library would be an unrequested dependency addition and break "follow existing patterns" | stdlib `urllib.request`, same as every existing provider client |
| Elasticsearch as a *new* required service for this milestone | Paid-tier gating on security/alerting features that OpenSearch includes free, and — per the verdict above — not needed at all if the ArcadeDB backend's native Lucene FTS is adopted | Nothing (ArcadeDB native), or OpenSearch if a dedicated engine is ever truly warranted later |

## Stack Patterns by Variant

**If the deployment selects the ArcadeDB backend:**
- Use ArcadeDB native HNSW (JVector) for vector search and native Lucene full-text — no separate search/vector service
- Provision **one ArcadeDB database per tenant** (or per tenant-tier) via the server's native multi-database mode, not a shared database with a `user_identifier` column — this gets tenant isolation "for free" on both the vector and full-text indexes and directly satisfies the "tenant-scoped isolation (ArcadeDB per-database or scoped)" item in PROJECT.md's Active requirements
- Because ArcadeDB's Lucene FTS index is ACID-integrated with graph/vector writes, drop the SQLite-FTS5-projection pattern (`sparse_index.py`'s outbox prepare/commit/replay) for this driver — it exists only to work around TuringDB's lack of native full-text

**If the deployment selects the TuringDB backend:**
- Keep the existing SQLite FTS5 projection + TuringDB vector search exactly as-is — this milestone is explicitly not rewriting retrieval-fusion or ranking (PROJECT.md, Out of Scope)
- The driver interface must accommodate this asymmetry: TuringDB driver owns a rebuildable-projection sparse index; ArcadeDB driver does not need one

**If any single tenant's vector volume is projected to exceed the ~1-5M range documented in ArcadeDB's own benchmark discussions:**
- Re-open the "dedicated systems" question for that tenant specifically; Qdrant is the pre-vetted fallback (see Alternatives table) — this does not need to block the current milestone

**If OAuth/OIDC rollout needs to support both a new IdP-based flow and existing static-bearer-token deployments during migration:**
- Keep `AGENTMEMORY_AUTH_TOKEN(S)` support alongside the new OIDC provider rather than a hard cutover — fastmcp supports composing/chaining verifiers; sequence this as an additive change with a rollback path per PROJECT.md's constraint that heavyweight swaps need "migration + rollback paths, not drop-ins"

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `fastmcp>=3.4,<4` (already pinned) | `OIDCProxy`/`OAuthProxy`/`RemoteAuthProvider` | These were introduced starting at fastmcp 2.12 and carried forward; **verify by direct import** (`from fastmcp.server.auth import OIDCProxy` or equivalent) against the exact version resolved within the existing `>=3.4,<4` pin before planning the OAuth phase — this research could not confirm the precise class path/version boundary with HIGH confidence |
| ArcadeDB 26.7.1 | Docker image `arcadedata/arcadedb:26.7.1` | Pin the same tag in Compose and any CI integration-test fixture, matching the existing pattern of pinning `turingdb==1.35` |
| Garage v2.2.0+ | boto3 (any current version) | Garage does not implement AWS bucket ACLs/policies or full versioning — code that assumes those S3 features (none currently exists in this codebase) would need adjustment; plain PUT/GET/DELETE object operations for document staging are fully supported |
| Keycloak 26.7.0 | Standard OIDC discovery (`/.well-known/openid-configuration`) | No FastMCP-side version coupling beyond the OIDC standard itself; Keycloak's realm/client config is the integration surface, not a Python dependency |
| Python 3.11–3.14 (already required) | `arcadedb-python` requires Python >=3.10 | Compatible if that client is chosen instead of the recommended stdlib driver |

## Sources

- [ArcadeDB GitHub](https://github.com/ArcadeData/arcadedb), [ArcadeDB Docs](https://docs.arcadedb.com/arcadedb/), [Postgres Protocol Plugin docs](https://docs.arcadedb.com/arcadedb/how-to/connectivity/postgres) — MEDIUM confidence, cross-checked web search
- [ArcadeDB 26.7.1 release blog](https://arcadedb.com/blog/), [ArcadeDB Jepsen tests blog](https://arcadedb.com/blog/arcadedb-jepsen-tests-34-pass/) — MEDIUM confidence
- [ArcadeDB vector benchmark discussion #3140](https://github.com/ArcadeData/arcadedb/discussions/3140), [Vector Embeddings docs](https://docs.arcadedb.com/arcadedb/how-to/data-modeling/vector-embeddings), [JVector issue #2529](https://github.com/ArcadeData/arcadedb/issues/2529) — MEDIUM confidence
- [Full-Text Index docs](https://docs.arcadedb.com/arcadedb/how-to/data-modeling/full-text-index) — MEDIUM confidence
- [arcadedb-python PyPI](https://pypi.org/project/arcadedb-python/), [GitHub](https://github.com/stevereiner/arcadedb-python) — MEDIUM confidence (Beta status is self-declared by the package's own classifiers)
- [Qdrant multitenancy docs](https://qdrant.tech/documentation/manage-data/multitenancy/), [Qdrant 1.16 tiered multitenancy blog](https://qdrant.tech/blog/qdrant-1.16.x/), [qdrant-client PyPI](https://pypi.org/project/qdrant-client/) — MEDIUM confidence
- [Meilisearch vs OpenSearch comparison](https://www.meilisearch.com/comparisons/meilisearch-vs-opensearch), [OpenSearch release history](https://opensearch.org/releases/) — MEDIUM confidence
- MinIO archival: [Vonng blog "MinIO Is Dead, Long Live MinIO"](https://blog.vonng.com/en/db/minio-resurrect/), [glukhov.org "MinIO CE in 2026: Retired Upstream"](https://www.glukhov.org/data-infrastructure/object-storage/minio-dead/), [minio/minio discussion #21667](https://github.com/minio/minio/discussions/21667) — MEDIUM confidence, multiple independent sources corroborate the archival date and cause
- [Garage HQ docs](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/), [Garage GitHub mirror](https://github.com/deuxfleurs-org/garage), [glukhov.org Garage quickstart](https://www.glukhov.org/data-infrastructure/object-storage/garage-quickstart/) — MEDIUM confidence
- [RustFS GitHub](https://github.com/rustfs/rustfs), [RustFS beta announcement](https://rustfs.dev/announcing-rustfs-beta-the-high-performance-s3-compatible-open-source-storage-for-the-ai-era/) — MEDIUM confidence
- [FastMCP OAuth Proxy docs](https://gofastmcp.com/servers/auth/oauth-proxy) — MEDIUM confidence (fetched via WebFetch, single source; verify class names against the exact pinned fastmcp version before implementation)
- [Keycloak release notes](https://www.keycloak.org/2026/07/keycloak-2670-released) — MEDIUM confidence
- [Authentik releases](https://docs.goauthentik.io/releases/) — MEDIUM confidence
- `.planning/codebase/CONCERNS.md`, `.planning/codebase/STACK.md`, `.planning/codebase/INTEGRATIONS.md`, `.planning/PROJECT.md`, and direct reads of `pyproject.toml` / `src/turing_agentmemory_mcp/embeddings.py` — HIGH confidence, primary source (this repository)

---
*Stack research for: Turing AgentMemory MCP stabilization milestone — backend/infra technology selection*
*Researched: 2026-07-11*
