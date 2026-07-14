"""ArcadeDB SQL query/param builders for fused memory search + evidence
traversal (04-07).

Split out of `store_search.py`/`store_evidence.py` to keep both under the
600-LOC cap, mirroring `store_memory_queries.py`/`store_documents_queries.py`'s
`Statement` (`(sql, params)` tuple) builder convention (04-05/04-06). Every
builder here binds ALL data values -- including query vectors and multi-id
lookups -- as `?`/`:named` params; no `ids.quote()`/`cypher_var()` string
interpolation anywhere (04-SPIKE-FINDINGS.md: bound params are strictly better
than any inline-literal quoting scheme, confirmed live for 26.7.1).

Three seed-channel shapes, one generic builder each, reused across every
content-bearing type (Memory/Fact/Entity/Community):

- `dense_search_statement` -- native HNSW `vectorNeighbors("Type[embedding]",
  :vec, :k)` (D-03 over-fetch-then-filter default). Returns the raw `distance`
  column (cosine distance, 0 = identical) -- callers convert to a
  higher-is-better similarity score themselves (matching `store_documents.py`'s
  `max(0.0, 1.0 - distance)` precedent), since `_collect_retrieval_evidence`
  sorts every channel by `-raw_score` uniformly.
- `sparse_search_statement` -- the BOTH-channels decision's first lexical
  channel, native `vector.sparseNeighbors("Type[lexical_tokens,lexical_weights]",
  :qi, :qv, :k)` (D-04 spike winner). `:qi`/`:qv` are the SAME
  `sparse_encoder.sparse_vector()` encoding the write side already populated
  (04-05) -- query-side callers MUST reuse that exact function, never a second
  tokenizer, or the channel silently degrades. Exposes a `score` column
  (higher = more relevant, per the D-04 spike/capabilities-doc framing of a
  BM25/IDF-style score -- distinct from `vectorNeighbors`' distance
  convention; this asymmetry is intentional, not an oversight).
- `lucene_search_statement` -- the BOTH-channels decision's second lexical
  channel, native `SEARCH_INDEX("Type[content]", :q) ORDER BY $score DESC`.
  Reuses `store_documents_queries.escape_lucene_query` (04-06) rather than
  re-deriving the Lucene-special-character escape -- unescaped `?`/`*`/`(`/`)`
  can raise `IndexException` (04-SPIKE-FINDINGS.md Unknown 4, load-bearing).

Graph surface (D-05, SQL `MATCH`, not openCypher -- composes with the vector/
full-text functions above in the same query language):

- `entity_traversal_statement` -- the entity-to-fact-to-memory traversal
  (`SUBJECT_OF`/`OBJECT_OF`, direct or via one intermediate entity hop over any
  edge type -- `.both()`, matching the retired Cypher `(e:Entity)--(n:Entity)`
  undirected step) in ArcadeDB's object-notation `MATCH {type: ..., as: ...,
  where: (...)}.out('Kind'){as: ...}` form -- the ONLY form the D-05 spike
  empirically confirmed live for 26.7.1 (`scripts/arcadedb_spike.py`'s
  `run_graph_surface_bakeoff`); the simplified Cypher-like
  `(variable:type {property: value})` pattern some generic ArcadeDB docs show
  is the retired literal shape this whole phase ports away from. `entity_ids`
  binds as a JSON array to `id IN :entity_ids` -- the same bound-array-IN
  pattern `store_memory_queries.memory_delete_statements` already established
  for `fact_ids` (04-05), extended here to the MATCH `where:` clause.

Multi-id lookups (replacing every string-built `" OR ".join(...)` OR-list --
Pattern 4, the plan's hard prohibition): `fact_sources_by_ids_statement`,
`community_sources_by_ids_statement`, `memory_rows_by_ids_statement` all bind
a single `id IN :xxx_ids` array param.
"""

from __future__ import annotations

from turing_agentmemory_mcp.store_documents_queries import escape_lucene_query
from turing_agentmemory_mcp.store_memory_queries import MEMORY_FIELDS

Statement = tuple[str, dict[str, object]]

_ENTITY_EDGE_KINDS: tuple[str, ...] = ("SUBJECT_OF", "OBJECT_OF")


def dense_search_statement(
    *,
    type_name: str,
    embedding: list[float],
    k: int,
    user_identifier: str,
    extra_fields: tuple[str, ...] = (),
) -> Statement:
    fields = ", ".join(("id", *extra_fields, "distance"))
    return (
        f"SELECT {fields} FROM "
        f'(SELECT expand(vectorNeighbors("{type_name}[embedding]", :vec, :k))) '
        "WHERE user_identifier = :user_identifier AND status = 'active'",
        {"vec": embedding, "k": k, "user_identifier": user_identifier},
    )


def sparse_search_statement(
    *,
    type_name: str,
    tokens: list[int],
    weights: list[float],
    k: int,
    user_identifier: str,
    extra_fields: tuple[str, ...] = (),
) -> Statement:
    fields = ", ".join(("id", *extra_fields, "score"))
    return (
        f"SELECT {fields} FROM "
        "(SELECT expand(vector.sparseNeighbors("
        f'"{type_name}[lexical_tokens,lexical_weights]", :qi, :qv, :k))) '
        "WHERE user_identifier = :user_identifier AND status = 'active'",
        {"qi": tokens, "qv": weights, "k": k, "user_identifier": user_identifier},
    )


def lucene_search_statement(
    *,
    type_name: str,
    query: str,
    limit: int,
    user_identifier: str,
    extra_fields: tuple[str, ...] = (),
) -> Statement:
    fields = ", ".join(("id", *extra_fields, "$score AS score"))
    return (
        f'SELECT {fields} FROM {type_name} WHERE SEARCH_INDEX("{type_name}[content]", :q) '
        "AND user_identifier = :user_identifier AND status = 'active' "
        f"ORDER BY $score DESC LIMIT {int(limit)}",
        {"q": escape_lucene_query(query), "user_identifier": user_identifier},
    )


def entity_traversal_statement(
    *,
    edge_kind: str,
    hop: int,
    entity_ids: list[str],
    user_identifier: str,
) -> Statement:
    if edge_kind not in _ENTITY_EDGE_KINDS:
        raise ValueError(f"unsupported entity traversal edge kind: {edge_kind!r}")
    if hop not in (1, 2):
        raise ValueError(
            "entity traversal hop must be 1 (direct) or 2 (via an intermediate entity)"
        )
    pattern = (
        "{type: Entity, as: e, where: (id IN :entity_ids "
        "AND user_identifier = :user_identifier AND status = 'active')}"
    )
    if hop == 2:
        # Undirected any-edge-type hop to an intermediate entity -- mirrors the
        # retired Cypher `(e:Entity)--(n:Entity)` step (dynamic per-predicate
        # entity-to-entity edges are unbounded vocabulary, store_memory_queries.py).
        # Every hop re-asserts user_identifier -- CLAUDE.md invariant #1 is the
        # only isolation backstop in this single-shared-database model, so no
        # intermediate vertex may rely solely on the seed's scoping (CR-01).
        pattern += (
            ".both(){as: n, where: (user_identifier = :user_identifier AND status = 'active')}"
        )
    pattern += (
        f".out('{edge_kind}'){{as: f, where: "
        "(user_identifier = :user_identifier AND status = 'active')}}"
        ".out('SUPPORTED_BY'){as: m, where: "
        "(user_identifier = :user_identifier AND status = 'active')}"
    )
    return (
        f"MATCH {pattern} RETURN m.id AS memory_id, f.id AS fact_id, "
        "f.confidence AS confidence, e.id AS entity_id",
        {"entity_ids": list(entity_ids), "user_identifier": user_identifier},
    )


def fact_sources_by_ids_statement(*, fact_ids: list[str], user_identifier: str) -> Statement:
    return (
        "SELECT id, source_memory_id, confidence FROM Fact WHERE id IN :fact_ids "
        "AND user_identifier = :user_identifier AND status = 'active'",
        {"fact_ids": list(fact_ids), "user_identifier": user_identifier},
    )


def community_sources_by_ids_statement(
    *, community_ids: list[str], user_identifier: str
) -> Statement:
    return (
        "SELECT id, source_memory_ids_json FROM Community WHERE id IN :community_ids "
        "AND user_identifier = :user_identifier AND status = 'active'",
        {"community_ids": list(community_ids), "user_identifier": user_identifier},
    )


def memory_rows_by_ids_statement(*, memory_ids: list[str], user_identifier: str) -> Statement:
    fields = ", ".join(MEMORY_FIELDS)
    return (
        f"SELECT {fields} FROM Memory WHERE id IN :memory_ids "
        "AND user_identifier = :user_identifier AND status = 'active'",
        {"memory_ids": list(memory_ids), "user_identifier": user_identifier},
    )
