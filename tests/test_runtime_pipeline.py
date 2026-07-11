from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import httpx
import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.community_detection import NativeLeidenDetector
from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    HTTPMemoryExtractor,
)
from turing_agentmemory_mcp.sparse_index import SparseIndex


class FakeClient:
    def __init__(self, *, type: str, host: str, token: str | None) -> None:
        self.type = type
        self.host = host
        self.token = token


class FakeStore:
    def __init__(self, client: object, **kwargs: object) -> None:
        self.client = client
        self.kwargs = kwargs
        self.bootstrapped = False

    def bootstrap(self) -> None:
        self.bootstrapped = True


def test_store_from_env_wires_the_fused_pipeline_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from turing_agentmemory_mcp import server

    sparse_path = tmp_path / "fts" / "memory.sqlite3"
    monkeypatch.setenv("TURINGDB_HOME", str(tmp_path))
    monkeypatch.setenv("AGENTMEMORY_FUSION_ENABLED", "true")
    monkeypatch.setenv("AGENTMEMORY_SPARSE_PATH", str(sparse_path))
    monkeypatch.setenv("AGENTMEMORY_FUSION_WEIGHTS", '{"episode_dense":1,"bm25":2,"community":0.5}')
    monkeypatch.setenv("GLINER_BASE_URL", "http://gliner.internal:8080/")
    monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-base-v1")
    monkeypatch.setenv("GLINER_THRESHOLD", "0.42")
    monkeypatch.setenv("GLINER_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("AGENTMEMORY_LEIDEN_SEED", "17")
    monkeypatch.setenv("AGENTMEMORY_LEIDEN_RESOLUTION", "1.25")
    monkeypatch.setenv("AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE", "64")
    monkeypatch.setenv("AGENTMEMORY_COMMUNITY_REBUILD_ON_BATCH", "1")
    monkeypatch.setattr(server, "TuringDB", FakeClient)
    monkeypatch.setattr(server, "TuringAgentMemory", FakeStore)

    store = server.store_from_env()

    assert store.bootstrapped is True
    assert store.kwargs["fusion_enabled"] is True
    assert store.kwargs["fusion_weights"] == {
        "bm25": 2.0,
        "community": 0.5,
        "episode_dense": 1.0,
    }
    assert isinstance(store.kwargs["sparse_index"], SparseIndex)
    assert store.kwargs["sparse_index"].path == sparse_path.resolve()
    extractor = store.kwargs["memory_extractor"]
    assert isinstance(extractor, HTTPMemoryExtractor)
    assert extractor.base_url == "http://gliner.internal:8080"
    assert extractor.model_name == "fastino/gliner2-base-v1"
    assert extractor.threshold == 0.42
    assert extractor.timeout_s == 45.0
    assert isinstance(store.kwargs["entity_processor"], NoopEntityProcessor)
    detector = store.kwargs["community_detector"]
    assert isinstance(detector, NativeLeidenDetector)
    assert detector.seed == 17
    assert detector.resolution == 1.25
    assert detector.max_cluster_size == 64
    assert store.kwargs["community_rebuild_on_batch"] is True
    assert store.kwargs["memory_index"] == "agent_memory_episode_vectors_768"
    assert store.kwargs["document_index"] == "agent_memory_document_vectors_768"
    assert store.kwargs["entity_index"] == "agent_memory_entity_vectors_768"
    assert store.kwargs["fact_index"] == "agent_memory_fact_vectors_768"
    assert store.kwargs["community_index"] == "agent_memory_community_vectors_768"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENTMEMORY_FUSION_ENABLED", "sometimes"),
        ("AGENTMEMORY_LEIDEN_SEED", "-1"),
        ("AGENTMEMORY_LEIDEN_RESOLUTION", "nan"),
        ("AGENTMEMORY_FUSION_WEIGHTS", "[]"),
    ],
)
def test_store_from_env_rejects_invalid_fused_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    from turing_agentmemory_mcp import server

    monkeypatch.setenv("TURINGDB_HOME", str(tmp_path))
    monkeypatch.setenv("AGENTMEMORY_FUSION_ENABLED", "1")
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(server, "TuringDB", FakeClient)
    monkeypatch.setattr(server, "TuringAgentMemory", FakeStore)

    with pytest.raises(ValueError):
        server.store_from_env()


def test_runtime_status_exposes_stage_identity_without_content(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.observability import RuntimeSignals

    signals = RuntimeSignals()
    signals.configure_stage(
        "extraction",
        ready=True,
        identity={
            "model": "fastino/gliner2-base-v1",
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        },
    )
    signals.record_degraded_channels(["community", "bm25"])
    signals.record_degraded_channels(["community"])
    signals.record_projection("community", success=True, item_count=3)

    status = signals.snapshot()

    assert status["stages"]["extraction"] == {
        "ready": True,
        "identity": {
            "model": "fastino/gliner2-base-v1",
            "schema_version": "memory-v1",
        },
    }
    assert status["degraded_channel_counts"] == {"bm25": 1, "community": 2}
    assert status["projections"]["community"]["status"] == "ready"
    assert status["projections"]["community"]["item_count"] == 3
    assert status["projections"]["community"]["updated_at"]
    assert "content" not in repr(status).lower()


def test_http_health_route_returns_runtime_readiness() -> None:
    from turing_agentmemory_mcp.server import create_mcp_app

    class HealthyMemory:
        def runtime_status(self) -> dict[str, object]:
            return {
                "stages": {
                    "graph": {"ready": True},
                    "embedding": {"ready": True, "identity": {"model": "granite"}},
                }
            }

    app = create_mcp_app(HealthyMemory())  # type: ignore[arg-type]

    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app.http_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["runtime"]["stages"]["embedding"]["identity"]["model"] == "granite"


def test_vector_bootstrap_rejects_an_existing_dimension_mismatch() -> None:
    from turing_agentmemory_mcp.store import TuringAgentMemory

    class Rows:
        def to_dict(self, orient: str) -> list[dict[str, object]]:
            assert orient == "records"
            return [{"name": "entity_vectors", "dimension": 3}]

    class IndexStore(TuringAgentMemory):
        def __init__(self) -> None:
            self.dimensions = 768

        def _query(self, query: str, *, operation: str) -> Rows:
            if query.startswith("CREATE VECTOR INDEX"):
                raise RuntimeError("already exists")
            assert query == "SHOW VECTOR INDEXES"
            return Rows()

    with pytest.raises(RuntimeError, match="entity_vectors.*expected 768.*found 3"):
        IndexStore()._ensure_vector_index("entity_vectors")
