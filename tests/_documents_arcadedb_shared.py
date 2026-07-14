"""Shared ArcadeDB document-test fixtures (not collected as tests, mirrors
`_retrieval_arcadedb_shared.py`'s naming convention).

Split out of `test_store_arcadedb_documents.py` (HI-01, 600-LOC cap) so the
fake client + its small helpers live in one place: `_FakeArcadeDBClient` is a
session-aware in-memory stand-in interpreting this plan's exact statement
shapes (`CREATE VERTEX <Type> SET ...`, `CREATE EDGE <Type> FROM (SELECT ...)
TO (SELECT ...)`, `SELECT ... FROM (SELECT expand(vectorNeighbors(...)))`,
`SELECT ... FROM <Type> WHERE SEARCH_INDEX(...)`, `SELECT ... FROM (SELECT
expand(out('NEXT_CHUNK')) ...)`) well enough to round-trip a real
`store_documents.py`/`store_chunking.py` call -- not a general SQL engine, no
live ArcadeDB container is required.
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
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory

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
        # HI-01 fix: both the inner (source chunk) and outer (target chunk)
        # WHERE clauses bind user_identifier -- mirror both here so a
        # cross-tenant NEXT_CHUNK edge planted directly is a regression this
        # fake can actually catch.
        source_id = str((params or {}).get("id") or "")
        user_identifier = (params or {}).get("user_identifier")
        bucket = session_id or "__no_session__"
        rows = self._committed + self._session_rows.get(bucket, [])
        chunks_by_id = {row.get("id"): row for row in rows if row.get("_type") == "Chunk"}
        source_row = chunks_by_id.get(source_id)
        if source_row is None or source_row.get("user_identifier") != user_identifier:
            return []
        edges = self._edges + self._session_edges.get(bucket, [])
        target_ids = {
            target for kind, source, target in edges if kind == "NEXT_CHUNK" and source == source_id
        }
        return [
            {
                "chunk_id": row.get("id", ""),
                "locator": row.get("locator", ""),
                "text": row.get("text", ""),
            }
            for row in rows
            if row.get("_type") == "Chunk"
            and row.get("id") in target_ids
            and row.get("user_identifier") == user_identifier
        ]


def make_document_store(
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


def committed_by_type(client: _FakeArcadeDBClient, record_type: str) -> list[dict[str, object]]:
    return [row for row in client._committed if row.get("_type") == record_type]


def edge_commands(
    client: _FakeArcadeDBClient, edge_type: str
) -> list[tuple[str, dict, str | None]]:
    prefix = f"CREATE EDGE {edge_type}"
    return [entry for entry in client.commands if entry[0].startswith(prefix)]
