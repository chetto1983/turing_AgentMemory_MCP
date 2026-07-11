from __future__ import annotations

from pathlib import Path

import yaml


def test_product_service_enables_the_fused_temporal_pipeline() -> None:
    compose = yaml.safe_load(
        Path(__file__).resolve().parents[1].joinpath("compose.yaml").read_text(encoding="utf-8")
    )
    environment = compose["services"]["turing-agentmemory-mcp"]["environment"]

    assert "AGENTMEMORY_FUSION_ENABLED=1" in environment
    assert "AGENTMEMORY_SPARSE_PATH=/turing/data/agent-memory-fts.sqlite3" in environment
    assert "AGENTMEMORY_COMMUNITY_REBUILD_ON_BATCH=1" in environment
    assert "AGENTMEMORY_LEIDEN_SEED=42" in environment
    assert "AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE=100" in environment
    assert "GLINER_MEMORY_SCHEMA=memory-v1" in environment
    assert (
        "TURINGDB_MEMORY_INDEX=${TURINGDB_MEMORY_INDEX:-agent_memory_episode_vectors_768}"
        in environment
    )
    assert (
        "TURINGDB_DOCUMENT_INDEX=${TURINGDB_DOCUMENT_INDEX:-agent_memory_document_vectors_768}"
        in environment
    )
    assert (
        "TURINGDB_ENTITY_INDEX=${TURINGDB_ENTITY_INDEX:-agent_memory_entity_vectors_768}"
        in environment
    )
    assert (
        "TURINGDB_FACT_INDEX=${TURINGDB_FACT_INDEX:-agent_memory_fact_vectors_768}"
        in environment
    )
    assert (
        "TURINGDB_COMMUNITY_INDEX=${TURINGDB_COMMUNITY_INDEX:-agent_memory_community_vectors_768}"
        in environment
    )


def test_product_healthcheck_validates_runtime_status_not_only_the_socket() -> None:
    compose = yaml.safe_load(
        Path(__file__).resolve().parents[1].joinpath("compose.yaml").read_text(encoding="utf-8")
    )
    health = compose["services"]["turing-agentmemory-mcp"]["healthcheck"]["test"][1]

    assert "/health" in health
    assert "runtime" in health
