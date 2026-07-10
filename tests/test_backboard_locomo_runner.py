from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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
                    "model": "fastino/gliner2-base-v1",
                    "entity_count": 2,
                }
            }
        },
        {"metadata": {}},
    ]

    assert runner.summarize_entity_extraction(rows) == {
        "annotated_memories": 1,
        "entities": 2,
        "models": ["fastino/gliner2-base-v1"],
    }


@pytest.mark.parametrize(
    "summary",
    [
        {"annotated_memories": 0, "entities": 0, "models": []},
        {"annotated_memories": 1, "entities": 2, "models": ["wrong-model"]},
    ],
)
def test_require_entity_model_rejects_missing_or_different_model(summary: dict[str, object]) -> None:
    with pytest.raises(RuntimeError, match="fastino/gliner2-base-v1"):
        runner.require_entity_model(summary, "fastino/gliner2-base-v1")
