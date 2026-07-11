from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "backboard_locomo_runner",
    ROOT / "scripts" / "eval_backboard_locomo_mcp.py",
)
assert SPEC is not None
assert SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_summarize_entity_extraction_reports_models_and_entity_counts() -> None:
    rows = [
        {
            "metadata": {
                "entity_extraction": {
                    "model": "lion-ai/gliner2-base-v1-onnx",
                    "entity_count": 2,
                }
            }
        },
        {"metadata": {}},
    ]

    assert runner.summarize_entity_extraction(rows) == {
        "annotated_memories": 1,
        "entities": 2,
        "models": ["lion-ai/gliner2-base-v1-onnx"],
    }


@pytest.mark.parametrize(
    "summary",
    [
        {"annotated_memories": 0, "entities": 0, "models": []},
        {"annotated_memories": 1, "entities": 2, "models": ["wrong-model"]},
    ],
)
def test_require_entity_model_rejects_missing_or_different_model(summary: dict[str, object]) -> None:
    with pytest.raises(RuntimeError, match="lion-ai/gliner2-base-v1-onnx"):
        runner.require_entity_model(summary, "lion-ai/gliner2-base-v1-onnx")


def test_comparable_cutoffs_are_fixed_at_20_50_and_200() -> None:
    assert runner.COMPARABLE_CUTOFFS == (20, 50, 200)
    assert runner.MAX_INGEST_BATCH == 1024
    assert runner.retrieval_cutoffs(200) == [1, 3, 5, 10, 20, 50, 200]


def test_ingest_batch_validation_commits_a_full_conversation_once() -> None:
    assert runner.validate_batch_size(1024) == 1024
    with pytest.raises(ValueError, match="between 1 and 1024"):
        runner.validate_batch_size(1025)


def test_ingest_defers_communities_then_rebuilds_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(_client: object, name: str, arguments: dict[str, object]) -> object:
        calls.append((name, arguments))
        if name == "memory_store_messages":
            return [{"id": str(row["memory_id"]), "metadata": {}} for row in arguments["messages"]]
        return {"community_count": 2}

    monkeypatch.setattr(runner, "call_tool", fake_call)
    messages = [
        {"memory_id": f"m{index}", "session_id": "s1", "role": "user", "content": "x"}
        for index in range(3)
    ]

    info, _rows = asyncio.run(
        runner.ingest_conversation(
            object(),
            user_identifier="alice",
            messages=messages,
            batch_size=2,
        )
    )

    assert [name for name, _ in calls] == [
        "memory_store_messages",
        "memory_store_messages",
        "memory_rebuild_communities",
    ]
    assert all(
        arguments["refresh_communities"] is False
        for name, arguments in calls
        if name == "memory_store_messages"
    )
    assert info["community"] == {"community_count": 2}


def test_resume_ingest_skips_already_committed_immutable_episodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_call(_client: object, name: str, arguments: dict[str, object]) -> object:
        calls.append((name, arguments))
        if name == "memory_get":
            return {"id": arguments["memory_id"]} if arguments["memory_id"] in {"m0", "m1"} else None
        if name == "memory_store_messages":
            return [{"id": str(row["memory_id"]), "metadata": {}} for row in arguments["messages"]]
        return {"community_count": 1}

    monkeypatch.setattr(runner, "call_tool", fake_call)
    messages = [
        {"memory_id": f"m{index}", "session_id": "s1", "role": "user", "content": "x"}
        for index in range(3)
    ]

    info, _rows = asyncio.run(
        runner.ingest_conversation(
            object(),
            user_identifier="alice",
            messages=messages,
            batch_size=2,
            skip_existing=True,
        )
    )

    stored_call = next(arguments for name, arguments in calls if name == "memory_store_messages")
    assert [row["memory_id"] for row in stored_call["messages"]] == ["m2"]
    assert info["messages"] == 3
    assert info["existing_results"] == 2
    assert info["stored_results"] == 1


def test_metrics_report_first_relevant_reciprocal_rank() -> None:
    bucket = runner.init_metric_counts()

    runner.update_metrics(
        bucket,
        evidence=["D1:1", "D1:9"],
        retrieved_refs=["D1:4", "D1:1", "D1:9"],
        answer_hit_by_k={20: True, 50: True, 200: True},
        ks=[20, 50, 200],
        latency_ms=12.0,
        search_error=False,
    )

    metrics = runner.finalize_metrics(bucket, [20, 50, 200])
    assert metrics["mrr"] == 0.5
    assert metrics["evidence_any_at_20"] == 1.0
    assert metrics["evidence_all_at_20"] == 1.0


def test_compact_hit_keeps_answer_context_and_token_accounting() -> None:
    hit = {
        "id": "m1",
        "content": "Alice moved to Rome.",
        "score": 0.8,
        "metadata": {"dia_id": "D1:1", "sample_id": "conv-1"},
    }

    compact = runner.compact_hit(hit, 1)

    assert compact["content"] == "Alice moved to Rome."
    assert compact["estimated_tokens"] == runner.estimate_tokens("Alice moved to Rome.")


def test_retrieval_diagnostics_reports_reranker_and_channel_identity() -> None:
    hits = [
        {
            "score_details": {
                "rerank_status": "provider_floor_fallback",
                "rerank_model": "Qwen3-Reranker-0.6B-q8_0.gguf",
                "channels": {
                    "episode_dense": {"rank": 1},
                    "bm25": {"rank": 3},
                },
            }
        },
        {
            "score_details": {
                "rerank_status": "provider_floor_fallback",
                "rerank_model": "Qwen3-Reranker-0.6B-q8_0.gguf",
                "channels": {"entity_dense": {"rank": 2}},
            }
        },
        {
            "score_details": {
                "rerank_status": "candidate_limit",
                "rerank_model": "Qwen3-Reranker-0.6B-q8_0.gguf",
                "channels": {"graph": {"rank": 4}},
            }
        },
    ]

    assert runner.retrieval_diagnostics(hits) == {
        "rerank_status": "provider_floor_fallback",
        "rerank_model": "Qwen3-Reranker-0.6B-q8_0.gguf",
        "rerank_candidate_limited": True,
        "retrieval_channels": ["bm25", "entity_dense", "episode_dense", "graph"],
    }


def test_conversation_ingest_never_contains_qa_gold_answers() -> None:
    item = {
        "sample_id": "conv-1",
        "conversation": {
            "session_1_date_time": "2026-01-01",
            "session_1": [{"dia_id": "D1:1", "speaker": "Alice", "text": "I moved."}],
        },
        "qa": [{"question": "Where?", "answer": "SECRET_GOLD", "category": 1}],
    }

    messages, _ = runner.build_messages(item)

    assert "SECRET_GOLD" not in repr(messages)


def test_turn_content_omits_embedded_image_bytes_but_keeps_media_context() -> None:
    content = runner.turn_content(
        "conv-1",
        "session_1",
        "2026-01-01",
        {
            "dia_id": "D1:1",
            "speaker": "Alice",
            "text": "Look at this.",
            "query": "turtles basking",
            "blip_caption": "three turtles on rocks",
            "img_url": [
                "data:image/jpeg;base64,/9j/VERY-LONG-BINARY",
                "https://example.test/turtles.jpg?token=SECRET-SIGNED-VALUE",
            ],
        },
    )

    assert "VERY-LONG-BINARY" not in content
    assert "SECRET-SIGNED-VALUE" not in content
    assert "embedded image/jpeg omitted" in content
    assert "example.test/turtles.jpg" in content
    assert "three turtles on rocks" in content


def test_resume_state_skips_completed_conversations() -> None:
    state = runner.resume_state(
        {
            "conversations": [{"sample_id": "conv-1"}],
            "results": [{"sample_id": "conv-1", "question_index": 1}],
        }
    )

    assert state.completed_samples == frozenset({"conv-1"})
    assert state.results[0]["question_index"] == 1


def test_store_search_limit_supports_mem0_comparable_top_200() -> None:
    from turing_agentmemory_mcp.store import TuringAgentMemory

    assert TuringAgentMemory._clean_limit(200) == 200
    assert TuringAgentMemory._clean_limit(500) == 200


def test_search_concurrency_validation_accepts_one_through_four() -> None:
    assert runner.validate_search_concurrency(1) == 1
    assert runner.validate_search_concurrency(4) == 4
    with pytest.raises(ValueError, match="between 1 and 4"):
        runner.validate_search_concurrency(0)
    with pytest.raises(ValueError, match="between 1 and 4"):
        runner.validate_search_concurrency(5)


def test_concurrent_searches_use_independent_clients_and_restore_question_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [object(), object()]
    active_clients: set[object] = set()
    max_active = 0

    async def fake_call(client: object, name: str, arguments: dict[str, object]) -> object:
        nonlocal max_active
        assert name == "memory_search"
        assert client not in active_clients
        active_clients.add(client)
        max_active = max(max_active, len(active_clients))
        question = str(arguments["query"])
        await asyncio.sleep({"slow": 0.03, "fast": 0.001, "medium": 0.002}[question])
        active_clients.remove(client)
        evidence_id = {"slow": "D1:1", "fast": "D1:2", "medium": "D1:3"}[question]
        return [
            {
                "id": evidence_id,
                "content": f"answer for {question}",
                "metadata": {"dia_id": evidence_id},
            }
        ]

    monkeypatch.setattr(runner, "call_tool", fake_call)
    item = {
        "sample_id": "conv-test",
        "qa": [
            {"category": 1, "question": "slow", "answer": "answer", "evidence": ["D1:1"]},
            {"category": 1, "question": "fast", "answer": "answer", "evidence": ["D1:2"]},
            {"category": 1, "question": "medium", "answer": "answer", "evidence": ["D1:3"]},
        ],
    }

    metrics, rows = asyncio.run(
        runner.evaluate_conversation(
            clients,
            item=item,
            user_identifier="alice",
            top_k=20,
            ks=[1, 3, 5, 10, 20],
            save_results=True,
        )
    )

    assert max_active == 2
    assert metrics["search_errors"] == 0
    assert [row["question_index"] for row in rows] == [1, 2, 3]
