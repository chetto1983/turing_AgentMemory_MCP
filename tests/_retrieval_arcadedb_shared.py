"""Shared ArcadeDB retrieval-test fixtures (not collected as tests, mirrors
`_batch_memory_shared.py`'s naming convention).

`_FakeArcadeDBClient` extends the session-aware in-memory stand-in convention
established by `tests/test_store_arcadedb_memory.py`/`tests/test_store_arcadedb_documents.py`
to also interpret 04-07's own statement shapes: native `vectorNeighbors`
(dense HNSW), native `vector.sparseNeighbors` (BOTH-channels lexical, first
channel), native `SEARCH_INDEX` (BOTH-channels lexical, second channel), the
D-05 SQL `MATCH {type: ..., as: ..., where: (...)}.out(...)` object-notation
graph surface, and bound `id IN :xxx_ids` array lookups -- no live ArcadeDB
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
from turing_agentmemory_mcp.memory_extraction import (
    Classification,
    EntityMention,
    MemoryExtraction,
    RelationMention,
)
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory

_CREATE_TYPE_RE = re.compile(r"CREATE VERTEX (\w+)", re.IGNORECASE)
_CREATE_EDGE_RE = re.compile(r"CREATE EDGE (\w+)", re.IGNORECASE)
_DENSE_TYPE_RE = re.compile(r'vectorNeighbors\("(\w+)\[', re.IGNORECASE)
_SPARSE_TYPE_RE = re.compile(r'vector\.sparseNeighbors\("(\w+)\[', re.IGNORECASE)
_LUCENE_TYPE_RE = re.compile(r'SEARCH_INDEX\("(\w+)\[', re.IGNORECASE)
_SELECT_FROM_TYPE_RE = re.compile(r"FROM (\w+)\b", re.IGNORECASE)
_OUT_EDGE_RE = re.compile(r"\.out\('(\w+)'\)")


def _euclidean(left: list[float], right: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(left, right, strict=False)) ** 0.5


def _dot(a_idx: list[int], a_val: list[float], b_idx: list[int], b_val: list[float]) -> float:
    b_map = dict(zip(b_idx, b_val, strict=False))
    return sum(value * b_map.get(idx, 0.0) for idx, value in zip(a_idx, a_val, strict=False))


def _edge_endpoints(params: dict[str, object]) -> tuple[str, str]:
    # Mirrors store_memory_queries.py's projection_edge_statements (source_id/
    # target_id) and memory_edge_statement (identifier/id) bound-param
    # conventions -- whichever this statement used.
    if "source_id" in params and "target_id" in params:
        return str(params["source_id"]), str(params["target_id"])
    if "identifier" in params and "id" in params:
        return str(params["identifier"]), str(params["id"])
    return "", ""


class _FakeArcadeDBClient:
    """Session-aware in-memory stand-in interpreting this plan's exact
    statement shapes -- not a general SQL engine. Evidence collectors never
    pass a `session_id` to `query()` (store_core.py's `_query` seam), so only
    globally committed rows/edges are ever visible to a read.
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

    # -- transaction control --

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
        return self._select(statement, params)

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
            return self._select(statement, params)
        if upper.startswith("CREATE VERTEX"):
            match = _CREATE_TYPE_RE.match(statement)
            row = dict(params or {})
            row["_type"] = match.group(1) if match else ""
            bucket = session_id or "__no_session__"
            self._session_rows.setdefault(bucket, []).append(row)
            return []
        if upper.startswith("CREATE EDGE TYPE"):
            return []
        if upper.startswith("CREATE EDGE"):
            match = _CREATE_EDGE_RE.match(statement)
            edge_type = match.group(1) if match else ""
            source_id, target_id = _edge_endpoints(params or {})
            bucket = session_id or "__no_session__"
            self._session_edges.setdefault(bucket, []).append((edge_type, source_id, target_id))
            return []
        if upper.startswith("UPDATE"):
            return []
        return []

    # -- read dispatch --

    def _select(self, statement: str, params: dict[str, object] | None) -> list[dict[str, object]]:
        visible = list(self._committed)
        upper = statement.upper()
        if "VECTORNEIGHBORS" in upper:
            return self._dense(statement, params, visible)
        if "SPARSENEIGHBORS" in upper:
            return self._sparse(statement, params, visible)
        if "SEARCH_INDEX" in upper:
            return self._lucene(statement, params, visible)
        if statement.strip().upper().startswith("MATCH"):
            return self._match(statement, params, visible)
        match = _SELECT_FROM_TYPE_RE.search(statement)
        record_type = match.group(1) if match else None
        rows = [row for row in visible if not record_type or row.get("_type") == record_type]
        return self._filter_generic(rows, params)

    @staticmethod
    def _filter_generic(
        rows: list[dict[str, object]], params: dict[str, object] | None
    ) -> list[dict[str, object]]:
        if not params:
            return rows
        results = []
        for row in rows:
            ok = True
            for key, value in params.items():
                if isinstance(value, list):
                    if row.get("id") not in value:
                        ok = False
                        break
                elif row.get(key) != value:
                    ok = False
                    break
            if ok:
                results.append(row)
        return results

    def _dense(
        self,
        statement: str,
        params: dict[str, object] | None,
        visible: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        match = _DENSE_TYPE_RE.search(statement)
        type_name = match.group(1) if match else ""
        params = params or {}
        query_vec = list(params.get("vec") or [])
        k = int(params.get("k") or 0)
        filter_params = {key: value for key, value in params.items() if key not in ("vec", "k")}
        candidates = [row for row in visible if row.get("_type") == type_name]
        scored = sorted(
            ((_euclidean(query_vec, list(row.get("embedding") or [])), row) for row in candidates),
            key=lambda pair: pair[0],
        )
        # D-03: the filter is applied AFTER the top-k slice -- post-filter
        # k-underfill, matching the live-confirmed spike behavior.
        results: list[dict[str, object]] = []
        for distance, row in scored[:k]:
            if not all(row.get(key) == value for key, value in filter_params.items()):
                continue
            enriched = dict(row)
            enriched["distance"] = distance
            results.append(enriched)
        return results

    def _sparse(
        self,
        statement: str,
        params: dict[str, object] | None,
        visible: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        match = _SPARSE_TYPE_RE.search(statement)
        type_name = match.group(1) if match else ""
        params = params or {}
        qi = list(params.get("qi") or [])
        qv = list(params.get("qv") or [])
        k = int(params.get("k") or 0)
        filter_params = {
            key: value for key, value in params.items() if key not in ("qi", "qv", "k")
        }
        candidates = [row for row in visible if row.get("_type") == type_name]
        scored = sorted(
            (
                (
                    _dot(
                        qi,
                        qv,
                        list(row.get("lexical_tokens") or []),
                        list(row.get("lexical_weights") or []),
                    ),
                    row,
                )
                for row in candidates
            ),
            key=lambda pair: -pair[0],
        )
        results: list[dict[str, object]] = []
        for score, row in scored[:k]:
            if score <= 0.0:
                continue
            if not all(row.get(key) == value for key, value in filter_params.items()):
                continue
            enriched = dict(row)
            enriched["score"] = score
            results.append(enriched)
        return results

    def _lucene(
        self,
        statement: str,
        params: dict[str, object] | None,
        visible: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        match = _LUCENE_TYPE_RE.search(statement)
        type_name = match.group(1) if match else ""
        params = params or {}
        query_text = str(params.get("q") or "").lower()
        tokens = [token for token in re.split(r"\W+", query_text) if token]
        filter_params = {key: value for key, value in params.items() if key != "q"}
        results: list[dict[str, object]] = []
        for row in visible:
            if row.get("_type") != type_name:
                continue
            if not all(row.get(key) == value for key, value in filter_params.items()):
                continue
            text = str(row.get("content") or "").lower()
            overlap = sum(1 for token in tokens if token in text)
            if overlap:
                enriched = dict(row)
                enriched["score"] = float(overlap)
                results.append(enriched)
        results.sort(key=lambda row: -float(row["score"]))
        return results

    def _match(
        self,
        statement: str,
        params: dict[str, object] | None,
        visible: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        params = params or {}
        entity_ids = list(params.get("entity_ids") or [])
        user_identifier = params.get("user_identifier")
        hop2 = ".both()" in statement
        out_edges = _OUT_EDGE_RE.findall(statement)
        edge_kind = out_edges[0] if out_edges else ""
        entities = {
            str(row["id"]): row for row in visible if row.get("_type") == "Entity" and row.get("id")
        }
        facts = {
            str(row["id"]): row for row in visible if row.get("_type") == "Fact" and row.get("id")
        }
        memories = {
            str(row["id"]): row for row in visible if row.get("_type") == "Memory" and row.get("id")
        }

        def targets(kind: str, source_id: str) -> list[str]:
            return [
                target for k, source, target in self._edges if k == kind and source == source_id
            ]

        def any_neighbors(source_id: str) -> list[str]:
            out = [target for _k, source, target in self._edges if source == source_id]
            inn = [source for _k, source, target in self._edges if target == source_id]
            return out + inn

        # `status = 'active'` is a literal in the real SQL (not a bound
        # param), so this fake -- like its sibling fakes in
        # test_store_arcadedb_memory.py/test_store_arcadedb_documents.py --
        # doesn't model literal `SET`/`WHERE` clauses; a row with no
        # explicit "status" key defaults to active.
        def is_active(row: dict[str, object]) -> bool:
            return row.get("status", "active") == "active"

        rows: list[dict[str, object]] = []
        starts = [
            entity_id
            for entity_id in entity_ids
            if entity_id in entities
            and entities[entity_id].get("user_identifier") == user_identifier
            and is_active(entities[entity_id])
        ]
        for entity_id in starts:
            hop_starts = [entity_id]
            if hop2:
                hop_starts = [
                    neighbor
                    for neighbor in any_neighbors(entity_id)
                    if neighbor in entities and is_active(entities[neighbor])
                ]
            for n_id in hop_starts:
                for fact_id in targets(edge_kind, n_id):
                    fact = facts.get(fact_id)
                    if fact is None or not is_active(fact):
                        continue
                    for memory_id in targets("SUPPORTED_BY", fact_id):
                        memory = memories.get(memory_id)
                        if memory is None or not is_active(memory):
                            continue
                        rows.append(
                            {
                                "memory_id": memory_id,
                                "fact_id": fact_id,
                                "confidence": fact.get("confidence", 1.0),
                                "entity_id": entity_id,
                            }
                        )
        return rows


class _ScriptedExtractor:
    """Deterministic memory extractor: `script[content]` -> (subject_text,
    subject_type, predicate, object_text, object_type). Produces the SAME
    downstream `EntityProjection`/`FactProjection`/`EdgeProjection` shape
    `temporal_graph.plan_temporal_projection` builds for a real GLiNER2
    extraction (SUBJECT_OF/OBJECT_OF/SUPPORTED_BY + a dynamic subject->object
    predicate edge) -- letting these tests build a real 2-hop entity graph
    through the actual write path (04-05) rather than hand-faking rows.
    """

    def __init__(self, script: dict[str, tuple[str, str, str, str, str]]) -> None:
        self.script = script

    def extract_many(self, texts: list[str]) -> tuple[MemoryExtraction, ...]:
        results = []
        for text in texts:
            subject_text, subject_type, predicate, object_text, object_type = self.script[text]
            s_start = text.index(subject_text)
            o_start = text.index(object_text)
            subject = EntityMention(
                subject_text, subject_type, 0.9, s_start, s_start + len(subject_text)
            )
            obj = EntityMention(object_text, object_type, 0.9, o_start, o_start + len(object_text))
            results.append(
                MemoryExtraction(
                    entities=(subject, obj),
                    relations=(RelationMention(predicate, subject, obj, 0.9),),
                    memory_kind=Classification("semantic_fact", 0.9),
                    model="test-gliner2",
                    device="cpu",
                    schema_version="memory-v1",
                )
            )
        return tuple(results)


def make_retrieval_store(
    client: _FakeArcadeDBClient,
    tmp_path: Path,
    *,
    memory_extractor: Any | None = None,
    reranker: Any | None = None,
) -> TuringAgentMemory:
    return TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingBatchEmbedder(),
        reranker=reranker,
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        memory_extractor=memory_extractor,
        observer=InMemorySpanRecorder(),
        fusion_enabled=True,
    )
