from __future__ import annotations

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
    assert runner.MAX_INGEST_BATCH == 256
    assert runner.retrieval_cutoffs(200) == [1, 3, 5, 10, 20, 50, 200]


def test_ingest_batch_validation_matches_gliner_sidecar_contract() -> None:
    assert runner.validate_batch_size(256) == 256
    with pytest.raises(ValueError, match="between 1 and 256"):
        runner.validate_batch_size(257)


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
