from __future__ import annotations

import pytest

import turing_agentmemory_mcp.gliner_provider as gliner_provider
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_ENTITY_LABELS,
    MEMORY_KIND_LABELS,
    MEMORY_RELATION_SCHEMA,
)


def test_fast_gliner2_adapter_serializes_batch_and_applies_threshold() -> None:
    class FakeFastGLiNER2:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[str]]] = []

        def predict_entities(self, text: str, labels: list[str]) -> list[dict[str, object]]:
            self.calls.append((text, labels))
            return [
                {"text": text, "label": "project", "score": 0.91, "start": 0, "end": len(text)},
                {"text": "low", "label": "project", "score": 0.2, "start": 0, "end": 3},
            ]

    model = FakeFastGLiNER2()
    adapter = gliner_provider.FastGLiNER2Adapter(model)

    assert adapter.batch_extract_entities(
        ["Aurora", "ArcadeDB"],
        ["project"],
        batch_size=16,
        threshold=0.5,
        include_confidence=True,
        include_spans=True,
    ) == [
        [{"text": "Aurora", "label": "project", "score": 0.91, "start": 0, "end": 6}],
        [{"text": "ArcadeDB", "label": "project", "score": 0.91, "start": 0, "end": 8}],
    ]
    assert model.calls == [("Aurora", ["project"]), ("ArcadeDB", ["project"])]


def test_fast_gliner2_adapter_extracts_constrained_memory_with_complete_endpoints() -> None:
    text = "Caroline joined the LGBTQ support group."

    class FakeFastGLiNER2:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def predict_entities(self, value: str, labels: list[str]) -> list[dict[str, object]]:
            self.calls.append(("entities", value, labels))
            return [
                {"text": "Caroline", "label": "person", "score": 0.99, "start": 0, "end": 8},
                {"text": "joined", "label": "activity", "score": 0.1, "start": 9, "end": 15},
            ]

        def extract_relations(
            self,
            value: str,
            labels: list[str],
            schema: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            self.calls.append(("relations", value, labels, schema))
            return [
                {
                    "relation": "participated_in",
                    "score": 0.93,
                    "subject": {
                        "text": "Caroline",
                        "label": "person",
                        "score": 0.99,
                        "start": 0,
                        "end": 8,
                    },
                    "object": {
                        "text": "LGBTQ support group",
                        "label": "organization",
                        "score": 0.96,
                        "start": 20,
                        "end": 39,
                    },
                },
                {
                    "relation": "likes",
                    "score": 0.2,
                    "subject": {
                        "text": "Caroline",
                        "label": "person",
                        "score": 0.99,
                        "start": 0,
                        "end": 8,
                    },
                    "object": {
                        "text": "LGBTQ support group",
                        "label": "organization",
                        "score": 0.96,
                        "start": 20,
                        "end": 39,
                    },
                },
            ]

        def classify(self, value: str, labels: list[str]) -> list[tuple[str, float]]:
            self.calls.append(("classify", value, labels))
            return [("episodic_event", 0.88), ("preference", 0.04)]

    model = FakeFastGLiNER2()
    adapter = gliner_provider.FastGLiNER2Adapter(model)

    assert adapter.batch_extract_memory([text], batch_size=8, threshold=0.5) == [
        {
            "entities": [
                {"text": "Caroline", "label": "person", "score": 0.99, "start": 0, "end": 8},
                {
                    "text": "LGBTQ support group",
                    "label": "organization",
                    "score": 0.96,
                    "start": 20,
                    "end": 39,
                },
            ],
            "relations": [
                {
                    "relation": "participated_in",
                    "score": 0.93,
                    "subject": {
                        "text": "Caroline",
                        "label": "person",
                        "score": 0.99,
                        "start": 0,
                        "end": 8,
                    },
                    "object": {
                        "text": "LGBTQ support group",
                        "label": "organization",
                        "score": 0.96,
                        "start": 20,
                        "end": 39,
                    },
                }
            ],
            "classifications": {
                "memory_kind": [
                    {"label": "episodic_event", "score": 0.88},
                    {"label": "preference", "score": 0.04},
                ]
            },
        }
    ]
    assert model.calls == [
        ("entities", text, list(MEMORY_ENTITY_LABELS)),
        ("relations", text, list(MEMORY_ENTITY_LABELS), list(MEMORY_RELATION_SCHEMA)),
        ("classify", text, list(MEMORY_KIND_LABELS)),
    ]


def test_fast_gliner2_adapter_treats_empty_relation_candidates_as_no_relations() -> None:
    class EmptyRelationModel:
        def predict_entities(self, value: str, labels: list[str]) -> list[dict[str, object]]:
            return [
                {
                    "text": "Markdown",
                    "label": "object",
                    "score": 0.86,
                    "start": 40,
                    "end": 48,
                }
            ]

        def extract_relations(
            self,
            value: str,
            labels: list[str],
            schema: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            raise RuntimeError('"invalid input: empty texts and/or entities"')

        def classify(self, value: str, labels: list[str]) -> list[tuple[str, float]]:
            return [("preference", 0.79), ("semantic_fact", 0.21)]

    result = gliner_provider.FastGLiNER2Adapter(EmptyRelationModel()).batch_extract_memory(
        ["Weekly status reports should be concise Markdown."],
        batch_size=1,
        threshold=0.5,
    )

    assert result[0]["relations"] == []
    assert result[0]["entities"] == [
        {
            "text": "Markdown",
            "label": "object",
            "score": 0.86,
            "start": 40,
            "end": 48,
        }
    ]
    assert result[0]["classifications"] == {
        "memory_kind": [
            {"label": "preference", "score": 0.79},
            {"label": "semantic_fact", "score": 0.21},
        ]
    }


def test_fast_gliner2_adapter_does_not_hide_other_relation_failures() -> None:
    class FailingRelationModel:
        def predict_entities(self, value: str, labels: list[str]) -> list[dict[str, object]]:
            return []

        def extract_relations(
            self,
            value: str,
            labels: list[str],
            schema: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            raise RuntimeError("model execution failed")

        def classify(self, value: str, labels: list[str]) -> list[tuple[str, float]]:
            raise AssertionError("classification must not run after an unexpected relation failure")

    adapter = gliner_provider.FastGLiNER2Adapter(FailingRelationModel())

    with pytest.raises(RuntimeError, match="model execution failed"):
        adapter.batch_extract_memory(["text"], batch_size=1, threshold=0.5)


def test_fast_gliner2_adapter_converts_utf8_byte_offsets_to_character_offsets() -> None:
    text = "Alice — family 🌟 Rome"

    def byte_span(value: str) -> tuple[int, int]:
        start = text.encode("utf-8").index(value.encode("utf-8"))
        return start, start + len(value.encode("utf-8"))

    family_start, family_end = byte_span("family")
    rome_start, rome_end = byte_span("Rome")

    class ByteOffsetModel:
        def predict_entities(self, value: str, labels: list[str]) -> list[dict[str, object]]:
            return [
                {
                    "text": "family",
                    "label": "group",
                    "score": 0.9,
                    "start": family_start,
                    "end": family_end,
                }
            ]

        def extract_relations(
            self,
            value: str,
            labels: list[str],
            schema: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            return [
                {
                    "relation": "located_in",
                    "score": 0.8,
                    "subject": {
                        "text": "family",
                        "label": "group",
                        "score": 0.9,
                        "start": family_start,
                        "end": family_end,
                    },
                    "object": {
                        "text": "Rome",
                        "label": "location",
                        "score": 0.9,
                        "start": rome_start,
                        "end": rome_end,
                    },
                }
            ]

        def classify(self, value: str, labels: list[str]) -> list[tuple[str, float]]:
            return [("semantic_fact", 0.9)]

    result = gliner_provider.FastGLiNER2Adapter(ByteOffsetModel()).batch_extract_memory(
        [text], batch_size=1, threshold=0.5
    )[0]

    expected_family = (text.index("family"), text.index("family") + len("family"))
    expected_rome = (text.index("Rome"), text.index("Rome") + len("Rome"))
    assert (result["entities"][0]["start"], result["entities"][0]["end"]) == expected_family
    assert (
        result["relations"][0]["subject"]["start"],
        result["relations"][0]["subject"]["end"],
    ) == expected_family
    assert (
        result["relations"][0]["object"]["start"],
        result["relations"][0]["object"]["end"],
    ) == expected_rome


def test_fast_gliner2_adapter_rejects_offsets_that_match_neither_contract() -> None:
    class CorruptModel:
        def predict_entities(self, text: str, labels: list[str]) -> list[dict[str, object]]:
            return [{"text": "Alice", "label": "person", "score": 0.9, "start": 2, "end": 7}]

    with pytest.raises(ValueError, match="offsets"):
        gliner_provider.FastGLiNER2Adapter(CorruptModel()).batch_extract_entities(
            ["Alice in Rome"],
            ["person"],
            batch_size=1,
            threshold=0.5,
            include_confidence=True,
            include_spans=True,
        )
