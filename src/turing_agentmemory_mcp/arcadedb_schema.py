"""Idempotent ArcadeDB schema bootstrap (D-09).

Creates the canonical vertex/edge types, one full-precision COSINE `LSM_VECTOR`
dense-vector channel, and BOTH lexical channels per content-bearing record
type: a native `LSM_SPARSE_VECTOR` channel (the D-04 spike's higher-scoring
candidate on the primary yardstick) and a native Lucene `FULL_TEXT` channel on
the record's raw text property (`content`, or `text` for `Chunk`). This
supersedes this module's original D-04-only framing: a later user decision
reconciled the D-04 spike finding with pre-spike plans that already assumed a
Lucene channel, landing on running BOTH channels through the existing Python
RRF (`retrieval_fusion.py`, unchanged) rather than picking one. See
`.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md` for the D-04
bake-off data and `04-03-SUMMARY.md`'s Amendment note for the both-channels
decision. Also creates a UNIQUE index on the `id` property (the value
`ids.stable_id()` produces) for every record type whose identity is not the
raw tenant `user_identifier` (ARC-08).

Every DDL form below was empirically verified against a live
`arcadedata/arcadedb:26.7.1` container as part of this plan (04-03), not
sourced from documentation alone:

- `CREATE VERTEX TYPE <name> IF NOT EXISTS` / `CREATE EDGE TYPE <name> IF NOT
  EXISTS` / `CREATE PROPERTY <type>.<name> IF NOT EXISTS <datatype>` are all
  natively idempotent -- confirmed live, re-running raises no error.
- `CREATE INDEX ...` does NOT support `IF NOT EXISTS` (confirmed live: a
  syntax error, "mismatched input 'IF'") -- idempotency for indexes is done by
  attempting the create and treating an "already exists" error as benign,
  mirroring `store_core.py`'s `_ensure_vector_index` pattern.
- ArcadeDB's schema introspection (`SELECT FROM schema:indexes` / `schema:
  types`) does NOT expose the `dimensions` METADATA an `LSM_VECTOR` index was
  created with -- confirmed live, no such field is returned. The only
  observable signal is the length of an already-stored vector, so dimension
  drift is detected by sampling one existing record, not by reading index
  metadata.

This module never generates or reads ArcadeDB's native record identity --
every identity check here is against the `id`/`identifier` property values
callers supply, matching ids.py's stable, deterministic ID scheme.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from turing_agentmemory_mcp.ids import cypher_var

DEFAULT_MAX_CONNECTIONS = 16
DEFAULT_BEAM_WIDTH = 100

VERTEX_TYPES: tuple[str, ...] = (
    "User",
    "Memory",
    "Document",
    "Chunk",
    "Entity",
    "Fact",
    "Community",
)
EDGE_TYPES: tuple[str, ...] = (
    "HAS_MEMORY",
    "HAS_DOCUMENT",
    "HAS_CHUNK",
    "NEXT_CHUNK",
    "SUBJECT_OF",
    "OBJECT_OF",
    "SUPPORTED_BY",
    "MENTIONS",
    "IN_COMMUNITY",
)
# Content-bearing types that carry a dense vector + lexical channel -- mirrors
# today's TuringDB memory/document(chunk)/entity/fact/community vector indexes
# (store_core.py's bootstrap) and the unified sparse_index.py `kind` coverage
# (episode/entity/fact/community/document) the D-04 channel replaces.
VECTOR_TYPES: tuple[str, ...] = ("Memory", "Chunk", "Entity", "Fact", "Community")
# Types whose primary identity is `ids.stable_id()` output, stored in `id` and
# UNIQUE-indexed (ARC-08). User is excluded: its identity is the caller-supplied
# `identifier` (raw user_identifier), never a stable_id() digest.
STABLE_ID_TYPES: tuple[str, ...] = (
    "Memory",
    "Document",
    "Chunk",
    "Entity",
    "Fact",
    "Community",
)

_EMBEDDING_PROPERTY = "embedding"
_LEXICAL_TOKENS_PROPERTY = "lexical_tokens"
_LEXICAL_WEIGHTS_PROPERTY = "lexical_weights"
# The raw text property each VECTOR_TYPE stores its content-bearing text
# under, for the Lucene FULL_TEXT channel to index directly -- unlike the
# derived lexical_tokens/lexical_weights sparse-vector channel (computed
# application-side from arbitrary source text), Lucene must index the actual
# stored property. Mirrors store_rebuild.py's `_canonical_vector_records`
# text_property mapping: every type uses `content` except `Chunk`, which
# stores its chunk body under `text`.
_FULL_TEXT_PROPERTY_BY_TYPE: dict[str, str] = {
    "Memory": "content",
    "Chunk": "text",
    "Entity": "content",
    "Fact": "content",
    "Community": "content",
}
_ALREADY_EXISTS_MARKER = "already exists"
_INDEX_REF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[([A-Za-z_][A-Za-z0-9_]*)\]$")


class SchemaClient(Protocol):
    """The subset of `ArcadeDBClient` this module issues DDL/introspection through."""

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]: ...

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class SchemaBootstrapConfig:
    """Validated bootstrap parameters (embeddings.py `__post_init__` convention)."""

    dimensions: int
    version: int = 1
    max_connections: int = DEFAULT_MAX_CONNECTIONS
    beam_width: int = DEFAULT_BEAM_WIDTH

    def __post_init__(self) -> None:
        if isinstance(self.dimensions, bool) or self.dimensions <= 0:
            raise ValueError("schema bootstrap dimensions must be positive")
        if isinstance(self.version, bool) or self.version <= 0:
            raise ValueError("schema bootstrap version must be positive")
        if isinstance(self.max_connections, bool) or self.max_connections <= 0:
            raise ValueError("schema bootstrap maxConnections must be positive")
        if isinstance(self.beam_width, bool) or self.beam_width <= 0:
            raise ValueError("schema bootstrap beamWidth must be positive")


def versioned_vector_index(base_name: str, user_identifier: str, version: int) -> str:
    """Deterministic tenant+version-namespaced property/index name (D-07 foundation).

    Extends `store_core.py`'s current `_tenant_vector_index` blake2b-digest
    tenant namespacing with a `_v{version}` suffix, so a rebuild (04-08) can
    create a new version's property/index alongside the live one and
    atomically swap which one queries read, rather than mutating a live index
    in place. Deterministic: identical inputs always produce the identical
    name; different versions always produce different names.
    """
    if isinstance(version, bool) or version <= 0:
        raise ValueError("versioned_vector_index version must be positive")
    digest = hashlib.blake2b(user_identifier.encode("utf-8"), digest_size=8).hexdigest()
    return cypher_var(f"{base_name}_tenant_{digest}_v{version}")


def introspect_vector_dimension(client: SchemaClient, name: str) -> int | None:
    """Best-effort dimension of an existing vector-bearing property.

    `name` is the auto-generated `"Type[property]"` index reference (the same
    literal form `vectorNeighbors`/`vector.sparseNeighbors` consume, per
    04-SPIKE-FINDINGS.md). Returns `None` when no record exists yet -- nothing
    to conflict with; see module docstring for why this samples data rather
    than reading index metadata.
    """
    match = _INDEX_REF_RE.match(name)
    if not match:
        raise ValueError(f"not a single-property vector index reference: {name!r}")
    type_name, property_name = match.group(1), match.group(2)
    rows = client.query(
        f"SELECT {property_name} AS vector FROM {type_name} "
        f"WHERE {property_name} IS NOT NULL LIMIT 1"
    )
    if not rows:
        return None
    vector = rows[0].get("vector")
    if not isinstance(vector, list):
        return None
    return len(vector)


def bootstrap(client: SchemaClient, *, dimensions: int, version: int = 1) -> SchemaBootstrapConfig:
    """Idempotently create the full ArcadeDB schema contract (D-09).

    Running this twice against the same database issues no failing/duplicate
    DDL -- type/property creation is natively idempotent (`IF NOT EXISTS`);
    index creation catches its own "already exists" error as a benign no-op.
    """
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


def _bootstrap_user_identity(client: SchemaClient) -> None:
    _create_property_if_missing(client, "User", "identifier", "STRING")
    _create_index_idempotent(client, "CREATE INDEX ON User (identifier) UNIQUE")


def _bootstrap_stable_id(client: SchemaClient, type_name: str) -> None:
    _create_property_if_missing(client, type_name, "id", "STRING")
    _create_index_idempotent(client, f"CREATE INDEX ON {type_name} (id) UNIQUE")


def _bootstrap_vector_channel(
    client: SchemaClient, type_name: str, config: SchemaBootstrapConfig
) -> None:
    _create_property_if_missing(client, type_name, _EMBEDDING_PROPERTY, "ARRAY_OF_FLOATS")
    existing = introspect_vector_dimension(client, f"{type_name}[{_EMBEDDING_PROPERTY}]")
    if existing is not None and existing != config.dimensions:
        raise ValueError(
            f"{type_name}.{_EMBEDDING_PROPERTY} vector dimension mismatch: "
            f"expected {config.dimensions}, found {existing}"
        )
    metadata = (
        f'{{"dimensions": {config.dimensions}, "similarity": "cosine", '
        f'"maxConnections": {config.max_connections}, "beamWidth": {config.beam_width}}}'
    )
    _create_index_idempotent(
        client,
        f"CREATE INDEX ON {type_name} ({_EMBEDDING_PROPERTY}) LSM_VECTOR METADATA {metadata}",
    )


def _bootstrap_lexical_channel(client: SchemaClient, type_name: str) -> None:
    _create_property_if_missing(client, type_name, _LEXICAL_TOKENS_PROPERTY, "ARRAY_OF_INTEGERS")
    _create_property_if_missing(client, type_name, _LEXICAL_WEIGHTS_PROPERTY, "ARRAY_OF_FLOATS")
    _create_index_idempotent(
        client,
        f"CREATE INDEX ON {type_name} ({_LEXICAL_TOKENS_PROPERTY}, "
        f"{_LEXICAL_WEIGHTS_PROPERTY}) LSM_SPARSE_VECTOR",
    )


def _bootstrap_full_text_channel(client: SchemaClient, type_name: str) -> None:
    """Native Lucene `FULL_TEXT` index on the type's raw text property.

    DDL form (`CREATE INDEX ON <type> (<property>) FULL_TEXT`, no `METADATA`
    analyzer block -- default `StandardAnalyzer`) was empirically verified
    live against `arcadedata/arcadedb:26.7.1` for this amendment, matching the
    form `scripts/arcadedb_spike.py` already proved for its `SEARCH_INDEX`
    bake-off channel. Feeds the same Python RRF as `LSM_SPARSE_VECTOR`
    (both-channels decision -- see module docstring).
    """
    property_name = _FULL_TEXT_PROPERTY_BY_TYPE[type_name]
    _create_property_if_missing(client, type_name, property_name, "STRING")
    _create_index_idempotent(client, f"CREATE INDEX ON {type_name} ({property_name}) FULL_TEXT")


def _create_type_if_missing(client: SchemaClient, kind: str, name: str) -> None:
    client.command(f"CREATE {kind} TYPE {name} IF NOT EXISTS")


def _create_property_if_missing(
    client: SchemaClient, type_name: str, property_name: str, data_type: str
) -> None:
    client.command(f"CREATE PROPERTY {type_name}.{property_name} IF NOT EXISTS {data_type}")


def _create_index_idempotent(client: SchemaClient, statement: str) -> None:
    try:
        client.command(statement)
    except Exception as exc:
        if _ALREADY_EXISTS_MARKER not in str(exc).lower():
            raise
