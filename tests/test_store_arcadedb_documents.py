"""04-06: document ingest/chunking/search paths ported from TuringDB to ArcadeDB
(ARC-04/05/06, PERF-01).

Every test runs against `_FakeArcadeDBClient`, a small session-aware in-memory
stand-in for `ArcadeDBClient` (same convention as `tests/test_store_arcadedb_memory.py`'s
fake, extended here to interpret `vectorNeighbors(...)`/`SEARCH_INDEX(...)`/
`out('NEXT_CHUNK')` well enough to round-trip through `store_documents.py`/
`store_chunking.py`'s real bound-param statements) -- no live ArcadeDB
container is required.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder

from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.store_documents_queries import escape_lucene_query

_STORE_DOCUMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_documents.py"
)
_STORE_CHUNKING_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_chunking.py"
)
_STORE_DOCUMENTS_QUERIES_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "turing_agentmemory_mcp"
    / "store_documents_queries.py"
)

_CREATE_TYPE_RE = re.compile(r"CREATE VERTEX (\w+)", re.IGNORECASE)
_CREATE_EDGE_RE = re.compile(r"CREATE EDGE (\w+)", re.IGNORECASE)
_UPDATE_TYPE_RE = re.compile(r"UPDATE (\w+)", re.IGNORECASE)
_DELETE_TYPE_RE = re.compile(r"DELETE FROM (\w+)", re.IGNORECASE)
_SELECT_FROM_RE = re.compile(r"FROM (\w+)", re.IGNORECASE)
_MATCH_KEYS = ("id", "user_identifier", "identifier", "document_id")


def _euclidean(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=False)) ** 0.5


class _FakeArcadeDBClient:
    """Session-aware in-memory stand-in interpreting this plan's exact
    statement shapes (`CREATE VERTEX <Type> SET ...`, `CREATE EDGE <Type> FROM
    (SELECT ...) TO (SELECT ...)`, `SELECT ... FROM (SELECT expand(
    vectorNeighbors(...)))`, `SELECT ... FROM <Type> WHERE SEARCH_INDEX(...)`,
    `SELECT ... FROM (SELECT expand(out('NEXT_CHUNK')) ...)`) well enough to
    round-trip a real `store_documents.py`/`store_chunking.py` call -- not a
    general SQL engine.
    """

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, object] | None, str | None]] = []
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self._committed: list[dict[str, object]] = []
        self._edges: list[tuple[str, str, str]] = []
        self._session_rows: dict[str, list[dict[str, object]]] = {}
        self._session_edges: dict[str, list[tuple[str, str, str]]] = {}
        self._session_counter = 0

    # -- transaction control (mirrors ArcadeDBClient's session-header model) --

    def begin(self) -> str:
        self.begin_calls += 1
        self._session_counter += 1
        session_id = f"session-{self._session_counter}"
        self._session_rows[session_id] = []
        self._session_edges[session_id] = []
        return session_id

    def commit(self, session_id: str) -> None:
        self.commit_calls += 1
        self._committed.extend(self._session_rows.pop(session_id, []))
        self._edges.extend(self._session_edges.pop(session_id, []))

    def rollback(self, session_id: str) -> None:
        self.rollback_calls += 1
        self._session_rows.pop(session_id, None)
        self._session_edges.pop(session_id, None)

    def run_in_transaction(self, body: Any, *, commit_retries: int | None = None) -> Any:
        session_id = self.begin()
        try:
            result = body(session_id)
        except Exception:
            self.rollback(session_id)
            raise
        self.commit(session_id)
        return result

    def is_ready(self) -> bool:
        return True

    # -- query/command --

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.queries.append((statement, params))
        return self._select(statement, params, session_id)

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.commands.append((statement, params, session_id))
        upper = statement.strip().upper()
        if upper.startswith("SELECT"):
            return self._select(statement, params, session_id)
        if upper.startswith("CREATE VERTEX"):
            match = _CREATE_TYPE_RE.match(statement)
            row = dict(params or {})
            row["_type"] = match.group(1) if match else ""
            bucket = session_id or "__no_session__"
            self._session_rows.setdefault(bucket, []).append(row)
            return []
        if upper.startswith("UPDATE"):
            match = _UPDATE_TYPE_RE.match(statement)
            record_type = match.group(1) if match else ""
            bucket = session_id or "__no_session__"
            match_params = {k: v for k, v in (params or {}).items() if k in _MATCH_KEYS}
            for row in self._committed + self._session_rows.get(bucket, []):
                if row.get("_type") != record_type:
                    continue
                if all(row.get(k) == v for k, v in match_params.items()):
                    row.update({k: v for k, v in (params or {}).items() if k not in ("id",)})
            return []
        if upper.startswith("DELETE FROM"):
            match = _DELETE_TYPE_RE.match(statement)
            record_type = match.group(1) if match else ""
            bucket = session_id or "__no_session__"
            match_params = {k: v for k, v in (params or {}).items() if k in _MATCH_KEYS}
            for target in (self._committed, self._session_rows.setdefault(bucket, [])):
                target[:] = [
                    row
                    for row in target
                    if row.get("_type") != record_type
                    or not all(row.get(k) == v for k, v in match_params.items())
                ]
            return []
        if upper.startswith("CREATE EDGE"):
            match = _CREATE_EDGE_RE.match(statement)
            edge_type = match.group(1) if match else ""
            params = params or {}
            source_id = (
                params.get("identifier") or params.get("document_id") or params.get("previous_id")
            )
            target_id = params.get("id") or params.get("chunk_id")
            bucket = session_id or "__no_session__"
            self._session_edges.setdefault(bucket, []).append(
                (edge_type, str(source_id or ""), str(target_id or ""))
            )
            return []
        return []

    def _select(
        self, statement: str, params: dict[str, object] | None, session_id: str | None
    ) -> list[dict[str, object]]:
        bucket = session_id or "__no_session__"
        visible = list(self._committed) + list(self._session_rows.get(bucket, []))
        upper = statement.upper()
        if "VECTORNEIGHBORS" in upper:
            return self._vector_neighbors(params, visible)
        if "SEARCH_INDEX" in upper:
            return self._lucene_search(params, visible)
        if "NEXT_CHUNK" in upper and "OUT(" in upper:
            return self._chunk_context(params, session_id)
        match = _SELECT_FROM_RE.search(statement)
        record_type = match.group(1) if match else None
        if record_type:
            visible = [row for row in visible if row.get("_type") == record_type]
        if not params:
            return visible
        return [row for row in visible if all(row.get(k) == v for k, v in params.items())]

    def _vector_neighbors(
        self, params: dict[str, object] | None, visible: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        params = params or {}
        query_vec = list(params.get("vec") or [])
        k = int(params.get("k") or 0)
        filter_params = {key: value for key, value in params.items() if key not in ("vec", "k")}
        candidates = [row for row in visible if row.get("_type") == "Chunk"]
        scored = sorted(
            ((_euclidean(query_vec, list(row.get("embedding") or [])), row) for row in candidates),
            key=lambda pair: pair[0],
        )
        # D-03: the filter is applied AFTER the top-k slice -- post-filter
        # k-underfill, matching the live-confirmed spike behavior.
        top = scored[:k]
        results: list[dict[str, object]] = []
        for distance, row in top:
            if not all(row.get(key) == value for key, value in filter_params.items()):
                continue
            enriched = dict(row)
            enriched["distance"] = distance
            results.append(enriched)
        return results

    def _lucene_search(
        self, params: dict[str, object] | None, visible: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        params = params or {}
        query_text = str(params.get("q") or "").lower()
        tokens = [token for token in re.split(r"\W+", query_text) if token]
        filter_params = {key: value for key, value in params.items() if key != "q"}
        matches: list[dict[str, object]] = []
        for row in visible:
            if row.get("_type") != "Chunk":
                continue
            if not all(row.get(key) == value for key, value in filter_params.items()):
                continue
            text = str(row.get("text") or "").lower()
            if any(token in text for token in tokens):
                matches.append(row)
        return matches

    def _chunk_context(
        self, params: dict[str, object] | None, session_id: str | None
    ) -> list[dict[str, object]]:
        source_id = str((params or {}).get("id") or "")
        bucket = session_id or "__no_session__"
        edges = self._edges + self._session_edges.get(bucket, [])
        target_ids = {
            target for kind, source, target in edges if kind == "NEXT_CHUNK" and source == source_id
        }
        rows = self._committed + self._session_rows.get(bucket, [])
        return [
            {
                "chunk_id": row.get("id", ""),
                "locator": row.get("locator", ""),
                "text": row.get("text", ""),
            }
            for row in rows
            if row.get("_type") == "Chunk" and row.get("id") in target_ids
        ]


def _make_store(
    client: _FakeArcadeDBClient, tmp_path: Path, embedder: CountingBatchEmbedder
) -> TuringAgentMemory:
    return TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=embedder,
        reranker=None,
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
    )


def _committed_by_type(client: _FakeArcadeDBClient, record_type: str) -> list[dict[str, object]]:
    return [row for row in client._committed if row.get("_type") == record_type]


def _edge_commands(
    client: _FakeArcadeDBClient, edge_type: str
) -> list[tuple[str, dict, str | None]]:
    prefix = f"CREATE EDGE {edge_type}"
    return [entry for entry in client.commands if entry[0].startswith(prefix)]


# -- Task 1, Test 1: ingest CREATEs one Document + N Chunk vertices + N
# HAS_CHUNK + (N-1) NEXT_CHUNK edges in ONE managed transaction --


def test_ingest_document_creates_document_and_chunks_in_one_managed_transaction(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store._ensure_user("alice")  # excluded from the transaction-count assertion below
    client.begin_calls = 0
    client.commit_calls = 0

    document = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="first chunk body\nsecond chunk body\nthird chunk body",
        chunk_chars=20,
    )

    assert document.chunk_count == 3
    assert client.begin_calls == 1, "the whole document+chunk+edge batch is ONE transaction"
    assert client.commit_calls == 1
    assert len(_committed_by_type(client, "Document")) == 1
    assert len(_committed_by_type(client, "Chunk")) == 3
    assert len(_edge_commands(client, "HAS_DOCUMENT")) == 1
    assert len(_edge_commands(client, "HAS_CHUNK")) == 3
    assert len(_edge_commands(client, "NEXT_CHUNK")) == 2


# -- Task 1, Test 2: each Chunk id is a stable_id, embedding inline, no
# vector_id property --


def test_chunk_id_is_stable_id_with_inline_embedding_and_no_vector_id(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="only chunk body",
        chunk_chars=1000,
    )

    chunks = _committed_by_type(client, "Chunk")
    assert len(chunks) == 1
    expected_id = stable_id("chunk", "alice", "doc-1", "1")
    assert chunks[0]["id"] == expected_id
    assert isinstance(chunks[0]["embedding"], list) and chunks[0]["embedding"]
    assert "vector_id" not in chunks[0]
    assert chunks[0]["lexical_tokens"], "expected at least one lexical token bucket"


# -- Task 1, Test 3: re-ingesting the same title+text is deduped by hash --


def test_reingesting_same_title_and_text_dedupes_by_hash(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    first = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="stable content",
        chunk_chars=1000,
    )
    second = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="stable content",
        chunk_chars=1000,
    )

    assert first.document_id == second.document_id
    assert first.chunk_count == second.chunk_count
    assert len(_committed_by_type(client, "Document")) == 1
    document_creates = [
        entry for entry in client.commands if entry[0].startswith("CREATE VERTEX Document")
    ]
    assert len(document_creates) == 1


# 04-09 regression (Rule 1 bug, found live via the ArcadeDB E2E capture):
# reindex_document_text used to call the soft `delete_document()` (an UPDATE
# setting status='deleted') before recreating a Document/Chunk with the SAME
# id -- but a soft-deleted row still occupies its slot in the UNIQUE `id`
# index, so the recreate raised a live DuplicatedKeyException. Fixed to hard
# DELETE the old Document/Chunk rows (confirmed live: ArcadeDB's
# `DELETE FROM <VertexType>` cascades edge removal too) before recreating.
def test_reindex_document_text_hard_deletes_old_rows_before_recreating_same_id(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook v1",
        text="original safety procedure content",
        chunk_chars=1000,
    )

    reindexed = store.reindex_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook v2",
        text="reindexed safety procedure content",
        chunk_chars=1000,
    )

    hard_deletes = [entry[0] for entry in client.commands if entry[0].startswith("DELETE FROM")]
    assert any("DELETE FROM Document" in stmt for stmt in hard_deletes)
    assert any("DELETE FROM Chunk" in stmt for stmt in hard_deletes)
    soft_deletes = [
        entry[0]
        for entry in client.commands
        if entry[0].startswith("UPDATE") and "status = 'deleted'" in entry[0]
    ]
    assert not soft_deletes, "reindex must not use the soft delete_document() path"
    assert reindexed.document_id == "doc-1"
    assert len(_committed_by_type(client, "Document")) == 1

    fetched = store.get_document(user_identifier="alice", document_id="doc-1")
    assert fetched is not None
    assert fetched.title == "Runbook v2"


# -- Task 1, Test 4: _chunk_context(chunk_id) resolves NEXT_CHUNK neighbors by
# chunk_id traversal --


def test_chunk_context_resolves_next_chunk_neighbor_by_chunk_id(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="first chunk body\nsecond chunk body",
        chunk_chars=20,
    )
    first_chunk_id = stable_id("chunk", "alice", "doc-1", "1")
    second_chunk_id = stable_id("chunk", "alice", "doc-1", "2")

    context = store._chunk_context(first_chunk_id)

    assert len(context) == 1
    assert context[0]["chunk_id"] == second_chunk_id
    assert context[0]["locator"] == "chunk=2"
    assert context[0]["text"] == "second chunk body"


# -- Task 1, Test 5: fail-closed on empty user_identifier; tenant-scoped reads --


def test_ingest_with_empty_user_identifier_raises_value_error(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    try:
        store.ingest_document_text(user_identifier="", title="T", text="body")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty user_identifier")


def test_tenant_scoped_get_document_never_returns_other_tenants_document(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    store.ingest_document_text(
        user_identifier="alice", document_id="doc-1", title="Secret", text="alice's secret body"
    )

    assert store.get_document(user_identifier="bob", document_id="doc-1") is None


# -- Task 2, Test 1: vector search returns DocumentHit citations ordered by
# native HNSW score, no vector_id join --


def test_document_search_returns_hits_ordered_by_native_vector_score(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-a",
        title="A",
        text="aaaaaaaaaaaaaaaaaaaa",  # length 20, matches the query's embedding
        chunk_chars=1000,
    )
    store.ingest_document_text(
        user_identifier="alice", document_id="doc-b", title="B", text="bbbbb", chunk_chars=1000
    )

    hits = store.search_documents(user_identifier="alice", query="xxxxxxxxxxxxxxxxxxxx", limit=5)

    assert hits
    assert hits[0].document_id == "doc-a"
    assert hits[0].chunk_id == stable_id("chunk", "alice", "doc-a", "1")
    assert hits[0].text == "aaaaaaaaaaaaaaaaaaaa"
    assert hits[0].score > 0.0


# -- Task 2, Test 2: adaptive over-fetch (D-03) -- the vector channel's k is
# max(limit*4, limit), not the raw limit --


def test_document_search_applies_adaptive_overfetch_multiplier(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice", document_id="doc-a", title="A", text="alpha content chunk"
    )

    store.search_documents(user_identifier="alice", query="alpha", limit=3)

    vector_queries = [
        (stmt, params) for stmt, params in client.queries if "vectorNeighbors" in stmt
    ]
    assert vector_queries
    assert vector_queries[0][1]["k"] == max(3 * 4, 3)


# -- Task 2, Test 3: the full-text channel matches an exact keyword query via
# native Lucene, with the query string escaped first --


def test_document_search_matches_via_native_lucene_full_text(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-a",
        title="A",
        text="the zephyrion incident report",
    )

    raw_query = "what is zephyrion?"
    hits = store.search_documents(user_identifier="alice", query=raw_query, limit=5)

    assert any(hit.document_id == "doc-a" for hit in hits)
    lucene_queries = [(stmt, params) for stmt, params in client.queries if "SEARCH_INDEX" in stmt]
    assert lucene_queries
    assert lucene_queries[0][1]["q"] == escape_lucene_query(raw_query)
    assert "\\?" in str(lucene_queries[0][1]["q"])


# -- Task 2, Test 4: tenant scoping -- a tenant-A query never returns
# tenant-B chunks --


def test_document_search_tenant_scoped_never_returns_other_tenants_chunks(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice", document_id="doc-a", title="A", text="alice private content"
    )

    hits = store.search_documents(user_identifier="bob", query="alice private content", limit=5)

    assert hits == []


# -- source-level acceptance-criteria grep gates --


def test_document_files_contain_no_vector_id_or_helper_calls() -> None:
    for path in (_STORE_DOCUMENTS_PATH, _STORE_CHUNKING_PATH, _STORE_DOCUMENTS_QUERIES_PATH):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("vector_id", "_document_vector_id"):
            assert forbidden not in source, f"{path.name} still references {forbidden!r}"
