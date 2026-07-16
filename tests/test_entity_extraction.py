from __future__ import annotations

import sys
import types

from turing_agentmemory_mcp.entity_extraction import (
    NoopEntityProcessor,
    entity_metadata_search_text,
    entity_processor_from_env,
)


def test_entity_processor_from_env_defaults_to_noop(monkeypatch) -> None:
    monkeypatch.delenv("GLINER_ENABLED", raising=False)

    assert isinstance(entity_processor_from_env(), NoopEntityProcessor)


def test_gliner2_onnx_processor_redacts_and_hides_raw_text(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeEntity:
        def __init__(self, text: str, label: str, start: int, end: int, score: float) -> None:
            self.text = text
            self.label = label
            self.start = start
            self.end = end
            self.score = score

    class FakeRuntime:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: object) -> FakeRuntime:
            calls.append({"model_name": model_name, "kwargs": kwargs})
            return cls()

        def extract_entities(
            self,
            text: str,
            labels: list[str],
            threshold: float = 0.5,
        ) -> list[FakeEntity]:
            calls.append({"text": text, "labels": labels, "threshold": threshold})
            email = "alice@example.com"
            return [
                FakeEntity("Alice", "person", 0, 5, 0.91),
                FakeEntity(email, "email", text.index(email), text.index(email) + len(email), 0.98),
            ]

    monkeypatch.setitem(
        sys.modules,
        "gliner2_onnx",
        types.SimpleNamespace(GLiNER2ONNXRuntime=FakeRuntime),
    )
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2_onnx")
    monkeypatch.setenv("GLINER_MODEL", "lmo3/gliner2-multi-v1-onnx")
    monkeypatch.setenv("GLINER_LABELS", "person,email")
    monkeypatch.setenv("GLINER_THRESHOLD", "0.42")
    monkeypatch.setenv("GLINER_REDACT", "1")
    monkeypatch.setenv("GLINER_PRECISION", "fp16")
    monkeypatch.setenv("GLINER_PROVIDERS", "CPUExecutionProvider")

    processor = entity_processor_from_env()
    result = processor.process("Alice uses alice@example.com")

    assert result.text == "[PERSON] uses [EMAIL]"
    assert calls[0] == {
        "model_name": "lmo3/gliner2-multi-v1-onnx",
        "kwargs": {"precision": "fp16", "providers": ["CPUExecutionProvider"]},
    }
    assert calls[1] == {
        "text": "Alice uses alice@example.com",
        "labels": ["person", "email"],
        "threshold": 0.42,
    }
    detection = result.metadata["entity_extraction"]
    assert detection["backend"] == "gliner2_onnx"
    assert detection["model"] == "lmo3/gliner2-multi-v1-onnx"
    assert detection["redacted"] is True
    assert detection["entity_count"] == 2
    assert detection["entities"][0] == {
        "label": "person",
        "start": 0,
        "end": 5,
        "score": 0.91,
    }
    assert all("text" not in entity for entity in detection["entities"])


def test_gliner_processor_keeps_text_when_redaction_disabled(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeModel:
        def predict_entities(
            self,
            text: str,
            labels: list[str],
            threshold: float = 0.5,
        ) -> list[dict[str, object]]:
            calls.append({"text": text, "labels": labels, "threshold": threshold})
            return [{"text": "ArcadeDB", "label": "product", "start": 0, "end": 8, "score": 0.77}]

    class FakeGLiNER:
        @classmethod
        def from_pretrained(cls, model_name: str) -> FakeModel:
            calls.append({"model_name": model_name})
            return FakeModel()

    monkeypatch.setitem(sys.modules, "gliner", types.SimpleNamespace(GLiNER=FakeGLiNER))
    monkeypatch.setenv("GLINER_ENABLED", "true")
    monkeypatch.setenv("GLINER_BACKEND", "gliner")
    monkeypatch.setenv("GLINER_MODEL", "gliner-community/gliner_small-v2.5")
    monkeypatch.setenv("GLINER_LABELS", "product")
    monkeypatch.setenv("GLINER_REDACT", "0")

    processor = entity_processor_from_env()
    result = processor.process("ArcadeDB stores memory")

    assert result.text == "ArcadeDB stores memory"
    assert calls == [
        {"model_name": "gliner-community/gliner_small-v2.5"},
        {"text": "ArcadeDB stores memory", "labels": ["product"], "threshold": 0.5},
    ]
    assert result.metadata["entity_extraction"]["entities"] == [
        {"text": "ArcadeDB", "label": "product", "start": 0, "end": 8, "score": 0.77}
    ]


def test_gliner2_processor_uses_extract_entities(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeGLiNER2Model:
        def extract_entities(
            self,
            text: str,
            labels: list[str],
            threshold: float = 0.5,
            include_confidence: bool = False,
            include_spans: bool = False,
        ) -> dict[str, dict[str, list[dict[str, object]]]]:
            calls.append(
                {
                    "text": text,
                    "labels": labels,
                    "threshold": threshold,
                    "include_confidence": include_confidence,
                    "include_spans": include_spans,
                }
            )
            return {
                "entities": {
                    "email": [
                        {
                            "text": "alice@example.com",
                            "start": 6,
                            "end": 23,
                            "confidence": 0.94,
                        }
                    ]
                }
            }

    class FakeGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str) -> FakeGLiNER2Model:
            calls.append({"model_name": model_name})
            return FakeGLiNER2Model()

    monkeypatch.setitem(sys.modules, "gliner2", types.SimpleNamespace(GLiNER2=FakeGLiNER2))
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2")
    monkeypatch.setenv("GLINER_MODEL", "fastino/gliner2-privacy-filter-PII-multi")
    monkeypatch.setenv("GLINER_LABELS", "email")

    processor = entity_processor_from_env()
    result = processor.process("Email alice@example.com")

    assert calls == [
        {"model_name": "fastino/gliner2-privacy-filter-PII-multi"},
        {
            "text": "Email alice@example.com",
            "labels": ["email"],
            "threshold": 0.5,
            "include_confidence": True,
            "include_spans": True,
        },
    ]
    assert result.metadata["entity_extraction"]["backend"] == "gliner2"
    assert result.metadata["entity_extraction"]["entity_count"] == 1
    assert result.metadata["entity_extraction"]["entities"] == [
        {"text": "alice@example.com", "label": "email", "start": 6, "end": 23, "score": 0.94}
    ]


def test_entity_processor_omits_native_entity_with_malformed_span(monkeypatch) -> None:
    class FakeGLiNER2Model:
        def extract_entities(
            self,
            text: str,
            labels: list[str],
            threshold: float = 0.5,
            include_confidence: bool = False,
            include_spans: bool = False,
        ) -> dict[str, dict[str, list[dict[str, object]]]]:
            return {
                "entities": {
                    "email": [
                        {
                            "text": "alice@example.com",
                            "start": 6,
                            "end": len(text) + 1,
                            "confidence": 0.94,
                        }
                    ]
                }
            }

    class FakeGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str) -> FakeGLiNER2Model:
            return FakeGLiNER2Model()

    monkeypatch.setitem(sys.modules, "gliner2", types.SimpleNamespace(GLiNER2=FakeGLiNER2))
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2")
    monkeypatch.setenv("GLINER_LABELS", "email")

    processor = entity_processor_from_env()

    assert processor.process("Email alice@example.com").metadata == {}


def _native_gliner2_processor(monkeypatch, response: object, *, redact: bool = False):
    class FakeGLiNER2Model:
        def extract_entities(
            self,
            text: str,
            labels: list[str],
            threshold: float = 0.5,
            include_confidence: bool = False,
            include_spans: bool = False,
        ) -> object:
            return response

    class FakeGLiNER2:
        @classmethod
        def from_pretrained(cls, model_name: str) -> FakeGLiNER2Model:
            return FakeGLiNER2Model()

    monkeypatch.setitem(sys.modules, "gliner2", types.SimpleNamespace(GLiNER2=FakeGLiNER2))
    monkeypatch.setenv("GLINER_ENABLED", "1")
    monkeypatch.setenv("GLINER_BACKEND", "gliner2")
    monkeypatch.setenv("GLINER_LABELS", "email")
    monkeypatch.setenv("GLINER_REDACT", "1" if redact else "0")
    return entity_processor_from_env()


def test_gliner2_normalizes_nested_string_entity_value(monkeypatch) -> None:
    processor = _native_gliner2_processor(
        monkeypatch, {"entities": {"email": ["alice@example.com"]}}
    )

    result = processor.process("Email alice@example.com")

    assert result.metadata["entity_extraction"]["entities"] == [
        {"text": "alice@example.com", "label": "email", "start": 6, "end": 23}
    ]


def test_gliner2_assigns_repeated_string_values_to_distinct_spans_and_redacts_both(
    monkeypatch,
) -> None:
    processor = _native_gliner2_processor(
        monkeypatch,
        {"entities": {"email": ["alice@example.com", "alice@example.com"]}},
        redact=True,
    )

    result = processor.process("alice@example.com and alice@example.com")

    assert result.text == "[EMAIL] and [EMAIL]"
    assert result.metadata["entity_extraction"]["entities"] == [
        {"label": "email", "start": 0, "end": 17},
        {"label": "email", "start": 22, "end": 39},
    ]


def test_gliner2_omits_excess_repeated_string_values(monkeypatch) -> None:
    processor = _native_gliner2_processor(
        monkeypatch,
        {"entities": {"email": ["alice@example.com", "alice@example.com"]}},
    )

    result = processor.process("alice@example.com")

    assert result.metadata["entity_extraction"]["entity_count"] == 1
    assert result.metadata["entity_extraction"]["entities"] == [
        {"text": "alice@example.com", "label": "email", "start": 0, "end": 17}
    ]


def test_gliner2_rejects_partial_or_nonnumeric_explicit_spans(monkeypatch) -> None:
    processor = _native_gliner2_processor(
        monkeypatch,
        {
            "entities": {
                "email": [
                    {"text": "alice@example.com", "start": 0},
                    {"text": "alice@example.com", "end": 17},
                    {"text": "alice@example.com", "start": "zero", "end": 17},
                ]
            }
        },
    )

    assert processor.process("alice@example.com").metadata == {}


def test_gliner2_rejects_explicit_text_span_mismatch_without_redacting(monkeypatch) -> None:
    processor = _native_gliner2_processor(
        monkeypatch,
        {"entities": {"email": [{"text": "not-alice", "start": 0, "end": 17}]}},
        redact=True,
    )

    result = processor.process("alice@example.com")

    assert result.text == "alice@example.com"
    assert result.metadata == {}


def test_gliner2_omits_nonfinite_confidence_scores_but_keeps_entities(monkeypatch) -> None:
    processor = _native_gliner2_processor(
        monkeypatch,
        {
            "entities": {
                "email": [
                    {"text": "one@example.com", "start": 0, "end": 15, "confidence": "nan"},
                    {"text": "two@example.com", "start": 16, "end": 31, "confidence": float("inf")},
                    {
                        "text": "three@example.com",
                        "start": 32,
                        "end": 49,
                        "confidence": float("-inf"),
                    },
                ]
            }
        },
    )

    result = processor.process("one@example.com two@example.com three@example.com")

    assert result.metadata["entity_extraction"]["entity_count"] == 3
    assert all("score" not in entity for entity in result.metadata["entity_extraction"]["entities"])


def test_entity_metadata_search_text_includes_labels_and_extracted_text() -> None:
    metadata = {
        "entity_extraction": {
            "labels": ["project", "library"],
            "entities": [
                {"text": "ArcadeDB", "label": "project"},
                {"text": "FastMCP", "label": "library"},
            ],
        }
    }

    assert (
        entity_metadata_search_text(metadata) == "project library project ArcadeDB library FastMCP"
    )
