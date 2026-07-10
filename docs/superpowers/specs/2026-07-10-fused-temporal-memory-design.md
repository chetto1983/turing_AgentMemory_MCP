# Fused Temporal Memory Pipeline Design

## Objective

Fuse the existing GLiNER2, Granite embedding, and Qwen reranking models with temporal graph retrieval, sparse retrieval, and Leiden communities. The resulting pipeline must remain local, tenant-isolated, explainable, recoverable, and measurable through direct MCP end-to-end evaluation.

The implementation must improve memory representation and retrieval rather than substitute another model without an ablation. Raw conversation turns remain immutable evidence. Every derived entity, relation, fact, and community must retain provenance back to that evidence.

## Constraints

- The deployment target has a 4 GB NVIDIA GPU. Granite embedding and Qwen reranking remain the only GPU residents.
- `lion-ai/gliner2-base-v1-onnx` remains revision-pinned and CPU-only in the shared GLiNER sidecar.
- TuringDB remains the authoritative graph and vector store.
- MCP remains the only memory API used by product and benchmark clients.
- Models and dependencies use persistent caches and pinned identities. Benchmark runs do not redownload unchanged artifacts.
- No extraction, projection, or reranking failure is silently reported as successful model execution.
- The default distributed product remains compatible with its MIT license.

## Selected Architecture

### Canonical temporal graph

Every stored message creates one immutable `Memory` episode. GLiNER2 performs one composed extraction over a speaker- and observation-time-enriched representation and returns:

- typed entities;
- constrained, directional relations;
- date and time expressions;
- memory-kind classification;
- extraction confidence and source spans.

Derived graph records use deterministic IDs:

- `Entity` nodes represent normalized entity identities per tenant and type;
- `Fact` nodes represent extracted subject-predicate-object assertions;
- `Community` nodes represent Leiden partitions;
- `MENTIONS`, `SUBJECT_OF`, `OBJECT_OF`, `SUPPORTED_BY`, `IN_COMMUNITY`, and typed relation edges connect the layers.

Facts include observation time, optional valid-from and valid-to times, extraction schema version, model identity, confidence, source memory ID, session, and speaker. New contradictory facts do not delete old evidence. Temporal validity can close a previous derived fact while preserving both facts and their source episodes.

### GLiNER2 composed extraction

The existing FastGLiNER2 ONNX runtime already supports composed schemas, relation extraction, classifications, and structured fields. The sidecar gains a versioned `/extract-memory` endpoint. It uses constrained relation schemas so subjects and objects must have compatible entity types. The endpoint accepts multiple messages and processes them in stable order under the existing bounded inference worker.

The initial schema covers people, organizations/groups, locations, activities/events, products/objects, topics, and date expressions. Relations cover participation, membership, location, ownership, preference, planning, creation, recommendation, family/social relationships, and event time. The schema is configuration, not hard-coded transport behavior.

Raw source text is never replaced by extraction output. A failed mandatory extraction rejects the batch before graph, vector, or sparse-index writes.

### Sparse search projection

SQLite FTS5 provides a persistent BM25 projection under `TURINGDB_HOME/data`. It indexes episode, fact, entity, and community text with tenant, source ID, kind, and projection version as unindexed fields. TuringDB remains authoritative; FTS5 is a rebuildable CQRS read model.

Projection writes are idempotent. A durable SQLite outbox records pending projection operations before the TuringDB mutation is acknowledged. Startup repair replays pending operations and can rebuild the complete projection from TuringDB. Search never scans every tenant memory to approximate lexical retrieval.

### Leiden communities

The production backend uses revision-pinned `graspologic-native` because it provides a native weighted Leiden implementation under MIT and publishes Linux wheels for the supported Python versions. Community detection runs on CPU outside the synchronous message write path.

Weighted undirected entity edges are built from extracted relations and source co-occurrence. A fixed random seed and recorded resolution make partitions reproducible. Hierarchical Leiden subdivides oversized communities. Isolated entities remain searchable but do not receive a fabricated community.

Community text is deterministic: highest-confidence entities, relations, temporal bounds, and representative fact snippets are assembled with provenance. Granite embeds this text. Community rebuild replaces only derived community nodes and edges for the tenant; episodes, facts, and entities remain unchanged.

`vtraag/leidenalg` is supported behind the same detector protocol only when explicitly installed by an operator. It is not included in the default image because it is GPL-3.0.

## Retrieval Pipeline

Search performs these candidate channels independently:

1. episode dense vector search;
2. fact dense vector search;
3. entity dense and normalized-exact search;
4. FTS5 BM25 search;
5. one- and two-hop graph expansion from entity and fact seeds;
6. community dense search.

Each channel returns a ranked list with channel-local evidence. Weighted reciprocal rank fusion combines ranks rather than incomparable raw scores. The default RRF constant is 60, and all channel weights are configuration values recorded in score explanations.

The fused pool is capped before Qwen reranking. Each rerank document contains the derived fact or episode, speaker/date context, a compact graph path, and source reference. Reranker truncation becomes token-aware and configurable rather than the current fixed 480-character cut. Final selection preserves relevance while avoiding duplicate facts from the same source message.

Every result can include:

- channel ranks and raw channel scores;
- weighted RRF contributions;
- graph path and community ID;
- reranker score and fallback state;
- source memory IDs and extraction confidence;
- degraded or unavailable channels.

## Availability And Recovery

- Mandatory GLiNER extraction is fail-closed for writes.
- TuringDB write and sparse projection state are reconciled through the durable outbox.
- Community maintenance is asynchronous and health-reported; stale communities do not block episode/fact retrieval.
- A failed candidate channel degrades search only when at least one healthy channel remains, and the response and telemetry name the degraded channel.
- A failed reranker preserves the fused order and marks the fallback; it never claims neural reranking succeeded.
- Administrative repair operations rebuild FTS projection, derived graph data, communities, and vectors without changing raw memory IDs.

## Security And Governance

All graph nodes, edges, vector records, FTS rows, and community jobs are scoped by `user_identifier`. Query filters apply before fusion. Raw text, extracted values, embeddings, and rerank documents are excluded from audit logs. Derived records inherit source expiration and deletion policy. Projection rebuild and community maintenance are audited administrative operations.

## Observability

Spans cover extraction, graph projection, sparse projection, every candidate channel, fusion, reranking, and context assembly. Metrics include model identity, batch size, entity/relation/fact counts, candidate counts by channel, overlap between channels, RRF contribution, fallback state, projection lag, community age, and stage latency. Logs contain identifiers and counts, never private content.

## Validation Contract

Unit and integration tests prove:

- composed GLiNER2 normalization and constrained relation handling;
- atomic, idempotent derived graph writes with provenance;
- tenant-isolated FTS5 BM25 and outbox recovery;
- deterministic weighted RRF and complete score explanations;
- graph expansion and community retrieval;
- deterministic Leiden partitioning and isolated-node handling;
- visible degradation and repair behavior;
- unchanged governance, filters, expiry, and deletion semantics.

Direct MCP E2E validation uses the full 1,540 non-adversarial LoCoMo questions at top 20, 50, and 200. It records evidence-any, evidence-all, MRR, answer-in-context, latency, token count, and final answer accuracy under a pinned answerer/judge contract. MCP is the only memory interface; answerer and judge are benchmark components, not alternate memory access paths.

The benchmark runs staged ablations: dense-only, dense plus BM25, entity/graph fusion, community fusion, and Qwen reranking. A channel becomes production-default only when it improves the quality/latency frontier. The final comparison to Mem0 uses the same dataset, question set, retrieval cutoffs, answerer, judge, prompts, and token accounting.

## Delivery Sequence

1. Extend the GLiNER sidecar and processor contract with composed memory extraction.
2. Add temporal graph projection and provenance-preserving derived records.
3. Add transactional FTS5 projection, outbox, and repair.
4. Replace fixed score blending with independent channels and weighted RRF.
5. Add graph expansion and token-aware Qwen reranking context.
6. Add deterministic native Leiden maintenance and community retrieval.
7. Add the comparable LoCoMo answer-generation evaluator and staged ablations.
8. Run the full direct-MCP E2E benchmark and tune only from recorded evidence.

