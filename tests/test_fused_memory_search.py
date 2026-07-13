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
from turing_agentmemory_mcp.store import TuringAgentMemory


class NullEmbedder:
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class ReadyOnlyClient:
    """Minimal ArcadeDB-shaped stub for tests that only exercise
    `runtime_status()`'s readiness probe (04-04's seam), never issuing an
    actual query/command."""

    def is_ready(self) -> bool:
        return True


def test_default_fusion_weights_prioritize_direct_evidence(tmp_path: Path) -> None:
    store = TuringAgentMemory(
        client=ReadyOnlyClient(),  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=NullEmbedder(),
        fusion_enabled=True,
    )

    assert store.fusion_weights == {
        "episode_dense": 1.5,
        "fact_dense": 0.75,
        "entity_dense": 0.5,
        "bm25": 2.0,
        "graph": 0.5,
        "community": 0.25,
    }
    identity = store.runtime_status()["stages"]["fusion"]["identity"]
    assert identity["bm25_weight"] == 2.0
    assert identity["episode_dense_weight"] == 1.5
    assert identity["community_weight"] == 0.25


def memory_row(
    memory_id: str,
    *,
    source: str = "locomo",
    session_id: str = "s1",
    tags: tuple[str, ...] = ("benchmark",),
    user_identifier: str = "alice",
) -> dict[str, object]:
    return {
        "id": memory_id,
        "user_identifier": user_identifier,
        "kind": "message",
        "content": f"source content {memory_id}",
        "session_id": session_id,
        "role": "user",
        "created_at": "2026-07-10T10:00:00Z",
        "updated_at": "2026-07-10T10:00:00Z",
        "expires_at": "",
        "source": source,
        "tags_json": json.dumps(tags),
        "metadata_json": "{}",
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
            client=ReadyOnlyClient(),  # type: ignore[arg-type]
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
            str(row["id"]): row
            for row in self.rows
            if row["id"] in allowed and row["user_identifier"] == user_identifier
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
        channels={"fact_dense": [evidence("deleted-source", "fact-1", kind="fact", raw_score=0.9)]},
        rows=[],
    )

    assert store.search_memory(user_identifier="alice", query="memory", limit=5) == []


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
    """ArcadeDB-shaped fixture (04-07): canned per-`operation` rows using the
    ported bare-key convention (`"id"`, `"distance"`/`"score"`), replacing the
    retired SQLite `SparseIndex` fixture -- the BOTH-channels lexical decision
    reads native `vector.sparseNeighbors`/`SEARCH_INDEX` (here: canned
    `*.lexical_search.sparse`/`*.lexical_search.lucene` rows), never the FTS5
    outbox (ARC-06). `alice_entity_id`'s single Lucene episode hit on `m3`
    plus its entity-lexical hit (expanded via the SAME
    `graph.entity_direct_subject` traversal rows the `graph` channel test
    also exercises) reproduce the old fixture's `{"m2", "m3"}` bm25 outcome.
    """

    def __init__(
        self,
        tmp_path: Path,
        *,
        extractor: QueryExtractor,
        fail_operation: str = "",
    ) -> None:
        alice_entity_id = stable_id("ent", "alice", "person", "alice")
        super().__init__(
            client=ReadyOnlyClient(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=NullEmbedder(),
            reranker=None,
            memory_extractor=extractor,
            fusion_enabled=True,
        )
        self.fail_operation = fail_operation
        self.alice_entity_id = alice_entity_id

    def _query(
        self, query: str, *, operation: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        if operation == self.fail_operation:
            raise RuntimeError("channel failed with private query")
        return {
            "memory.vector_search.fused": [
                {"id": "m-low", "distance": 0.9},
                {"id": "m1", "distance": 0.2},
            ],
            "fact.vector_search": [
                {"id": "f1", "source_memory_id": "m1", "distance": 0.1},
            ],
            "entity.vector_search": [
                {"id": self.alice_entity_id, "distance": 0.3},
            ],
            "community.vector_search": [
                {
                    "id": "community-1",
                    "source_memory_ids_json": '["m1", "m2"]',
                    "distance": 0.35,
                }
            ],
            "memory.lexical_search.lucene": [{"id": "m3", "score": 5.0}],
            "entity.lexical_search.lucene": [{"id": self.alice_entity_id, "score": 3.0}],
            "graph.entity_direct_subject": [
                {
                    "memory_id": "m2",
                    "fact_id": "f2",
                    "confidence": 0.85,
                    "entity_id": self.alice_entity_id,
                }
            ],
            "graph.entity_direct_object": [],
            "graph.entity_two_hop_subject": [],
            "graph.entity_two_hop_object": [],
        }.get(operation, [])


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
        ("m1", "m1"),
        ("m-low", "m-low"),
    ]
    assert [(item.source_memory_id, item.evidence_id) for item in channels["fact_dense"]] == [
        ("m1", "f1")
    ]
    assert {item.source_memory_id for item in channels["entity_dense"]} == {"m2"}
    assert {item.source_memory_id for item in channels["graph"]} == {"m2"}
    assert {item.source_memory_id for item in channels["community"]} == {"m1", "m2"}
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


def test_fused_rerank_bounds_gpu_candidates_and_preserves_tail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RERANK_CANDIDATE_LIMIT", "2")
    reranker = StatusReranker("applied")
    store = FusedStore(
        tmp_path,
        channels={
            "episode_dense": [
                evidence("m1", "m1", kind="episode", raw_score=0.9),
                evidence("m2", "m2", kind="episode", raw_score=0.8),
                evidence("m3", "m3", kind="episode", raw_score=0.7),
            ]
        },
        rows=[memory_row("m1"), memory_row("m2"), memory_row("m3")],
        reranker=reranker,
    )

    hits = store.search_memory(user_identifier="alice", query="Alice", limit=3)

    assert len(reranker.documents) == 2
    assert [hit.id for hit in hits] == ["m2", "m1", "m3"]
    assert hits[2].score_details["rerank_status"] == "candidate_limit"
