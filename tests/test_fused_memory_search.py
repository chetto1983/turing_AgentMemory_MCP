from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.memory_extraction import (
    Classification,
    EntityMention,
    MemoryExtraction,
)
from turing_agentmemory_mcp.models import RetrievalEvidence
from turing_agentmemory_mcp.rerank import RerankResult, Scored
from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory


class NullEmbedder:
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def memory_row(
    memory_id: str,
    *,
    source: str = "locomo",
    session_id: str = "s1",
    tags: tuple[str, ...] = ("benchmark",),
    user_identifier: str = "alice",
) -> dict[str, object]:
    return {
        "m.id": memory_id,
        "m.user_identifier": user_identifier,
        "m.kind": "message",
        "m.content": f"source content {memory_id}",
        "m.session_id": session_id,
        "m.role": "user",
        "m.created_at": "2026-07-10T10:00:00Z",
        "m.updated_at": "2026-07-10T10:00:00Z",
        "m.expires_at": "",
        "m.source": source,
        "m.tags_json": json.dumps(tags),
        "m.metadata_json": "{}",
    }


class FusedStore(TuringAgentMemory):
    def __init__(
        self,
        tmp_path: Path,
        *,
        channels: dict[str, list[RetrievalEvidence]],
        rows: list[dict[str, object]],
        degraded: dict[str, str] | None = None,
        reranker: object | None = None,
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=NullEmbedder(),
            reranker=reranker,  # type: ignore[arg-type]
            fusion_enabled=True,
            fusion_weights={
                "episode_dense": 1.0,
                "fact_dense": 1.0,
                "entity_dense": 1.0,
                "bm25": 1.0,
                "graph": 1.0,
            },
        )
        self.channels = channels
        self.rows = rows
        self.degraded = degraded or {}

    def _collect_retrieval_evidence(
        self,
        *,
        user_identifier: str,
        query: str,
        candidate_limit: int,
    ) -> tuple[dict[str, list[RetrievalEvidence]], dict[str, str]]:
        return self.channels, self.degraded

    def _memory_rows_for_ids(
        self,
        user_identifier: str,
        memory_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        allowed = set(memory_ids)
        return {
            str(row["m.id"]): row
            for row in self.rows
            if row["m.id"] in allowed and row["m.user_identifier"] == user_identifier
        }


def evidence(
    source_memory_id: str,
    evidence_id: str,
    *,
    kind: str,
    raw_score: float,
    hop: int = 0,
) -> RetrievalEvidence:
    return RetrievalEvidence(
        source_memory_id=source_memory_id,
        evidence_id=evidence_id,
        evidence_kind=kind,
        raw_score=raw_score,
        hop=hop,
    )


def test_fused_search_maps_derived_records_to_source_episode_with_explanation(
    tmp_path: Path,
) -> None:
    store = FusedStore(
        tmp_path,
        channels={
            "episode_dense": [
                evidence("m1", "m1", kind="episode", raw_score=0.01),
                evidence("m2", "m2", kind="episode", raw_score=0.99),
            ],
            "fact_dense": [
                evidence("m1", "fact-1", kind="fact", raw_score=9.0),
                evidence("m1", "fact-2", kind="fact", raw_score=8.0),
            ],
            "graph": [
                evidence("m1", "fact-hop", kind="fact", raw_score=0.5, hop=2),
            ],
            "bm25": [
                evidence("m1", "fact-1", kind="fact", raw_score=0.000001),
                evidence("m2", "m2", kind="episode", raw_score=1000.0),
            ],
        },
        rows=[memory_row("m1"), memory_row("m2")],
        degraded={"community": "unavailable"},
    )

    hits = store.search_memory(
        user_identifier="alice",
        query="what does Alice prefer?",
        limit=2,
        explain=True,
    )

    assert [hit.id for hit in hits] == ["m1", "m2"]
    assert set(hits[0].score_details["channels"]) == {
        "bm25",
        "episode_dense",
        "fact_dense",
        "graph",
    }
    assert hits[0].score_details["evidence_ids"] == ["fact-1", "fact-2", "fact-hop", "m1"]
    assert hits[0].score_details["max_hop"] == 2
    assert hits[0].score_details["degraded_channels"] == ["community"]
    assert hits[0].score_details["fusion_score"] == hits[0].score


def test_fused_search_applies_filters_before_channel_rank_assignment(tmp_path: Path) -> None:
    store = FusedStore(
        tmp_path,
        channels={
            "episode_dense": [
                evidence("wrong", "wrong", kind="episode", raw_score=0.9),
                evidence("keep", "keep", kind="episode", raw_score=0.8),
            ]
        },
        rows=[
            memory_row("wrong", source="chat", session_id="s2", tags=("other",)),
            memory_row("keep", source="locomo", session_id="s1", tags=("benchmark",)),
        ],
    )

    hits = store.search_memory(
        user_identifier="alice",
        query="Alice",
        limit=5,
        source="locomo",
        session_id="s1",
        tags=["benchmark"],
        explain=True,
    )

    assert [hit.id for hit in hits] == ["keep"]
    assert hits[0].score_details["channels"]["episode_dense"]["rank"] == 1


def test_fused_search_enforces_tenant_before_fusion(tmp_path: Path) -> None:
    store = FusedStore(
        tmp_path,
        channels={
            "episode_dense": [
                evidence("bob-memory", "bob-memory", kind="episode", raw_score=1.0),
                evidence("alice-memory", "alice-memory", kind="episode", raw_score=0.8),
            ]
        },
        rows=[
            memory_row("bob-memory", user_identifier="bob"),
            memory_row("alice-memory", user_identifier="alice"),
        ],
    )

    hits = store.search_memory(user_identifier="alice", query="memory", limit=5)

    assert [hit.id for hit in hits] == ["alice-memory"]


def test_fused_search_returns_empty_when_all_evidence_sources_are_missing(
    tmp_path: Path,
) -> None:
    store = FusedStore(
        tmp_path,
        channels={
            "fact_dense": [
                evidence("deleted-source", "fact-1", kind="fact", raw_score=0.9)
            ]
        },
        rows=[],
    )

    assert store.search_memory(user_identifier="alice", query="memory", limit=5) == []


class Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.rows


class QueryExtractor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def extract_many(self, texts: list[str]) -> tuple[MemoryExtraction, ...]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("query extraction failed with private text")
        entity = EntityMention("Alice", "person", 0.9, 0, 5)
        return (
            MemoryExtraction(
                entities=(entity,),
                relations=(),
                memory_kind=Classification("semantic_fact", 0.8),
                model="test-gliner2",
                device="cpu",
                schema_version="memory-v1",
            ),
        )


class CollectorStore(TuringAgentMemory):
    def __init__(
        self,
        tmp_path: Path,
        *,
        extractor: QueryExtractor,
        fail_operation: str = "",
    ) -> None:
        sparse = SparseIndex(tmp_path / "collector.sqlite3")
        sparse.initialize()
        alice_entity_id = stable_id("ent", "alice", "person", "alice")
        sparse.upsert_many(
            [
                SparseDocument("alice:episode:m3", "alice", "m3", "episode", "Alice trip"),
                SparseDocument("alice:fact:f3", "alice", "f3", "fact", "Alice prefers tea"),
                SparseDocument(
                    f"alice:entity:{alice_entity_id}",
                    "alice",
                    alice_entity_id,
                    "entity",
                    "Alice (person)",
                ),
            ]
        )
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=NullEmbedder(),
            reranker=None,
            memory_extractor=extractor,
            sparse_index=sparse,
            fusion_enabled=True,
        )
        self.fail_operation = fail_operation
        self.alice_entity_id = alice_entity_id

    def _query(self, query: str, *, operation: str) -> Rows:
        if operation == self.fail_operation:
            raise RuntimeError("channel failed with private query")
        rows = {
            "memory.vector_search.fused": [
                {"m.id": "m1", "score": 0.8},
            ],
            "fact.vector_search": [
                {"f.id": "f1", "f.source_memory_id": "m1", "score": 0.9},
            ],
            "entity.vector_search": [
                {"e.id": self.alice_entity_id, "score": 0.7},
            ],
            "fact.source_lookup": [
                {"f.id": "f3", "f.source_memory_id": "m3", "f.confidence": 0.75},
            ],
            "graph.entity_direct_subject": [
                {
                    "m.id": "m2",
                    "f.id": "f2",
                    "f.confidence": 0.85,
                    "e.id": self.alice_entity_id,
                }
            ],
            "graph.entity_direct_object": [],
            "graph.entity_two_hop_subject": [],
            "graph.entity_two_hop_object": [],
        }.get(operation, [])
        return Rows(rows)


def test_collectors_build_independent_dense_sparse_and_graph_channels(
    tmp_path: Path,
) -> None:
    extractor = QueryExtractor()
    store = CollectorStore(tmp_path, extractor=extractor)

    channels, degraded = store._collect_retrieval_evidence(
        user_identifier="alice",
        query="Alice",
        candidate_limit=20,
    )

    assert degraded == {}
    assert [(item.source_memory_id, item.evidence_id) for item in channels["episode_dense"]] == [
        ("m1", "m1")
    ]
    assert [(item.source_memory_id, item.evidence_id) for item in channels["fact_dense"]] == [
        ("m1", "f1")
    ]
    assert {item.source_memory_id for item in channels["entity_dense"]} == {"m2"}
    assert {item.source_memory_id for item in channels["graph"]} == {"m2"}
    assert {item.source_memory_id for item in channels["bm25"]} == {"m2", "m3"}
    assert extractor.calls == [["Alice"]]


def test_collector_failure_is_reported_without_losing_other_channels(tmp_path: Path) -> None:
    store = CollectorStore(
        tmp_path,
        extractor=QueryExtractor(fail=True),
        fail_operation="fact.vector_search",
    )

    channels, degraded = store._collect_retrieval_evidence(
        user_identifier="alice",
        query="Alice",
        candidate_limit=20,
    )

    assert "episode_dense" in channels
    assert "bm25" in channels
    assert degraded == {
        "fact_dense": "RuntimeError",
        "graph": "RuntimeError",
    }
    assert "private" not in json.dumps(degraded)


class StatusReranker:
    def __init__(self, status: str) -> None:
        self.status = status
        self.documents: list[str] = []

    def rerank_with_status(self, query: str, documents: list[str]) -> RerankResult:
        self.documents = list(documents)
        scores = [Scored(index=1, score=0.95), Scored(index=0, score=0.8)]
        return RerankResult(scores=scores, status=self.status, model="test-qwen")


def test_fused_rerank_applies_provenance_context_and_reports_status(tmp_path: Path) -> None:
    reranker = StatusReranker("applied")
    store = FusedStore(
        tmp_path,
        channels={
            "episode_dense": [
                evidence("m1", "m1", kind="episode", raw_score=0.9),
                evidence("m2", "m2", kind="episode", raw_score=0.8),
            ]
        },
        rows=[memory_row("m1"), memory_row("m2")],
        reranker=reranker,
    )

    hits = store.search_memory(
        user_identifier="alice",
        query="Alice",
        limit=2,
        explain=True,
    )

    assert [hit.id for hit in hits] == ["m2", "m1"]
    assert "memory_id: m1" in reranker.documents[0]
    assert "source: locomo" in reranker.documents[0]
    assert "created_at: 2026-07-10T10:00:00Z" in reranker.documents[0]
    assert hits[0].score_details["rerank_status"] == "applied"
    assert hits[0].score_details["rerank_model"] == "test-qwen"


def test_fused_rerank_fallback_preserves_rrf_order_and_is_visible(tmp_path: Path) -> None:
    store = FusedStore(
        tmp_path,
        channels={
            "episode_dense": [
                evidence("m1", "m1", kind="episode", raw_score=0.9),
                evidence("m2", "m2", kind="episode", raw_score=0.8),
            ]
        },
        rows=[memory_row("m1"), memory_row("m2")],
        reranker=StatusReranker("provider_error"),
    )

    hits = store.search_memory(user_identifier="alice", query="Alice", limit=2)

    assert [hit.id for hit in hits] == ["m1", "m2"]
    assert hits[0].score_details["rerank_status"] == "provider_error"
