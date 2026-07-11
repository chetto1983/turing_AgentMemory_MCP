# Pitfalls Research

**Domain:** Dockerized MCP memory server — GPU-mandatory sidecars, TuringDB→ArcadeDB backend abstraction, S3/OAuth heavyweight swaps, CI/hooks with no-skip-as-green
**Researched:** 2026-07-11
**Confidence:** MEDIUM (codebase-grounded findings are HIGH confidence — read directly from `compose.yaml`, `CLAUDE.md`, `CONCERNS.md`; ArcadeDB/OAuth/S3-specific claims are MEDIUM — cross-checked web sources, no hands-on ArcadeDB migration precedent in this repo yet)

## Critical Pitfalls

### Pitfall 1: TuringDB daemon restart silently orphans the in-memory graph

**What goes wrong:**
TuringDB is `restart: unless-stopped` with an 8g memory limit and no OOM guard beyond the container limit. If TuringDB restarts for any reason (OOM kill, host reboot, manual restart), the MCP server keeps running against a TuringDB instance whose user graphs are **durable on disk but not auto-loaded into memory**. Queries silently return empty or partial results instead of erroring, because there's no code path that reacts to a TuringDB restart by calling `load_graph`.

**Why it happens:**
CLAUDE.md invariant #6 documents this explicitly ("After a TuringDB daemon restart, call `load_graph` explicitly — user graphs are durable but not auto-loaded") but it's a *documented manual step*, not enforced by the MCP server's own health/readiness logic. `docker compose`'s `depends_on: condition: service_healthy` only gates **startup order** — it does not re-verify or react to a dependency restarting later in the container's lifetime.

**How to avoid:**
Make `load_graph` part of the MCP server's own startup/reconnect logic rather than an operator runbook step: on every TuringDB connection failure or a detected new TuringDB process (e.g., health payload signals cold DB), the store layer should call `load_graph` before serving. At minimum, the `/health` readiness check (already gates `runtime.stages.graph.ready`) should go unhealthy — and stay unhealthy until `load_graph` succeeds — rather than assuming a one-time load at boot is sufficient for the container's whole lifetime.

**Warning signs:**
Search/retrieval tools return empty results after a period of apparent stability; TuringDB container shows a restart in `docker compose ps`/logs but MCP's `/health` still reports `ok`.

**Phase to address:** Thrust 1 (Infrastructure on Docker) — should be verified as part of "real document flows end-to-end through the dockerized MCP," specifically by chaos-testing a TuringDB container restart mid-stack and confirming the MCP `/health` check catches it.

---

### Pitfall 2: GPU sidecars silently degrade instead of failing loudly

**What goes wrong:**
`compose.yaml` requests GPU access for `agentmemory-embed`/`agentmemory-rerank` two ways simultaneously: the top-level `gpus: all` key **and** `deploy.resources.reservations.devices` with `driver: nvidia`. On a host without a working NVIDIA Container Toolkit, this doesn't always fail cleanly — behavior differs by Docker Compose version, and a misconfigured host can produce a container that starts but never gets real GPU access, silently falling back to a broken or CPU-bound llama.cpp server rather than a "device driver not found" error.

**Why it happens:**
Docker Compose GPU support has two overlapping mechanisms (the Compose-spec `gpus:` field vs the Swarm-style `deploy.reservations.devices`), and the failure mode when GPU access is misconfigured is often silent degradation rather than a hard startup error — teams assume "container is running" means "GPU is attached."

**How to avoid:**
The healthcheck already runs `nvidia-smi >/dev/null && curl ...` inside the container, which is the correct pattern (verifies GPU visibility from *inside* the started container, not just `docker run --gpus all` on the host). Keep that. Additionally: pick one GPU-declaration mechanism as canonical (the `gpus: all` top-level key is sufficient for Compose v2) and document why the other is present, or drop the redundant one — two overlapping declarations is confusing for anyone debugging a GPU acquisition failure later.

**Warning signs:**
`docker compose up` succeeds, healthchecks pass, but embedding/rerank latency is 10-100x worse than expected (CPU fallback); `nvidia-smi` inside the container returns a driver-mismatch or "no devices found" error that the healthcheck script swallows if `set -e` isn't respected.

**Phase to address:** Thrust 1 (Infrastructure on Docker) — verify with an explicit "GPU visible inside container" smoke test as part of the one-command-stack acceptance criteria, not just healthcheck-passes.

---

### Pitfall 3: Read-only/non-root hardening breaks new write paths only at runtime, not at test time

**What goes wrong:**
`turing-agentmemory-mcp`, `agentmemory-lab`, `agentmemory-gliner`, and the llama-provider sidecars all run `read_only: true` with only `/tmp` and `/run` as writable tmpfs mounts, plus the shared `turing-data` volume at `/turing`. Every *existing* write path (document staging, sparse index, job queue, audit/span JSONL) is already routed to `/turing` or `/tmp`. Heavyweight swaps in this milestone add new write surfaces — an S3 client's local buffer/cache, an ArcadeDB driver's local WAL or connection cache, OAuth/OIDC JWKS caching, vector-index-versioning metadata — and any of these that default to `$HOME`, a library-default cache dir, or the container filesystem root will fail with `OSError: Read-only file system` **only when actually exercised in the hardened container**, not in unit tests that run outside Docker.

**Why it happens:**
`ruff check` and `pytest` run on the host/dev environment where the filesystem is writable; the read-only constraint is a container-only property. This is exactly the kind of gap CLAUDE.md's Definition of Done exists to close ("validated end-to-end on a real scenario, not just when unit tests are green"), but new heavyweight-swap dependencies are the most likely place to reintroduce it because they weren't part of the original hardening pass.

**How to avoid:**
Every new library/dependency introduced for S3, ArcadeDB, or OAuth must have its cache/home/tmp env vars explicitly pinned to `/tmp` or `/turing` in `compose.yaml`, following the existing `HOME=/tmp`, `XDG_CACHE_HOME=/tmp/.cache`, `PYTHONPYCACHEPREFIX=/tmp/pycache` pattern already used for every service. Add a smoke test that runs the actual dockerized (read-only) container through the full write path for each new integration, not just a host-side unit test.

**Warning signs:**
A feature works in `pytest` and fails only when run via `docker compose up`; `test_docker_hardening.py`-style structural tests (which check `read_only: true` and `tmpfs` are declared) pass even though a specific new dependency isn't actually compatible with them.

**Phase to address:** Thrust 1 (Docker) sets the constraint; each Thrust 2 heavyweight-swap sub-phase (S3, ArcadeDB, OAuth/OIDC, vector versioning) must re-verify it against the hardened container, not assume Thrust 1 covers it once.

---

### Pitfall 4: The repository/driver interface leaks TuringDB's transaction quirks into the contract

**What goes wrong:**
TuringDB has several documented, non-obvious behaviors baked into `store.py` today: dependent graph batches must be **submitted** before the next `MATCH` can see them (invariant #4), vector search results do not preserve score order through composed `VECTOR SEARCH ... MATCH ...` queries and must be sorted in the application layer (invariant #5), and graphs require an explicit `load_graph` after a daemon restart (invariant #6, see Pitfall 1). If the new repository/driver interface is designed by mirroring these TuringDB mechanics as first-class interface methods (e.g., `submit_batch()` as a required step every driver must implement, or a `raw_vector_search()` that callers are expected to re-sort), the ArcadeDB driver either has to fake TuringDB's staging semantics unnecessarily, or worse, silently returns unsorted/stale-looking results because the ArcadeDB code path forgot the TuringDB-specific workaround that the interface baked in.

**Why it happens:**
It's natural — and much less work in the short term — to extract an interface by generalizing the existing `store.py` call patterns rather than by first defining domain-level operations (`upsert_memory`, `link_entities`, `vector_search` returning a guaranteed-sorted result) and then implementing TuringDB's batch-submit-before-match and app-layer-sort as **internal details of the TuringDB driver only**.

**How to avoid:**
Design the interface around what callers need (idempotent upserts, sorted vector search results, tenant-scoped graph traversal), not around how TuringDB happens to implement it. Every quirk in CLAUDE.md invariants #4-#6 should be resolved *inside* the TuringDB driver implementation and invisible to callers and to the ArcadeDB driver. Write a backend-agnostic contract test suite (one set of tests, run against both drivers) that asserts the *outcomes* (sorted results, visible-after-write consistency, no manual reload needed) rather than the mechanics.

**Warning signs:**
The driver interface has methods named after TuringDB primitives (`submit`, `match`, `load_graph`) rather than domain operations; the ArcadeDB driver has TODO/no-op implementations of TuringDB-specific methods; sort-order or staleness bugs appear only when swapping backends, not caught by TuringDB-only tests.

**Phase to address:** Thrust 2, backend driver abstraction sub-phase — should be the very first deliverable (interface design) before any ArcadeDB code is written, verified by writing the ArcadeDB driver stub against the interface and confirming it needs no TuringDB-specific hooks.

---

### Pitfall 5: Tenant isolation becomes backend-dependent during the swap

**What goes wrong:**
Today, tenant isolation is enforced entirely at the application layer: every `store.py` read/write is explicitly scoped by `user_identifier`, and CONCERNS.md notes there is "no multi-tenancy isolation at the TuringDB level" — it's a single shared graph namespace filtered by property. ArcadeDB, by contrast, naturally supports **per-database** tenancy (one ArcadeDB database per tenant). If the driver abstraction lets the ArcadeDB driver take a shortcut — relying on database-level isolation instead of also enforcing `user_identifier` scoping in every query, the way the TuringDB driver must — then a single driver bug (a missing tenant filter, a copy-paste query, a cross-database join in a later feature) has no defense-in-depth: it becomes a straight cross-tenant data leak, not a filtered-but-broken query.

**Why it happens:**
"ArcadeDB isolates tenants at the database level, so we don't need to filter" is a plausible-sounding optimization that silently drops invariant #1 ("fail closed on an empty identifier... never let model output select the tenant") from being a contract *of the interface* to being a property *of one implementation*.

**How to avoid:**
Treat `user_identifier` scoping as a **mandatory parameter on every interface method**, validated fail-closed by the interface layer itself (not left to each driver to remember), regardless of whether the underlying backend also provides its own isolation. Database-per-tenant in ArcadeDB should be additional defense-in-depth, never a replacement for query-level scoping. Run the exact same concurrent multi-tenant isolation test suite (CONCERNS.md's "Untested Area: Concurrent Multi-Tenant Queries," priority High) against both drivers before either ships.

**Warning signs:**
The ArcadeDB driver's query construction doesn't reference `user_identifier` at all for some operations ("it's handled by the database boundary"); the interface layer doesn't validate/reject an empty or missing tenant identifier before dispatching to a driver.

**Phase to address:** Thrust 2, backend driver abstraction + ArcadeDB adoption sub-phases jointly — this is a shared contract, not something either sub-phase owns alone. Verification: the concurrent multi-tenant test gap from CONCERNS.md, run against both backends.

---

### Pitfall 6: Deterministic IDs drift when a backend's native record identifiers leak into "stable" IDs

**What goes wrong:**
`ids.py` produces stable/deterministic IDs used for idempotent retries and — critically — for **stable vector IDs**, so a memory or chunk's vector in the TuringDB vector index can be re-derived and matched consistently across rebuilds. ArcadeDB has its own native record identifiers (RIDs, e.g. `#12:34`, tied to cluster/position and **not** stable across compaction/migration). If the ArcadeDB driver is implemented by convenience — using ArcadeDB's own RID as "the" record ID instead of continuing to compute and store the app-level deterministic ID as an indexed property — then vector IDs correlated to that record drift the moment the record moves (compaction, backup/restore, migration), silently orphaning vectors or causing duplicate entries on rebuild (compounding the already-known "Stale Vector Accumulation" bug in CONCERNS.md).

**Why it happens:**
Using the database's native primary key is the path of least resistance for a new driver; the cost (ID instability across the specific operations that matter for this app — rebuilds, backups, migrations) isn't visible until much later, often after data has accumulated.

**How to avoid:**
The deterministic ID scheme in `ids.py` must remain the canonical, backend-agnostic identifier for every record and vector, stored as an indexed/queryable property on both backends — never substituted with a backend-native identifier. Add an explicit test that computes the same deterministic ID for the same logical input against both drivers and asserts vector-index correlation survives a rebuild.

**Warning signs:**
Vector search returns results that don't correlate to the graph record that produced them after a rebuild; duplicate vectors appear for what should be the same underlying entity when switching backends; the ArcadeDB driver code references `record.getIdentity()`/RID anywhere in ID-generation logic.

**Phase to address:** Thrust 2, backend driver abstraction sub-phase — verify before ArcadeDB is exposed as a selectable backend, using the existing "Vector Index Rebuild with Active Queries" and stale-vector test gaps from CONCERNS.md as the template for a backend-parity version.

---

### Pitfall 7: ArcadeDB's per-item transaction model and HNSW rebuild cost collide with this app's existing write/rebuild patterns

**What goes wrong:**
`store.py` currently creates memories, entities, and facts largely one item (or small batch) at a time, and memory extraction/embedding calls are already known to be unbatched (CONCERNS.md, "Memory Extraction HTTP Requests Not Batched" and "Chunk Embedding Requires Individual Roundtrips"). ArcadeDB is fully transactional with MVCC and, per its own documentation, supports multiple isolation levels including optimistic-concurrency-style validation; a high-frequency, many-small-transaction write pattern (as this app currently generates) is more prone to concurrent-modification retries under ArcadeDB's isolation model than under TuringDB's explicit batch-submit model, especially once multi-worker document ingestion (already a Thrust 2 goal) is added on top. Separately, ArcadeDB's vector index uses the JVector library (HNSW variant) where build cost and quality trade off against quantization choice — published benchmarks show meaningfully different build times depending on quantization (INT8 quantization builds faster than unquantized at the ~1M-vector scale) — and the app's existing `memory_rebuild_vector_projection` tool already has a known bug (adds new vectors without removing stale ones). Porting that rebuild tool naively to ArcadeDB compounds an existing bug with a new, potentially much slower rebuild operation that also blocks/competes with live queries if not versioned.

**Why it happens:**
The batching and rebuild-versioning fixes are already tracked as separate CONCERNS.md items (tech debt + missing feature), and it's tempting to treat the ArcadeDB port as backend-swap-only work, deferring the batching/versioning fixes to "later" — but ArcadeDB's isolation model and HNSW build cost make those pre-existing gaps materially worse on the new backend, not equally bad.

**How to avoid:**
Sequence the batch-embedding and vector-index-versioning fixes from CONCERNS.md **before or alongside** the ArcadeDB driver, not after — the ArcadeDB driver should ship with a versioned/namespaced vector index and a retry-wrapped write path from day one, rather than porting the current unbatched, unversioned pattern and discovering the isolation/rebuild-cost problems in production. Choose and document a quantization strategy explicitly (don't take ArcadeDB's default) based on this app's actual vector counts.

**Warning signs:**
Concurrent-modification / optimistic-lock exceptions appearing under load that don't occur against TuringDB; vector rebuilds on ArcadeDB taking materially longer than expected and blocking concurrent search; index size growing without bound exactly as already observed with TuringDB's stale-vector bug.

**Phase to address:** Thrust 2 — ArcadeDB adoption sub-phase, sequenced after (or paired with) the tech-debt items "Stale Vector Accumulation," "Memory Extraction HTTP Requests Not Batched," and the missing "Vector Index Versioning" feature.

---

### Pitfall 8: Swapping SQLite FTS5 for ArcadeDB's Lucene full-text index silently changes ranking behavior

**What goes wrong:**
The current sparse/BM25 signal in the retrieval-fusion stack (`retrieval_fusion.py`, `sparse_index.py`) is powered by SQLite FTS5 with its own tokenizer and BM25 ranking. ArcadeDB's full-text index is Lucene-backed and lets you choose (and mix, per-field) different Lucene analyzers — e.g., an English analyzer vs. a standard analyzer — each with different tokenization, stemming, and stop-word behavior than FTS5's default. If the migration doesn't deliberately choose (or approximate) an analyzer that matches FTS5's current tokenization behavior, the lexical/BM25 component of the weighted RRF fusion score changes in ways that are functionally "correct" (index built, queries return results) but rank differently — a regression that unit tests checking "search returns results" will not catch.

**Why it happens:**
Analyzer choice is a configuration detail easy to leave at a library default during a backend port, and ranking-quality regressions from tokenizer mismatches are invisible without a query-level relevance comparison — they don't throw errors.

**How to avoid:**
Treat analyzer selection as a first-class decision, not a default: compare FTS5's tokenizer/ranking behavior against candidate Lucene analyzers on the same query set before committing to one for the ArcadeDB driver. This is exactly what the "vector + full-text strategy (research-decided)" item in PROJECT.md's Key Decisions should resolve — don't let it be settled implicitly by whatever ArcadeDB defaults to.

**Warning signs:**
Golden-query recall/MRR (see Pitfall 9) drops specifically on lexical/keyword-style queries when running against the ArcadeDB backend, while semantic/vector-heavy queries look unaffected — a signature of a tokenizer mismatch rather than a broader retrieval bug.

**Phase to address:** Thrust 2 — the research-decided "vector + full-text strategy" sub-item, resolved before ArcadeDB's full-text index is wired into the fusion pipeline as a BM25 replacement.

---

### Pitfall 9: Treating "it compiles and CRUD works" as done for a backend swap, instead of gating on a retrieval-quality parity check

**What goes wrong:**
This is the most consequential pitfall for the whole milestone: a functioning ArcadeDB driver (data writes, reads, and unit tests pass) can still produce a **materially worse product** than the TuringDB baseline, because the product's actual value is retrieval ranking quality, not just data correctness. Analyzer mismatches (Pitfall 8), vector quantization/normalization differences (Pitfall 7), and graph-traversal semantic differences between TuringDB's query language and ArcadeDB's SQL/Cypher/Gremlin surface can each independently degrade recall/MRR without producing a single failing test, because none of the store-level CRUD tests measure ranking quality — only the E2E score gate and the real-document benchmark harness (`scripts/e2e_score.py`, `scripts/real_document_benchmark.py`) do that, and only against the current (TuringDB) backend.

**Why it happens:**
CI/test discipline naturally converges on what's cheap to assert (does the write succeed, does the read return *a* result) rather than what's expensive to assert (is the *ranking* of results still good) — and a backend swap is exactly the class of change where the cheap checks pass while the expensive property silently regresses.

**How to avoid:**
Before ArcadeDB is offered as a selectable production backend, run the existing deterministic E2E score gate and the real-document benchmark harness against **both** backends on the same fixed corpus and question set, and require the ArcadeDB score to be within an explicit, documented tolerance of the TuringDB baseline (not just "runs without crashing"). This golden/parity gate is non-negotiable per CLAUDE.md's Definition of Done ("validated end-to-end on a real scenario") and PROJECT.md's Core Value ("Stabilization that breaks retrieval correctness... is a failure, not progress").

**Warning signs:**
"ArcadeDB backend" ships with only unit/integration test coverage, no side-by-side benchmark comparison; PR/commit descriptions claim the swap works based on a single manual smoke test rather than the deterministic gate (explicitly warned against by CLAUDE.md: "Don't claim a benchmark win from one corpus, one run, or mismatched provider configs").

**Phase to address:** Thrust 2 — dual-backend/migration sub-phase; this should be the **exit criterion** for ArcadeDB becoming a default-eligible backend, not an optional nice-to-have.

---

### Pitfall 10: OAuth/OIDC migration that keeps a client-supplied tenant field authoritative

**What goes wrong:**
Today, `user_identifier` (the tenant) is an arbitrary string supplied by the caller with no identity provider validating it — auth is a separate, coarser static-bearer-token check (`AGENTMEMORY_AUTH_TOKEN(S)`). Per the MCP authorization spec (2025-11-25 revision), an MCP server exposed over HTTP should act strictly as an **OAuth 2.1 resource server**, validating access tokens issued by an external authorization server and checking the token's audience (per RFC 8707) before trusting it. The natural, correct migration derives tenant identity from the verified token's claims (subject/sub, or an org claim). The common mistake is implementing OIDC token validation *in addition to* — rather than *instead of* — the existing client-supplied `user_identifier` field, "for backward compatibility," which leaves a straightforward tenant-isolation bypass: any caller with a valid-but-generic OAuth token can still supply an arbitrary `user_identifier` and access another tenant's memories.

**Why it happens:**
OIDC integration is usually scoped as "add authentication," and the existing tenant-scoping mechanism (the `user_identifier` parameter already threaded through 25+ tools) looks unrelated, so it's easy to treat identity and tenancy as separate concerns and ship OIDC without revisiting how the tenant identifier is derived.

**How to avoid:**
Once OIDC is authoritative, `user_identifier` must be derived server-side from verified token claims, not accepted as client input — this directly extends CLAUDE.md invariant #1 ("Never let model output select the tenant") to "never let client input select the tenant" once real identity is available. If a transition period requires accepting both, the two must be reconciled (token claim wins, client-supplied value is rejected or ignored) with an explicit audit log entry, not silently merged.

**Warning signs:**
Tool signatures still accept `user_identifier` as a free-form parameter after OIDC ships; there's no code path that overwrites/validates it against the token's claims; the static bearer-token path (`StaticTokenVerifier` in `server.py`) remains reachable in the same deployment as OIDC without an explicit reason.

**Phase to address:** Thrust 2 — OAuth/OIDC sub-item under "remaining heavyweight items." Verification: an integration test where a valid OIDC token for tenant A attempts to pass `user_identifier="tenant-b"` and is rejected/overridden, not honored.

---

### Pitfall 11: S3 staging "fixes" the upload-session leak in the app layer but reproduces it at the storage layer

**What goes wrong:**
CONCERNS.md documents three tightly related issues in the current local-filesystem staging design: the in-memory `DocumentUploadStore._sessions` dict has no TTL/cleanup, session state is lost on restart, and expiry is never enforced. Moving staging to S3 is listed as part of the fix ("Use external blob storage (S3) for staged files instead of local filesystem" — CONCERNS.md's scaling-path note). But S3 has the *exact same class of problem* natively: incomplete multipart uploads accumulate silently in a bucket, consuming storage and cost, unless an explicit `AbortIncompleteMultipartUpload` lifecycle rule is configured (AWS's own guidance recommends ~7 days as a starting point). If the migration persists session *metadata* to a durable store (fixing the in-memory-dict half of the bug) but doesn't also configure the bucket-side lifecycle rule, the leak simply relocates from "RAM growth in the MCP container" to "unbounded S3 storage cost and orphaned parts," which is arguably worse because it's invisible from inside the application entirely.

**Why it happens:**
S3 integration work tends to focus on the happy path (upload completes, object is committed) and treats "S3 is durable and scalable" as sufficient, missing that multipart uploads are a stateful protocol with their own cleanup requirements independent of the app's session bookkeeping.

**How to avoid:**
Fix both halves together: persist upload-session state (TTL-based, matching the CONCERNS.md recommendation to persist like `DocumentJobStore` does) **and** configure an `AbortIncompleteMultipartUpload` lifecycle rule on the staging bucket/prefix with a TTL that matches or is shorter than the app-level session TTL. Additionally, use per-part and full-object checksums (`x-amz-checksum-*`, SHA256) on upload completion — silent corruption during a large multipart PDF upload should be caught by checksum mismatch, not discovered later as a garbled document chunk.

**Warning signs:**
S3 bucket storage cost or object count grows without a corresponding growth in "documents successfully ingested"; no lifecycle rule is visible in the S3 bucket configuration/IaC; upload completion doesn't verify a checksum against what was sent.

**Phase to address:** Thrust 2 — S3 staging sub-item under "remaining heavyweight items," addressed together with the existing "Upload Session Memory Leak," "Thread Safety Gap in Upload Store," and "Session Expiry Not Enforced" tech-debt/bug items, not as a separate later fix.

---

### Pitfall 12: CI reports green without proving the gated tiers actually ran

**What goes wrong:**
Two related failure modes both produce a passing CI badge that doesn't mean what it appears to mean: (1) `pytest`'s exit code is 0 even when tests are skipped (e.g., a `pytest.mark.skipif(not gpu_available)` marker on GPU-dependent tests) — on a GPU-less GitHub Actions hosted runner, every GPU-gated test silently reports "skipped," the process exits 0, and the job goes green having verified nothing about GPU-backed retrieval; (2) if the dockerized GPU sidecars are started as part of CI and GPU device acquisition fails (`could not select device driver "" with capabilities: [[gpu]]` is the typical Docker error), a CI script that isn't asserting the container actually came up healthy — or that wraps the GPU tier in `continue-on-error`/`|| true` — will also go green having run nothing.

**Why it happens:**
"The job didn't fail" is easy to treat as equivalent to "the thing we meant to test, ran and passed," but skip semantics and best-effort error suppression both break that equivalence, and it's exactly the failure mode PROJECT.md flags by name ("CI on GPU-less runners must degrade those tiers to a compile/stub floor without silently skipping").

**How to avoid:**
For every gated CI tier: assert `skipped == 0` (or an explicit, reviewed allow-list of intentional skips) rather than trusting exit code alone; for the GPU tier specifically, either (a) run on a GPU-capable runner and assert the healthcheck's `nvidia-smi` check actually passed inside the container, or (b) explicitly run a compile/stub floor (the repo already supports this pattern via `E2E_USE_EXTERNAL_EMBED`/`E2E_USE_EXTERNAL_RERANK` env toggles and stub embed/rerank endpoints in `scripts/e2e_score.py`) and assert that floor executed — never silently degrade without a visible, asserted marker in the CI output. This is the concrete mechanism behind the "no-skip-as-green discipline" requirement in Thrust 3.

**Warning signs:**
CI logs show `X skipped` in a tier that's supposed to be mandatory, with no assertion failing on that count; the GPU-tier job step has `continue-on-error: true` or a trailing `|| true`; a red build was "fixed" by adding a `skipif`/`xfail` marker instead of fixing the underlying flake or timing assumption.

**Phase to address:** Thrust 3 — CI + git hooks, specifically the "no-skip-as-green discipline" and "GPU tiers degrade without silently skipping" requirements already named in PROJECT.md.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|-----------------|
| Keep the static bearer-token auth path (`StaticTokenVerifier`) reachable in the same deployment after OIDC ships | Fast rollback path during OIDC rollout | Tenant-bypass surface stays open; auth downgrade risk | Only as an explicitly gated, audited local-dev/break-glass mode — never a silently reachable prod fallback |
| Naive dual-write to TuringDB and ArcadeDB during migration, no reconciliation job | Fast to prototype a working ArcadeDB path | Silent, unbounded divergence between backends on partial failure | Only behind a feature flag, time-boxed to a spike; never in the actual cutover path |
| Port `store.py`'s existing unbatched per-item write pattern straight to the ArcadeDB driver | Less initial driver code | ArcadeDB's isolation model surfaces concurrent-modification retries this pattern doesn't hit against TuringDB (Pitfall 7) | Never — batch the writes before or alongside the ArcadeDB port |
| Leave both `gpus: all` and `deploy.reservations.devices` GPU declarations in `compose.yaml` without comment | Works today, no immediate risk | Ambiguous for future maintainers debugging GPU acquisition failures | Acceptable short-term; Thrust 1 should resolve to one canonical form and document the choice |
| Fix the upload-session leak only in the app layer (persist to SQLite) without configuring an S3 bucket lifecycle rule once S3 lands | Quick, code-only fix | The leak relocates to unbounded S3 storage/cost, invisible from inside the app | Never acceptable once S3 replaces local staging — both halves must ship together |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| TuringDB | Assuming `VECTOR SEARCH ... MATCH ...` preserves score order | Always sort vector results in the application layer (invariant #5) |
| TuringDB | Querying nodes from a graph batch that hasn't been submitted yet | Submit each dependent batch before the next `MATCH` (invariant #4) |
| TuringDB | Assuming the graph auto-reloads after a daemon restart | Call `load_graph` explicitly and make the MCP `/health` readiness check enforce it (Pitfall 1) |
| ArcadeDB full-text | Assuming a Lucene analyzer is a drop-in equivalent to SQLite FTS5's BM25 tokenizer | Explicitly select/compare analyzers against the golden query set before defaulting (Pitfall 8) |
| ArcadeDB vector index | Rebuilding the HNSW index the same way the (buggy) TuringDB rebuild works today | Version/namespace the index; don't port the known stale-vector bug forward (Pitfall 7) |
| S3 | Assuming `CompleteMultipartUpload` returning 200 guarantees byte-for-byte integrity | Verify per-part and full-object checksums (`x-amz-checksum-*`) |
| MCP OAuth | Trusting token possession alone as proof of tenant identity | Validate audience per RFC 8707 and derive `user_identifier` from verified claims, never a client-supplied field (Pitfall 10) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Single daemon-thread document worker (existing, CONCERNS.md) | Ingestion latency grows linearly with concurrent uploads; the 830-page G220 PDF already took 114s single-threaded (CONTINUE_HERE.md) | Thread pool / multi-worker leasing with per-worker lease rows in `DocumentJobStore` | Breaks past a handful of concurrent large documents |
| Full HNSW rebuild without versioning on ArcadeDB | Rebuild time scales with corpus size and competes with live queries; published benchmarks show multi-thousand-second builds at ~1M vectors depending on quantization | Namespaced/versioned vector indexes with atomic swap on completion | Breaks once corpus exceeds low-hundred-thousands of vectors |
| Vector search over-fetches 4x limit before filtering (existing, CONCERNS.md) | Memory/latency overhead grows with limit and filter-rejection rate | Push filtering to index predicate or adaptive fetch sizing | Breaks at high concurrent QPS or large tenant graphs |
| One ArcadeDB database per tenant at high tenant count | File-handle / page-cache pressure per open database (unverified at this app's scale) | Benchmark realistic tenant counts before committing to per-database tenancy over a scoped shared-database model | Likely breaks in the thousands-of-tenants range — flagged as a research gap, not confirmed |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Tenant identity still derived from a client-supplied field after OIDC ships | Cross-tenant data leakage via a trivially forgeable parameter | Derive `user_identifier` from verified token claims server-side; reject client-supplied values once OIDC is authoritative (Pitfall 10) |
| Static bearer-token path left reachable in prod after OIDC cutover | Classic auth-downgrade attack surface | Explicitly gate/disable the bearer path outside local dev; audit-log any use |
| ArcadeDB per-database tenancy assumed sufficient without app-layer scoping | One missing query filter = straight cross-tenant exposure, no defense-in-depth | Keep `user_identifier` scoping mandatory in the driver interface regardless of backend-level isolation (Pitfall 5) |
| S3-staged files with no per-tenant prefix/ACL separation | Data leakage across tenants at the storage layer | Prefix staged objects by tenant, use short-lived presigned URLs, never shared static bucket credentials |

## "Looks Done But Isn't" Checklist

- **Docker one-command stack:** `docker compose config --quiet` passes — verify a GPU is actually visible *inside* a container started by `docker compose up`, not just via `docker run --gpus all` (Pitfall 2)
- **Backend driver abstraction:** driver interface compiles and CRUD tests pass — verify the identical tenant-isolation and retrieval-parity test suites run against *both* drivers, not just the one being actively developed (Pitfall 5, 9)
- **ArcadeDB adoption:** ingestion and search "work" against ArcadeDB — verify recall/MRR on the golden benchmark corpus is not measurably worse than the TuringDB baseline before treating it as production-eligible (Pitfall 9)
- **OAuth/OIDC:** login/token-exchange flow works — verify the old static-bearer path is actually gated off in the deployed configuration, and that `user_identifier` cannot be overridden by client input (Pitfall 10)
- **S3 staging:** uploads succeed — verify an abandoned/aborted multipart upload is actually cleaned up on *both* the app side (session TTL) and the bucket side (lifecycle rule), and that a corrupted upload is rejected via checksum (Pitfall 11)
- **CI green:** pipeline shows green — verify by inspecting job output that zero tests were skipped in gated tiers and that the GPU tier actually attached a real GPU device, not a stub silently substituted without an assertion (Pitfall 12)
- **TuringDB restart resilience:** stack looks healthy after a restart — verify `load_graph` was actually re-invoked and `/health`'s `runtime.stages.graph.ready` reflects reality (Pitfall 1)

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|----------------|------------------|
| TuringDB restarted without `load_graph` being called | LOW | Call `load_graph` manually via an ops runbook today; wire it into the health/readiness path so this becomes self-healing |
| Divergent state between TuringDB and ArcadeDB during dual-write migration | HIGH | Run a reconciliation pass comparing deterministic IDs/checksums between backends; fall back to single-writer mode until resolved |
| Vector index built on ArcadeDB with the wrong quantization/analyzer choice | MEDIUM | Rebuild under a new versioned index name and atomic-swap once the parity gate (Pitfall 9) passes; never overwrite the live index in place |
| Bearer-token fallback left reachable post-OIDC cutover | MEDIUM | Rotate/revoke all static tokens immediately, audit access logs for the exposure window, close the code path |
| S3 lifecycle rule missing, incomplete multipart uploads accumulated | LOW | Backfill an `AbortIncompleteMultipartUpload` lifecycle rule; run a one-time cleanup pass over existing incomplete uploads (no early-delete charge per AWS) |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| TuringDB restart doesn't auto-reload graph | Thrust 1 — Infrastructure on Docker | Chaos-test a TuringDB container restart mid-stack; confirm `/health` catches it and `load_graph` is re-invoked |
| GPU sidecar silent degradation | Thrust 1 — Infrastructure on Docker | Assert `nvidia-smi` succeeds from inside the started container as part of the one-command-stack acceptance check |
| Read-only hardening breaks new write paths | Thrust 1 sets constraint; each Thrust 2 heavyweight-swap sub-phase re-verifies | Run each new integration's actual write path inside the hardened (read-only) container, not just host-side unit tests |
| Leaky TuringDB abstraction in driver interface | Thrust 2 — backend driver abstraction | ArcadeDB driver stub implements the interface with zero TuringDB-specific hooks required |
| Tenant isolation becomes backend-dependent | Thrust 2 — backend driver abstraction + ArcadeDB adoption | Same concurrent multi-tenant isolation test suite passes against both drivers |
| Deterministic ID drift breaks vector correlation | Thrust 2 — backend driver abstraction | Same deterministic ID computed for identical input on both drivers; vector correlation survives rebuild |
| ArcadeDB transaction/HNSW cost collides with existing write/rebuild patterns | Thrust 2 — ArcadeDB adoption, sequenced with batch-embedding and vector-versioning fixes | Load test concurrent writes against ArcadeDB; measure rebuild time and confirm versioned/atomic swap |
| Lucene analyzer mismatch changes BM25 ranking | Thrust 2 — research-decided vector/full-text strategy | Golden-query recall/MRR comparison isolates lexical-query regression before defaulting to an analyzer |
| No parity gate = silent retrieval-quality regression | Thrust 2 — dual-backend migration (exit criterion) | E2E score gate + real-document benchmark run against both backends within a documented tolerance |
| OAuth/OIDC tenant-bypass via client-supplied field | Thrust 2 — OAuth/OIDC | Integration test: valid token for tenant A + client-supplied `user_identifier="tenant-b"` is rejected/overridden |
| S3 staging reproduces the upload-session leak at the storage layer | Thrust 2 — S3 staging, paired with existing upload-session tech-debt/bug items | Bucket lifecycle rule configured and asserted in IaC; app-side TTL and bucket-side rule both verified |
| CI green without proving gated tiers ran | Thrust 3 — CI + git hooks | Assert `skipped == 0` (or reviewed allow-list) per gated tier; GPU tier asserts real device attachment or an explicit stub-floor marker |

## Sources

- `.planning/PROJECT.md`, `.planning/codebase/CONCERNS.md`, `.planning/codebase/INTEGRATIONS.md`, `CLAUDE.md` — HIGH confidence, primary source for all codebase-grounded pitfalls (invariants #1, #4, #5, #6; existing tech debt, known bugs, scaling limits)
- `compose.yaml`, `docker/turingdb.Dockerfile`, `tests/test_docker_hardening.py`, `CONTINUE_HERE.md` — HIGH confidence, read directly for GPU/healthcheck/hardening specifics
- [ArcadeDB Vector Embeddings docs](https://docs.arcadedb.com/arcadedb/how-to/data-modeling/vector-embeddings) and [Benchmarking ArcadeDB's Vector Index Build/Search discussion](https://github.com/ArcadeData/arcadedb/discussions/3140) — MEDIUM confidence (official docs + maintainer discussion, cross-checked), HNSW/JVector build-cost and quantization tuning
- [ArcadeDB Full-Text Index docs](https://docs.arcadedb.com/arcadedb/how-to/data-modeling/full-text-index) — MEDIUM confidence, Lucene analyzer configuration per field
- [ArcadeDB High Availability docs](https://docs.arcadedb.com/arcadedb/concepts/high-availability) and [ArcadeDB Jepsen test results](https://arcadedb.com/blog/arcadedb-jepsen-tests-34-pass/) — MEDIUM confidence, MVCC/isolation-level claims
- [Model Context Protocol Authorization spec (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) — MEDIUM confidence (primary spec, single-source but authoritative), OAuth 2.1 resource-server/PKCE/RFC 8707 audience-binding requirements
- [AWS: Configuring a lifecycle rule to abort incomplete multipart uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html) and [AWS: Discovering and deleting incomplete multipart uploads](https://aws.amazon.com/blogs/aws-cloud-financial-management/discovering-and-deleting-incomplete-multipart-uploads-to-lower-amazon-s3-costs/) — MEDIUM confidence (official AWS docs, cross-checked), S3 multipart cleanup/lifecycle guidance
- [Docker Compose GPU support docs](https://docs.docker.com/compose/how-tos/gpu-support/) and general GPU-Compose pitfall commentary (NVIDIA developer forums, community write-ups) — LOW-MEDIUM confidence, general pattern corroborated by the repo's own `nvidia-smi`-in-healthcheck pattern

---
*Pitfalls research for: Turing AgentMemory MCP — Stabilization Milestone (Docker stack, backend driver abstraction / ArcadeDB, heavyweight swaps, CI/hooks)*
*Researched: 2026-07-11*
