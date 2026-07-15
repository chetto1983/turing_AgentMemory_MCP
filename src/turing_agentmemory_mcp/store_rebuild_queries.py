"""ArcadeDB SQL query/param + DDL builders for vector-projection and
community-graph rebuild (04-08, ARC-04/ARC-05/INFRA-03).

D-07 versioned atomic-swap (new logic, no in-repo analog -- see
04-PATTERNS.md "No Analog Found"): a rebuild never mutates the live
`embedding`/`lexical_tokens`/`lexical_weights` properties record-by-record
while it is still computing new values -- that in-place-mutation shape is
exactly what caused the known `memory_rebuild_vector_projection`
stale-vector bug under the old CSV-load model. Instead it stages every
freshly computed value into a tenant+version-namespaced scratch property
(named via `arcadedb_schema.versioned_vector_index`, reused verbatim --
04-03's naming seam, not a new scheme), backed by a real `LSM_VECTOR` index
so the staged version is independently ANN-queryable (D-07's stated
canary/rollback affordance). Only once EVERY active record has been staged
does the rebuild flip the live fields in ONE same-record field-to-field
`UPDATE ... SET embedding = <scratch property>` copy -- a single command
whose bound params never vary per record, so a search issued mid-rebuild
always sees either the fully-old or the fully-new state, never a mix. The
scratch property/index is dropped immediately after (self-cleanup; nothing
accumulates across repeated rebuilds -- Test 3's "no stale accumulation").

Community-graph replace (`community_replace_sqlscript`, Task 2) is a
distinct concern: Leiden re-clustering recomputes every active community's
full state in ONE `sqlscript` BEGIN/LET/COMMIT transaction, so the same
partial-visibility risk does not apply -- creating/updating Community
vertices and their `IN_COMMUNITY` edges is already atomic by virtue of being
one script call. The community embedding + both lexical channels are written
inline in that same script, not staged.

Every builder returns a `Statement` (`(sql, params)` tuple, mirroring
`store_memory_queries.py`'s 04-05 convention) or a plain DDL string for
schema-lifecycle calls issued directly via `ArcadeDBClient.command()` (not
wrapped in an app-level `_write`/`_write_many` transaction, matching
`arcadedb_schema.py`'s own precedent that schema mutations are not data
writes). Callers pre-compute JSON serialization and `sparse_encoder.
sparse_vector()` lexical encoding themselves (matching `store_memory_write.
py`'s established convention of computing `lexical_tokens`/`lexical_weights`
before calling into the query-builder layer) -- this module only builds SQL
text and never derives data values it doesn't receive. No `quote()` or
legacy synthetic-integer-id helper or `cypher_var()`-node-literal anywhere;
every data value is a bound param except the LET-variable references, which
are our own internally generated identifiers, never user input.
"""

from __future__ import annotations

from turing_agentmemory_mcp.arcadedb_schema import (
    DEFAULT_BEAM_WIDTH,
    DEFAULT_MAX_CONNECTIONS,
    versioned_vector_index,
)
from turing_agentmemory_mcp.ids import stable_id

Statement = tuple[str, dict[str, object]]

_LEX_TOKENS_SUFFIX = "_lex_tok"
_LEX_WEIGHTS_SUFFIX = "_lex_wt"


# -- D-07 staging/swap naming --------------------------------------------------


def vector_version_id(kind: str, user_identifier: str) -> str:
    """Deterministic key for the (kind, tenant) active-version pointer row."""
    return stable_id("vecver", kind, user_identifier)


def staging_property_names(
    base_index_name: str, user_identifier: str, version: int
) -> tuple[str, str, str]:
    """(embedding, lexical_tokens, lexical_weights) scratch property names for
    this rebuild cycle -- all namespaced via `versioned_vector_index` (04-03),
    never a new naming scheme."""
    return (
        versioned_vector_index(base_index_name, user_identifier, version),
        versioned_vector_index(f"{base_index_name}{_LEX_TOKENS_SUFFIX}", user_identifier, version),
        versioned_vector_index(f"{base_index_name}{_LEX_WEIGHTS_SUFFIX}", user_identifier, version),
    )


# -- D-07 schema DDL (issued directly via client.command(), not _write*) ------


def vector_version_schema_ddl() -> list[str]:
    return [
        "CREATE VERTEX TYPE VectorVersion IF NOT EXISTS",
        "CREATE PROPERTY VectorVersion.id IF NOT EXISTS STRING",
        "CREATE PROPERTY VectorVersion.user_identifier IF NOT EXISTS STRING",
        "CREATE PROPERTY VectorVersion.version IF NOT EXISTS INTEGER",
        "CREATE INDEX ON VectorVersion (id) UNIQUE",
    ]


def staging_vector_schema_ddl(type_name: str, property_name: str, *, dimensions: int) -> list[str]:
    metadata = (
        f'{{"dimensions": {dimensions}, "similarity": "cosine", '
        f'"maxConnections": {DEFAULT_MAX_CONNECTIONS}, "beamWidth": {DEFAULT_BEAM_WIDTH}}}'
    )
    return [
        f"CREATE PROPERTY {type_name}.{property_name} IF NOT EXISTS ARRAY_OF_FLOATS",
        f"CREATE INDEX ON {type_name} ({property_name}) LSM_VECTOR METADATA {metadata}",
    ]


def staging_lexical_schema_ddl(
    type_name: str, tokens_property: str, weights_property: str
) -> list[str]:
    return [
        f"CREATE PROPERTY {type_name}.{tokens_property} IF NOT EXISTS ARRAY_OF_INTEGERS",
        f"CREATE PROPERTY {type_name}.{weights_property} IF NOT EXISTS ARRAY_OF_FLOATS",
    ]


def drop_staging_vector_index_ddl(type_name: str, property_name: str) -> str:
    return f"DROP INDEX `{type_name}[{property_name}]`"


def drop_staging_property_ddl(type_name: str, property_name: str) -> str:
    return f"DROP PROPERTY {type_name}.{property_name} IF EXISTS"


# -- D-07 data statements ------------------------------------------------------


def vector_version_select_statement(*, version_id: str, user_identifier: str) -> Statement:
    return (
        "SELECT version FROM VectorVersion WHERE id = :id AND user_identifier = :user_identifier",
        {"id": version_id, "user_identifier": user_identifier},
    )


def vector_version_create_statement(
    *, version_id: str, version: int, user_identifier: str
) -> Statement:
    return (
        "CREATE VERTEX VectorVersion SET id = :id, "
        "user_identifier = :user_identifier, version = :version",
        {"id": version_id, "user_identifier": user_identifier, "version": version},
    )


def vector_version_update_statement(
    *, version_id: str, version: int, user_identifier: str
) -> Statement:
    return (
        "UPDATE VectorVersion SET version = :version WHERE id = :id "
        "AND user_identifier = :user_identifier",
        {"id": version_id, "user_identifier": user_identifier, "version": version},
    )


def stage_vector_statement(
    *,
    type_name: str,
    staging_embedding_property: str,
    staging_tokens_property: str,
    staging_weights_property: str,
    record_id: str,
    embedding: list[float],
    lexical_tokens: list[int],
    lexical_weights: list[float],
    user_identifier: str,
) -> Statement:
    return (
        f"UPDATE {type_name} SET {staging_embedding_property} = :embedding, "
        f"{staging_tokens_property} = :lexical_tokens, "
        f"{staging_weights_property} = :lexical_weights WHERE id = :id "
        "AND user_identifier = :user_identifier",
        {
            "id": record_id,
            "embedding": embedding,
            "lexical_tokens": lexical_tokens,
            "lexical_weights": lexical_weights,
            "user_identifier": user_identifier,
        },
    )


def swap_vector_statement(
    *,
    type_name: str,
    user_identifier: str,
    staging_embedding_property: str,
    staging_tokens_property: str,
    staging_weights_property: str,
) -> Statement:
    """The atomic swap: ONE bulk same-record field-to-field copy from the
    fully-populated scratch properties into the live, search-queried
    `embedding`/`lexical_tokens`/`lexical_weights` -- no bound param varies
    per record, so this is a single command regardless of match count."""
    return (
        f"UPDATE {type_name} SET embedding = {staging_embedding_property}, "
        f"lexical_tokens = {staging_tokens_property}, "
        f"lexical_weights = {staging_weights_property} "
        "WHERE user_identifier = :user_identifier AND status = 'active'",
        {"user_identifier": user_identifier},
    )


def canonical_vector_records_statement(
    *, type_name: str, text_property: str, user_identifier: str, status: str = "active"
) -> Statement:
    return (
        f"SELECT id, {text_property} FROM {type_name} "
        "WHERE user_identifier = :user_identifier AND status = :status",
        {"user_identifier": user_identifier, "status": status},
    )


# -- cross-mixin dependencies ported from store_memory_write.py/
# store_memory_read.py's call sites (04-05 heads-up: these two were still
# Cypher-shaped and stubbed in that plan's own test double) --------------------


def fact_ids_for_memory_statement(*, user_identifier: str, memory_id: str) -> Statement:
    return (
        "SELECT id FROM Fact WHERE user_identifier = :user_identifier "
        "AND source_memory_id = :memory_id AND status = 'active'",
        {"user_identifier": user_identifier, "memory_id": memory_id},
    )


def existing_entity_ids_statement(*, user_identifier: str, entity_ids: list[str]) -> Statement:
    return (
        "SELECT id FROM Entity WHERE user_identifier = :user_identifier AND id IN :entity_ids",
        {"user_identifier": user_identifier, "entity_ids": list(entity_ids)},
    )


# -- community rebuild inputs --------------------------------------------------


def community_entities_statement(*, user_identifier: str) -> Statement:
    return (
        "SELECT id, display_name, entity_type, confidence, source_memory_id FROM Entity "
        "WHERE user_identifier = :user_identifier AND status = 'active'",
        {"user_identifier": user_identifier},
    )


def community_mentions_statement(*, user_identifier: str) -> Statement:
    """One row per Memory; `entity_id` is the list of MENTIONS-linked Entity
    ids for that memory (ArcadeDB's `out('EdgeType').property` collection
    form) -- callers flatten it, replacing the retired one-row-per-mention
    Cypher shape."""
    return (
        "SELECT id AS memory_id, out('MENTIONS').id AS entity_id FROM Memory "
        "WHERE user_identifier = :user_identifier AND status = 'active'",
        {"user_identifier": user_identifier},
    )


def community_facts_statement(*, user_identifier: str) -> Statement:
    return (
        "SELECT id, subject_entity_id, predicate, object_entity_id, content, confidence, "
        "observed_at, source_memory_id FROM Fact "
        "WHERE user_identifier = :user_identifier AND status = 'active'",
        {"user_identifier": user_identifier},
    )


def active_community_ids_statement(*, user_identifier: str) -> Statement:
    return (
        "SELECT id FROM Community WHERE user_identifier = :user_identifier AND status = 'active'",
        {"user_identifier": user_identifier},
    )


# -- Task 2: community-graph replace, sqlscript+LET ---------------------------


def community_replace_sqlscript(
    *,
    user_identifier: str,
    prepared: list[dict[str, object]],
    existing_ids: set[str],
    timestamp: str,
) -> Statement:
    """One BEGIN/LET/COMMIT script (04-RESEARCH.md Pattern 1): stale-mark
    every previously active Community, then either UPDATE-in-place a
    projection whose id already existed (refresh only, no edge changes --
    matches the pre-port semantics) or CREATE a brand-new Community vertex +
    its `IN_COMMUNITY` edges, LET-bound so the edges can reference the
    vertex this SAME script just created. Each `prepared` entry is a plain
    dict with keys: id, content, member_ids (list[str]), member_ids_json,
    source_memory_ids_json, fact_ids_json, confidence, level, parent_id,
    edge_weight, embedding, lexical_tokens, lexical_weights -- all
    precomputed by the caller (`store_rebuild.py`). Embedding + both lexical
    channels are inline; no legacy synthetic-integer join property anywhere;
    every value is a bound param except the LET variable references.
    """
    params: dict[str, object] = {"user_identifier": user_identifier, "timestamp": timestamp}
    statements: list[str] = [
        "UPDATE Community SET status = 'stale', updated_at = :timestamp "
        "WHERE user_identifier = :user_identifier AND status = 'active';"
    ]
    for index, entry in enumerate(prepared):
        prefix = f"c{index}"
        params.update(
            {
                f"{prefix}_id": entry["id"],
                f"{prefix}_content": entry["content"],
                f"{prefix}_member_ids_json": entry["member_ids_json"],
                f"{prefix}_source_memory_ids_json": entry["source_memory_ids_json"],
                f"{prefix}_fact_ids_json": entry["fact_ids_json"],
                f"{prefix}_confidence": entry["confidence"],
                f"{prefix}_level": entry["level"],
                f"{prefix}_parent_id": entry["parent_id"],
                f"{prefix}_edge_weight": entry["edge_weight"],
                f"{prefix}_timestamp": timestamp,
                f"{prefix}_embedding": entry["embedding"],
                f"{prefix}_lexical_tokens": entry["lexical_tokens"],
                f"{prefix}_lexical_weights": entry["lexical_weights"],
            }
        )
        if entry["id"] in existing_ids:
            statements.append(
                f"UPDATE Community SET content = :{prefix}_content, "
                f"member_ids_json = :{prefix}_member_ids_json, "
                f"source_memory_ids_json = :{prefix}_source_memory_ids_json, "
                f"fact_ids_json = :{prefix}_fact_ids_json, "
                f"confidence = :{prefix}_confidence, level = :{prefix}_level, "
                f"parent_id = :{prefix}_parent_id, edge_weight = :{prefix}_edge_weight, "
                f"updated_at = :{prefix}_timestamp, status = 'active', "
                f"embedding = :{prefix}_embedding, lexical_tokens = :{prefix}_lexical_tokens, "
                f"lexical_weights = :{prefix}_lexical_weights "
                f"WHERE id = :{prefix}_id AND user_identifier = :user_identifier;"
            )
            continue
        community_var = f"$community_{prefix}"
        statements.append(
            f"LET {community_var} = CREATE VERTEX Community SET id = :{prefix}_id, "
            "user_identifier = :user_identifier, "
            f"content = :{prefix}_content, member_ids_json = :{prefix}_member_ids_json, "
            f"source_memory_ids_json = :{prefix}_source_memory_ids_json, "
            f"fact_ids_json = :{prefix}_fact_ids_json, confidence = :{prefix}_confidence, "
            f"level = :{prefix}_level, parent_id = :{prefix}_parent_id, "
            f"edge_weight = :{prefix}_edge_weight, created_at = :{prefix}_timestamp, "
            f"updated_at = :{prefix}_timestamp, status = 'active', "
            f"embedding = :{prefix}_embedding, lexical_tokens = :{prefix}_lexical_tokens, "
            f"lexical_weights = :{prefix}_lexical_weights;"
        )
        for member_index, member_id in enumerate(entry["member_ids"]):  # type: ignore[arg-type]
            member_param = f"{prefix}_member_{member_index}"
            params[member_param] = member_id
            statements.append(
                f"CREATE EDGE IN_COMMUNITY FROM (SELECT FROM Entity "
                f"WHERE id = :{member_param} AND user_identifier = :user_identifier) "
                f"TO {community_var};"
            )
    body = "BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;"
    return body, params
