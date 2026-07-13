"""ArcadeDB SQL query/param builders for document ingest/search (04-06).

Split out of `store_documents.py`/`store_chunking.py` to keep both under the
600-LOC cap, mirroring `store_memory_queries.py`'s `Statement` (`(sql, params)`
tuple) builder convention (04-05). A whole document ingest (Document vertex +
Chunk vertices + HAS_DOCUMENT/HAS_CHUNK/NEXT_CHUNK edges) is a flat list of
`Statement`s passed to `store_core.py`'s `_write_many` (D-08) -- ONE managed
transaction with read-your-writes, so a `NEXT_CHUNK` edge can always resolve
its `previous` endpoint whether it was committed moments ago in the SAME
batch or in an earlier request.

No legacy synthetic-integer join property anywhere (ARC-05): every Chunk's
`id` is `ids.stable_id()`, the dense `embedding` and both lexical channels
(`lexical_tokens`/`lexical_weights`, the both-channels decision) are inline
record properties. All data values are bound params -- `quote()`/`cypher_var()`
interpolation is not used here (Pitfall 2).

Document search runs two native ArcadeDB channels, both `user_identifier`-bound
and both keeping the D-03 adaptive over-fetch-then-filter default:
`vectorNeighbors("Chunk[embedding]", ...)` (dense HNSW) and
`SEARCH_INDEX("Chunk[text]", ...)` (Lucene full-text, exposing an orderable
`$score` -- 04-SPIKE-FINDINGS.md Unknown 4). `SEARCH_INDEX`'s query argument is
parsed as a raw Lucene query string -- `escape_lucene_query` neutralizes the
reserved characters the spike found could raise `IndexException` (`?`, `*`,
`(`, `)`, ...) before it reaches the query.
"""

from __future__ import annotations

import re

Statement = tuple[str, dict[str, object]]

DOCUMENT_FIELDS: tuple[str, ...] = (
    "id",
    "user_identifier",
    "title",
    "chunk_count",
    "chunk_chars",
    "text_hash",
    "source",
    "tags_json",
    "metadata_json",
    "created_at",
    "updated_at",
    "expires_at",
)

CHUNK_FIELDS: tuple[str, ...] = (
    "id",
    "document_id",
    "user_identifier",
    "title",
    "ordinal",
    "locator",
    "source",
    "tags_json",
    "metadata_json",
    "created_at",
    "updated_at",
    "expires_at",
    "text",
)

_LUCENE_SPECIAL_RE = re.compile(r'([+\-!(){}\[\]^"~*?:\\&|/])')


def escape_lucene_query(text: str) -> str:
    """Backslash-escape Lucene query-syntax special characters.

    04-SPIKE-FINDINGS.md Unknown 4: an unescaped `?`/`*`/`(`/`)`/etc. in the
    raw natural-language query can raise `IndexException` through
    `SEARCH_INDEX` -- this is the mandatory guard the spike flagged as
    load-bearing for any production query builder using that function.
    """
    return _LUCENE_SPECIAL_RE.sub(r"\\\1", text)


def document_create_statement(
    *,
    document_id: str,
    user_identifier: str,
    title: str,
    chunk_count: int,
    chunk_chars: int,
    text_hash: str,
    source: str,
    tags_json: str,
    metadata_json: str,
    created_at: str,
    updated_at: str,
    expires_at: str,
) -> Statement:
    return (
        "CREATE VERTEX Document SET id = :id, user_identifier = :user_identifier, "
        "title = :title, chunk_count = :chunk_count, chunk_chars = :chunk_chars, "
        "text_hash = :text_hash, source = :source, tags_json = :tags_json, "
        "metadata_json = :metadata_json, created_at = :created_at, updated_at = :updated_at, "
        "expires_at = :expires_at, status = 'searchable'",
        {
            "id": document_id,
            "user_identifier": user_identifier,
            "title": title,
            "chunk_count": chunk_count,
            "chunk_chars": chunk_chars,
            "text_hash": text_hash,
            "source": source,
            "tags_json": tags_json,
            "metadata_json": metadata_json,
            "created_at": created_at,
            "updated_at": updated_at,
            "expires_at": expires_at,
        },
    )


def document_edge_statement(*, user_identifier: str, document_id: str) -> Statement:
    return (
        "CREATE EDGE HAS_DOCUMENT FROM (SELECT FROM User WHERE identifier = :identifier) "
        "TO (SELECT FROM Document WHERE id = :id)",
        {"identifier": user_identifier, "id": document_id},
    )


def chunk_create_statement(
    *,
    chunk_id: str,
    document_id: str,
    user_identifier: str,
    title: str,
    ordinal: int,
    locator: str,
    source: str,
    tags_json: str,
    metadata_json: str,
    created_at: str,
    updated_at: str,
    expires_at: str,
    text: str,
    embedding: list[float],
    lexical_tokens: list[int],
    lexical_weights: list[float],
) -> Statement:
    return (
        "CREATE VERTEX Chunk SET id = :id, document_id = :document_id, "
        "user_identifier = :user_identifier, title = :title, ordinal = :ordinal, "
        "locator = :locator, source = :source, tags_json = :tags_json, "
        "metadata_json = :metadata_json, created_at = :created_at, updated_at = :updated_at, "
        "expires_at = :expires_at, status = 'active', text = :text, embedding = :embedding, "
        "lexical_tokens = :lexical_tokens, lexical_weights = :lexical_weights",
        {
            "id": chunk_id,
            "document_id": document_id,
            "user_identifier": user_identifier,
            "title": title,
            "ordinal": ordinal,
            "locator": locator,
            "source": source,
            "tags_json": tags_json,
            "metadata_json": metadata_json,
            "created_at": created_at,
            "updated_at": updated_at,
            "expires_at": expires_at,
            "text": text,
            "embedding": embedding,
            "lexical_tokens": lexical_tokens,
            "lexical_weights": lexical_weights,
        },
    )


def has_chunk_edge_statement(*, document_id: str, chunk_id: str, ordinal: int) -> Statement:
    return (
        "CREATE EDGE HAS_CHUNK FROM (SELECT FROM Document WHERE id = :document_id) "
        "TO (SELECT FROM Chunk WHERE id = :chunk_id) SET ordinal = :ordinal",
        {"document_id": document_id, "chunk_id": chunk_id, "ordinal": ordinal},
    )


def next_chunk_edge_statement(*, previous_chunk_id: str, chunk_id: str) -> Statement:
    return (
        "CREATE EDGE NEXT_CHUNK FROM (SELECT FROM Chunk WHERE id = :previous_id) "
        "TO (SELECT FROM Chunk WHERE id = :chunk_id)",
        {"previous_id": previous_chunk_id, "chunk_id": chunk_id},
    )


def document_select_statement(*, document_id: str, user_identifier: str) -> Statement:
    fields = ", ".join(DOCUMENT_FIELDS)
    return (
        f"SELECT {fields} FROM Document WHERE id = :id AND user_identifier = :user_identifier "
        "AND status = 'searchable'",
        {"id": document_id, "user_identifier": user_identifier},
    )


def document_update_statement(
    *,
    document_id: str,
    user_identifier: str,
    title: str,
    source: str,
    tags_json: str,
    metadata_json: str,
    expires_at: str,
    updated_at: str,
) -> Statement:
    return (
        "UPDATE Document SET title = :title, source = :source, tags_json = :tags_json, "
        "metadata_json = :metadata_json, expires_at = :expires_at, updated_at = :updated_at "
        "WHERE id = :id AND user_identifier = :user_identifier AND status = 'searchable'",
        {
            "id": document_id,
            "user_identifier": user_identifier,
            "title": title,
            "source": source,
            "tags_json": tags_json,
            "metadata_json": metadata_json,
            "expires_at": expires_at,
            "updated_at": updated_at,
        },
    )


def chunk_metadata_update_statement(
    *,
    document_id: str,
    user_identifier: str,
    title: str,
    source: str,
    tags_json: str,
    metadata_json: str,
    expires_at: str,
    updated_at: str,
) -> Statement:
    return (
        "UPDATE Chunk SET title = :title, source = :source, tags_json = :tags_json, "
        "metadata_json = :metadata_json, expires_at = :expires_at, updated_at = :updated_at "
        "WHERE document_id = :document_id AND user_identifier = :user_identifier "
        "AND status = 'active'",
        {
            "document_id": document_id,
            "user_identifier": user_identifier,
            "title": title,
            "source": source,
            "tags_json": tags_json,
            "metadata_json": metadata_json,
            "expires_at": expires_at,
            "updated_at": updated_at,
        },
    )


def document_delete_statement(
    *, document_id: str, user_identifier: str, updated_at: str
) -> Statement:
    return (
        "UPDATE Document SET status = 'deleted', updated_at = :updated_at "
        "WHERE id = :id AND user_identifier = :user_identifier",
        {"id": document_id, "user_identifier": user_identifier, "updated_at": updated_at},
    )


def chunk_delete_statement(*, document_id: str, user_identifier: str, updated_at: str) -> Statement:
    return (
        "UPDATE Chunk SET status = 'deleted', updated_at = :updated_at "
        "WHERE document_id = :document_id AND user_identifier = :user_identifier",
        {"document_id": document_id, "user_identifier": user_identifier, "updated_at": updated_at},
    )


def chunk_context_statement(*, chunk_id: str) -> Statement:
    return (
        "SELECT id AS chunk_id, locator, text FROM "
        "(SELECT expand(out('NEXT_CHUNK')) FROM Chunk WHERE id = :id) WHERE status = 'active'",
        {"id": chunk_id},
    )


def chunk_vector_search_statement(
    *, embedding: list[float], k: int, user_identifier: str, document_id: str = ""
) -> Statement:
    fields = ", ".join(CHUNK_FIELDS)
    clause = "user_identifier = :user_identifier AND status = 'active'"
    params: dict[str, object] = {
        "vec": embedding,
        "k": k,
        "user_identifier": user_identifier,
    }
    if document_id:
        clause += " AND document_id = :document_id"
        params["document_id"] = document_id
    return (
        f"SELECT {fields}, distance FROM "
        '(SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))) '
        f"WHERE {clause}",
        params,
    )


def chunk_lucene_search_statement(
    *, query: str, limit: int, user_identifier: str, document_id: str = ""
) -> Statement:
    fields = ", ".join(CHUNK_FIELDS)
    clause = "user_identifier = :user_identifier AND status = 'active'"
    params: dict[str, object] = {
        "q": escape_lucene_query(query),
        "user_identifier": user_identifier,
    }
    if document_id:
        clause += " AND document_id = :document_id"
        params["document_id"] = document_id
    return (
        f'SELECT {fields} FROM Chunk WHERE SEARCH_INDEX("Chunk[text]", :q) '
        f"AND {clause} ORDER BY $score DESC LIMIT {int(limit)}",
        params,
    )
