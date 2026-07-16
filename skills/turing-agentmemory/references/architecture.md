# Architecture and Lifecycle

## Core Model

ArcadeDB stores the canonical tenant-scoped graph. Dense indexes, sparse indexes, extracted
facts/entities, temporal relations, Leiden communities, and rerank order are derived or
retrieval-time structures. Canonical graph records remain the authority for lifecycle and
repair.

```text
authenticated caller
        |
        v
 user_identifier boundary
        |
        +--> canonical episodes, facts, entities, documents, chunks
        |               |
        |               +--> temporal/entity graph
        |               +--> Leiden communities
        |               +--> sparse BM25 projection
        |               +--> dense vector projection
        |
query --+--> parallel candidates --> weighted rank fusion --> rerank --> scoped evidence
```

## Write Lifecycle

1. Validate tenant scope and input shape.
2. Apply governance redaction before persistence and embedding when enabled.
3. Write the canonical scoped record with provenance and retention metadata.
4. Extract entities/facts and temporal relationships when configured.
5. Update sparse and dense projections.
6. Refresh derived communities, immediately or once after a batch.
7. Return the canonical object and ID.

Stable caller-supplied IDs make replay duplicate-safe. Raw message episodes are append-only
temporal evidence. A changed durable fact should update its mutable structured record rather
than rewrite history or create two unqualified current truths.

## Retrieval Lifecycle

1. Apply `user_identifier` and all explicit metadata/date filters.
2. Generate dense, sparse, entity, graph, and community candidates from healthy channels.
3. Fuse candidates using weighted reciprocal-rank evidence.
4. Optionally rerank the candidate set.
5. Hydrate active canonical records and remove expired or deleted content.
6. Return bounded context or inspectable result objects.

The server can degrade individual channels. Runtime readiness must therefore be interpreted
per stage and projection; a live MCP socket alone does not prove retrieval quality.

## Isolation Model

`user_identifier` is the mandatory partition key for reads, writes, updates, deletion,
projection repair, and community rebuild. `session_id`, source, tags, types, and dates only
narrow that partition. They never expand it.

Identity should be mapped from an authenticated subject by the host. Do not accept an
arbitrary model-produced tenant ID. Service authorization and data scoping are separate:
an MCP bearer token authenticates the client, while `user_identifier` selects the data
partition.

## Retention and Deletion

`expires_at` suppresses expired memories and documents from active reads. Deletion is soft
and removes records from active retrieval while preserving the product's governed lifecycle.
Backups, audit retention, and physical erasure obligations remain deployment responsibilities.

## Evidence Semantics

Episodes and document chunks are direct evidence. Extracted facts, entities, graph paths,
and communities are useful retrieval signals but may be inferred. For high-consequence
answers, inspect or cite the direct supporting record and distinguish model inference from
stored evidence.
