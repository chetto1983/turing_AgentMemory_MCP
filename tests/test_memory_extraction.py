from __future__ import annotations

import json
import math

import pytest

import turing_agentmemory_mcp.memory_extraction as memory_extraction
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    HTTPMemoryExtractor,
    normalize_memory_extraction,
    normalize_memory_extractions,
)

TEXT = "Caroline joined the LGBTQ support group on 7 May 2023."


def provider_result() -> dict[str, object]:
    return {
        "entities": [
            {"text": "Caroline", "label": "person", "score": 0.99, "start": 0, "end": 8},
            {
                "text": "LGBTQ support group",
                "label": "organization",
                "score": 0.96,
                "start": 20,
                "end": 39,
            },
            {"text": "7 May 2023", "label": "date", "score": 0.94, "start": 43, "end": 53},
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


def test_normalize_memory_extraction_preserves_typed_provenance() -> None:
    extraction = normalize_memory_extraction(
        TEXT,
        provider_result(),
        model="lion-ai/gliner2-base-v1-onnx",
        device="cuda",
        schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
    )

    assert extraction.schema_version == MEMORY_EXTRACTION_SCHEMA_VERSION
    assert extraction.model == "lion-ai/gliner2-base-v1-onnx"
    assert extraction.device == "cuda"
    assert extraction.entities[0].text == "Caroline"
    assert extraction.entities[1].span == (20, 39)
    assert extraction.relations[0].relation == "participated_in"
    assert extraction.relations[0].subject.text == "Caroline"
    assert extraction.relations[0].object.text == "LGBTQ support group"
    assert extraction.memory_kind.label == "episodic_event"
    assert extraction.memory_kind.score == pytest.approx(0.88)


@pytest.mark.parametrize(
    "mutation",
    [
        {"text": "Carol", "label": "person", "score": 0.99, "start": 0, "end": 8},
        {"text": "Caroline", "label": "person", "score": math.nan, "start": 0, "end": 8},
        {"text": "Caroline", "label": "person", "score": 1.01, "start": 0, "end": 8},
        {"text": "Caroline", "label": "person", "score": 0.99, "start": -1, "end": 8},
    ],
)
def test_normalize_memory_extraction_rejects_corrupt_entities(
    mutation: dict[str, object],
) -> None:
    raw = provider_result()
    raw["entities"] = [mutation]

    with pytest.raises(ValueError):
        normalize_memory_extraction(
            TEXT,
            raw,
            model="model",
            device="cpu",
            schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
        )


def test_normalize_memory_extraction_rejects_relation_endpoint_not_in_entities() -> None:
    raw = provider_result()
    relation = raw["relations"][0]  # type: ignore[index]
    relation["subject"] = {  # type: ignore[index]
        "text": "joined",
        "label": "activity",
        "score": 0.8,
        "start": 9,
        "end": 15,
    }

    with pytest.raises(ValueError, match="relation endpoint"):
        normalize_memory_extraction(
            TEXT,
            raw,
            model="model",
            device="cpu",
            schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
        )


def test_normalize_memory_extractions_rejects_result_count_mismatch() -> None:
    with pytest.raises(ValueError, match="result count"):
        normalize_memory_extractions(
            [TEXT, "Second message"],
            [provider_result()],
            model="model",
            device="cpu",
            schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
        )


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_http_memory_extractor_posts_versioned_batch_and_normalizes(monkeypatch) -> None:
    requests: list[tuple[object, float]] = []
    response = {
        "model": "lion-ai/gliner2-base-v1-onnx",
        "device": "cuda",
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        "results": [provider_result()],
    }

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse(response)

    monkeypatch.setattr(memory_extraction, "urlopen", fake_urlopen)
    extractor = HTTPMemoryExtractor(
        base_url="http://agentmemory-gliner:8080/",
        model_name="lion-ai/gliner2-base-v1-onnx",
        threshold=0.55,
        timeout_s=12.5,
    )

    results = extractor.extract_many([TEXT])

    assert results[0].relations[0].relation == "participated_in"
    assert results[0].memory_kind.label == "episodic_event"
    request, timeout = requests[0]
    assert request.full_url == "http://agentmemory-gliner:8080/extract-memory"
    assert json.loads(request.data) == {
        "texts": [TEXT],
        "threshold": 0.55,
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
    }
    assert timeout == 12.5


def test_http_memory_extractor_chunks_long_text_and_restores_offsets(monkeypatch) -> None:
    prefix = "A" * memory_extraction.MAX_MEMORY_EXTRACTION_TEXT_CHARS
    text = prefix + " Rome"
    requests: list[list[str]] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        del timeout
        payload = json.loads(request.data)
        request_texts = payload["texts"]
        requests.append(request_texts)
        results = []
        for chunk in request_texts:
            start = chunk.find("Rome")
            entities = (
                [{"text": "Rome", "label": "location", "score": 0.99, "start": start, "end": start + 4}]
                if start >= 0
                else []
            )
            results.append(
                {
                    "entities": entities,
                    "relations": [],
                    "classifications": {
                        "memory_kind": [
                            {
                                "label": "episodic_event",
                                "score": 0.9 if start >= 0 else 0.6,
                            }
                        ]
                    },
                }
            )
        return FakeResponse(
            {
                "model": "model",
                "device": "cpu",
                "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
                "results": results,
            }
        )

    monkeypatch.setattr(memory_extraction, "urlopen", fake_urlopen)

    result = HTTPMemoryExtractor(base_url="http://provider", model_name="model").extract_many(
        [text]
    )[0]

    assert len(requests) == 1
    assert len(requests[0]) == 2
    assert all(
        len(chunk) <= memory_extraction.MAX_MEMORY_EXTRACTION_TEXT_CHARS
        for chunk in requests[0]
    )
    assert result.entities[0].text == "Rome"
    assert result.entities[0].start == len(prefix) + 1
    assert result.entities[0].end == len(text)
    assert result.memory_kind.score == 0.9


@pytest.mark.parametrize(
    "response",
    [
        {
            "model": "wrong-model",
            "device": "cpu",
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "results": [provider_result()],
        },
        {
            "model": "model",
            "device": "cpu",
            "schema_version": "memory-v0",
            "results": [provider_result()],
        },
        {
            "model": "model",
            "device": "cpu",
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "results": [],
        },
    ],
)
def test_http_memory_extractor_rejects_provider_contract(
    monkeypatch, response: dict[str, object]
) -> None:
    monkeypatch.setattr(
        memory_extraction,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(response),
    )
    extractor = HTTPMemoryExtractor(base_url="http://provider", model_name="model")

    with pytest.raises(RuntimeError):
        extractor.extract_many([TEXT])


def test_http_memory_extractor_rejects_corrupt_provider_provenance(monkeypatch) -> None:
    raw = provider_result()
    raw["entities"] = [
        {"text": "Caroline", "label": "person", "score": 0.99, "start": 1, "end": 9}
    ]
    response = {
        "model": "model",
        "device": "cpu",
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        "results": [raw],
    }
    monkeypatch.setattr(
        memory_extraction,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(response),
    )

    with pytest.raises(RuntimeError, match="invalid extraction results"):
        HTTPMemoryExtractor(base_url="http://provider", model_name="model").extract_many([TEXT])
