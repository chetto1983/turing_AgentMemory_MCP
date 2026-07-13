"""ArcadeDB SQL query/param builders for the memory write/read paths (04-05).

Split out of `store_memory_write.py`/`store_memory_read.py` to keep both under
the 600-LOC cap -- bound-param ArcadeDB SQL is more verbose per operation than
the retired Cypher-literal shape it replaces (04-PATTERNS.md). Every builder
here returns a `Statement` (`(sql, params)` tuple) consumed by `store_core.py`'s
`_write_many`/`_query` seam (04-04): a whole list of `Statement`s passed to
`_write_many` runs inside ONE managed transaction with read-your-writes across
every statement, so a `CREATE EDGE ... FROM (SELECT ...)` in the same batch
can find a vertex an earlier statement in the same batch just created.

No legacy synthetic-integer join property anywhere (ARC-05): `stable_id()`
(passed in as `id`/`*_id` values by callers) is the sole cross-record
identifier; the dense `embedding` is an inline record property. All data
values are bound params -- `quote()` interpolation is not used here (Pitfall 2).
"""

from __future__ import annotations

from turing_agentmemory_mcp.ids import cypher_var
from turing_agentmemory_mcp.temporal_graph import EdgeProjection, EntityProjection, FactProjection

Statement = tuple[str, dict[str, object]]

MEMORY_FIELDS: tuple[str, ...] = (
    "id",
    "user_identifier",
    "kind",
    "content",
    "session_id",
    "role",
    "created_at",
    "updated_at",
    "expires_at",
    "source",
    "tags_json",
    "metadata_json",
)

# Fixed edge kinds pre-registered by `arcadedb_schema.bootstrap` (04-03) and
# their (source type, target type), mirroring `temporal_graph.py`'s `_edge()`
# call sites. Any OTHER kind is a dynamic per-predicate edge
# (`fact.predicate.upper()`, temporal_graph.py:258) between two Entities --
# unbounded vocabulary, not pre-registered, so `projection_edge_statements`
# declares its type on demand (idempotent `IF NOT EXISTS`, 04-03 finding).
_FIXED_EDGE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "MENTIONS": ("Memory", "Entity"),
    "SUBJECT_OF": ("Entity", "Fact"),
    "OBJECT_OF": ("Entity", "Fact"),
    "SUPPORTED_BY": ("Fact", "Memory"),
}
_DYNAMIC_EDGE_ENDPOINTS = ("Entity", "Entity")


def memory_create_statement(
    *,
    memory_id: str,
    user_identifier: str,
    kind: str,
    content: str,
    session_id: str,
    role: str,
    source: str,
    tags_json: str,
    metadata_json: str,
    created_at: str,
    updated_at: str,
    expires_at: str,
    embedding: list[float],
    lexical_tokens: list[int],
    lexical_weights: list[float],
) -> Statement:
    return (
        "CREATE VERTEX Memory SET id = :id, user_identifier = :user_identifier, "
        "kind = :kind, content = :content, session_id = :session_id, role = :role, "
        "source = :source, tags_json = :tags_json, metadata_json = :metadata_json, "
        "created_at = :created_at, updated_at = :updated_at, expires_at = :expires_at, "
        "status = 'active', embedding = :embedding, lexical_tokens = :lexical_tokens, "
        "lexical_weights = :lexical_weights",
        {
            "id": memory_id,
            "user_identifier": user_identifier,
            "kind": kind,
            "content": content,
            "session_id": session_id,
            "role": role,
            "source": source,
            "tags_json": tags_json,
            "metadata_json": metadata_json,
            "created_at": created_at,
            "updated_at": updated_at,
            "expires_at": expires_at,
            "embedding": embedding,
            "lexical_tokens": lexical_tokens,
            "lexical_weights": lexical_weights,
        },
    )


def memory_edge_statement(*, user_identifier: str, memory_id: str) -> Statement:
    # Bound-param names deliberately mirror the target property name
    # (`identifier`/`id`, matching `store_core.py`'s `_ensure_user` convention)
    # rather than a caller-scoped name -- keeps every builder's param dict
    # trivially explainable as "the value that lands in this property".
    return (
        "CREATE EDGE HAS_MEMORY FROM (SELECT FROM User WHERE identifier = :identifier) "
        "TO (SELECT FROM Memory WHERE id = :id)",
        {"identifier": user_identifier, "id": memory_id},
    )


def entity_create_statement(
    entity: EntityProjection,
    *,
    embedding: list[float],
    lexical_tokens: list[int],
    lexical_weights: list[float],
) -> Statement:
    return (
        "CREATE VERTEX Entity SET id = :id, user_identifier = :user_identifier, "
        "entity_type = :entity_type, canonical_name = :canonical_name, "
        "display_name = :display_name, content = :content, confidence = :confidence, "
        "first_observed_at = :first_observed_at, last_observed_at = :last_observed_at, "
        "source_memory_id = :source_memory_id, schema_version = :schema_version, "
        "model = :model, expires_at = :expires_at, status = 'active', "
        "embedding = :embedding, lexical_tokens = :lexical_tokens, "
        "lexical_weights = :lexical_weights",
        {
            "id": entity.id,
            "user_identifier": entity.user_identifier,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "display_name": entity.display_name,
            "content": entity.content,
            "confidence": entity.confidence,
            "first_observed_at": entity.observed_at,
            "last_observed_at": entity.observed_at,
            "source_memory_id": entity.source_memory_id,
            "schema_version": entity.schema_version,
            "model": entity.model,
            "expires_at": entity.expires_at,
            "embedding": embedding,
            "lexical_tokens": lexical_tokens,
            "lexical_weights": lexical_weights,
        },
    )


def fact_create_statement(
    fact: FactProjection,
    *,
    tags_json: str,
    metadata_json: str,
    embedding: list[float],
    lexical_tokens: list[int],
    lexical_weights: list[float],
) -> Statement:
    return (
        "CREATE VERTEX Fact SET id = :id, user_identifier = :user_identifier, "
        "subject_entity_id = :subject_entity_id, predicate = :predicate, "
        "object_entity_id = :object_entity_id, content = :content, confidence = :confidence, "
        "observed_at = :observed_at, valid_from = :valid_from, valid_to = :valid_to, "
        "valid_time_precision = :valid_time_precision, source_memory_id = :source_memory_id, "
        "session_id = :session_id, speaker = :speaker, source = :source, "
        "tags_json = :tags_json, metadata_json = :metadata_json, "
        "schema_version = :schema_version, model = :model, expires_at = :expires_at, "
        "status = 'active', embedding = :embedding, lexical_tokens = :lexical_tokens, "
        "lexical_weights = :lexical_weights",
        {
            "id": fact.id,
            "user_identifier": fact.user_identifier,
            "subject_entity_id": fact.subject_entity_id,
            "predicate": fact.predicate,
            "object_entity_id": fact.object_entity_id,
            "content": fact.content,
            "confidence": fact.confidence,
            "observed_at": fact.observed_at,
            "valid_from": fact.valid_from,
            "valid_to": fact.valid_to,
            "valid_time_precision": fact.valid_time_precision,
            "source_memory_id": fact.source_memory_id,
            "session_id": fact.session_id,
            "speaker": fact.speaker,
            "source": fact.source,
            "tags_json": tags_json,
            "metadata_json": metadata_json,
            "schema_version": fact.schema_version,
            "model": fact.model,
            "expires_at": fact.expires_at,
            "embedding": embedding,
            "lexical_tokens": lexical_tokens,
            "lexical_weights": lexical_weights,
        },
    )


def projection_edge_statements(edges: tuple[EdgeProjection, ...]) -> list[Statement]:
    statements: list[Statement] = []
    declared_kinds: set[str] = set()
    for edge in edges:
        source_type, target_type = _FIXED_EDGE_ENDPOINTS.get(edge.kind, _DYNAMIC_EDGE_ENDPOINTS)
        kind = cypher_var(edge.kind).upper()
        if edge.kind not in _FIXED_EDGE_ENDPOINTS and kind not in declared_kinds:
            statements.append((f"CREATE EDGE TYPE {kind} IF NOT EXISTS", {}))
            declared_kinds.add(kind)
        properties: dict[str, object] = {"id": edge.id, **edge.properties}
        set_clause = ", ".join(f"{name} = :{name}" for name in properties)
        params: dict[str, object] = {
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            **properties,
        }
        statements.append(
            (
                f"CREATE EDGE {kind} FROM (SELECT FROM {source_type} WHERE id = :source_id) "
                f"TO (SELECT FROM {target_type} WHERE id = :target_id) SET {set_clause}",
                params,
            )
        )
    return statements


def memory_select_statement(*, memory_id: str, user_identifier: str) -> Statement:
    fields = ", ".join(MEMORY_FIELDS)
    return (
        f"SELECT {fields} FROM Memory WHERE id = :id "
        "AND user_identifier = :user_identifier AND status = 'active'",
        {"id": memory_id, "user_identifier": user_identifier},
    )


def memory_list_statement(*, user_identifier: str) -> Statement:
    fields = ", ".join(MEMORY_FIELDS)
    return (
        f"SELECT {fields} FROM Memory WHERE user_identifier = :user_identifier "
        "AND status = 'active'",
        {"user_identifier": user_identifier},
    )


def memory_update_statement(
    *,
    memory_id: str,
    user_identifier: str,
    kind: str,
    content: str,
    session_id: str,
    role: str,
    source: str,
    tags_json: str,
    metadata_json: str,
    expires_at: str,
    updated_at: str,
    lexical_tokens: list[int],
    lexical_weights: list[float],
    embedding: list[float] | None,
) -> Statement:
    params: dict[str, object] = {
        "id": memory_id,
        "user_identifier": user_identifier,
        "kind": kind,
        "content": content,
        "session_id": session_id,
        "role": role,
        "source": source,
        "tags_json": tags_json,
        "metadata_json": metadata_json,
        "expires_at": expires_at,
        "updated_at": updated_at,
        "lexical_tokens": lexical_tokens,
        "lexical_weights": lexical_weights,
    }
    set_terms = [
        "kind = :kind",
        "content = :content",
        "session_id = :session_id",
        "role = :role",
        "source = :source",
        "tags_json = :tags_json",
        "metadata_json = :metadata_json",
        "expires_at = :expires_at",
        "updated_at = :updated_at",
        "status = 'active'",
        "lexical_tokens = :lexical_tokens",
        "lexical_weights = :lexical_weights",
    ]
    if embedding is not None:
        set_terms.append("embedding = :embedding")
        params["embedding"] = embedding
    return (
        "UPDATE Memory SET "
        + ", ".join(set_terms)
        + " WHERE id = :id AND user_identifier = :user_identifier",
        params,
    )


def memory_delete_statements(
    *, memory_id: str, user_identifier: str, fact_ids: list[str], updated_at: str
) -> list[Statement]:
    statements: list[Statement] = [
        (
            "UPDATE Memory SET status = 'deleted', updated_at = :updated_at "
            "WHERE id = :id AND user_identifier = :user_identifier",
            {"id": memory_id, "user_identifier": user_identifier, "updated_at": updated_at},
        )
    ]
    if fact_ids:
        statements.append(
            ("UPDATE Fact SET status = 'deleted' WHERE id IN :fact_ids", {"fact_ids": fact_ids})
        )
    return statements
