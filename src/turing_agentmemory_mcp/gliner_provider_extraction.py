"""GLiNER2 extraction logic, wire-payload validation, and label-schema handling."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Protocol

from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_ENTITY_LABELS,
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MEMORY_KIND_LABELS,
    MEMORY_RELATION_SCHEMA,
)

DEFAULT_MODEL_NAME = "lion-ai/gliner2-base-v1-onnx"
DEFAULT_MODEL_REVISION = "5551729ccc76b30395bc9600f2348ec52a87cead"
MAX_TEXTS = 256
MAX_LABELS = 64
MAX_TEXT_CHARS = 16_384
MAX_LABEL_CHARS = 256
EMPTY_RELATION_INPUT_ERROR = "invalid input: empty texts and/or entities"


class RequestFailure(ValueError):
    def __init__(self, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.status = status
        super().__init__(status.phrase)


class ProviderFailure(ValueError):
    pass


class ExtractProvider(Protocol):
    def extract(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def extract_memory(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def health_payload(self) -> dict[str, Any]: ...


@dataclass
class FastGLiNER2Adapter:
    """Adapt FastGLiNER2's one-text API to the provider batch contract."""

    model: Any

    def batch_extract_entities(
        self,
        texts: list[str],
        labels: list[str],
        *,
        batch_size: int,
        threshold: float,
        include_confidence: bool,
        include_spans: bool,
    ) -> list[list[dict[str, Any]]]:
        del batch_size  # FastGLiNER2 currently accepts one text per inference.
        results: list[list[dict[str, Any]]] = []
        for text in texts:
            raw_entities = self.model.predict_entities(text, labels)
            if not isinstance(raw_entities, list):
                raise ValueError("FastGLiNER2 returned a non-list result")
            entities: list[dict[str, Any]] = []
            for raw in raw_entities:
                if not isinstance(raw, dict):
                    continue
                score = raw.get("score")
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(float(score))
                    or float(score) < threshold
                ):
                    continue
                entity = _normalize_entity_offsets(text, raw)
                if not include_confidence:
                    entity.pop("score", None)
                if not include_spans:
                    entity.pop("start", None)
                    entity.pop("end", None)
                entities.append(entity)
            results.append(entities)
        return results

    def batch_extract_memory(
        self,
        texts: list[str],
        *,
        batch_size: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        del batch_size  # FastGLiNER2 currently accepts one text per inference.
        results: list[dict[str, Any]] = []
        labels = list(MEMORY_ENTITY_LABELS)
        relation_schema = list(MEMORY_RELATION_SCHEMA)
        memory_kinds = list(MEMORY_KIND_LABELS)
        for text in texts:
            raw_entities = self.model.predict_entities(text, labels)
            try:
                raw_relations = self.model.extract_relations(text, labels, relation_schema)
            except RuntimeError as exc:
                if str(exc).strip().strip('"') != EMPTY_RELATION_INPUT_ERROR:
                    raise
                raw_relations = []
            raw_classifications = self.model.classify(text, memory_kinds)
            entities = _filter_scored_objects(raw_entities, threshold, "entity")
            relations = _filter_scored_objects(raw_relations, threshold, "relation")
            entities = [_normalize_entity_offsets(text, entity) for entity in entities]
            relations = [_normalize_relation_offsets(text, relation) for relation in relations]
            entities = _merge_relation_endpoints(entities, relations)
            classifications = _normalize_classifications(raw_classifications)
            results.append(
                {
                    "entities": entities,
                    "relations": relations,
                    "classifications": {"memory_kind": classifications},
                }
            )
        return results


@dataclass
class GLiNERProvider:
    model: Any
    model_name: str = DEFAULT_MODEL_NAME
    device: str = "cpu"
    batch_size: int = 8
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size <= 0
        ):
            raise ValueError("batch_size must be a positive integer")
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("GLiNERProvider device must be cpu or cuda")

    def extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        texts, labels, threshold, include_confidence, include_spans = _validate_extract_payload(
            payload
        )
        try:
            with self.lock:
                results = self.model.batch_extract_entities(
                    texts,
                    labels,
                    batch_size=self.batch_size,
                    threshold=threshold,
                    include_confidence=include_confidence,
                    include_spans=include_spans,
                )
        except Exception as exc:
            raise ProviderFailure("model inference failed") from exc
        if not isinstance(results, list):
            raise ProviderFailure("model must return a list of results")
        if len(results) != len(texts):
            raise ProviderFailure("model result count must match text count")
        return {"model": self.model_name, "device": self.device, "results": results}

    def extract_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        texts, threshold = _validate_extract_memory_payload(payload)
        try:
            with self.lock:
                results = self.model.batch_extract_memory(
                    texts,
                    batch_size=self.batch_size,
                    threshold=threshold,
                )
        except Exception as exc:
            raise ProviderFailure("model inference failed") from exc
        if not isinstance(results, list):
            raise ProviderFailure("model must return a list of results")
        if len(results) != len(texts):
            raise ProviderFailure("model result count must match text count")
        return {
            "model": self.model_name,
            "device": self.device,
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "results": results,
        }

    def health_payload(self) -> dict[str, str]:
        return {"status": "ok", "model": self.model_name, "device": self.device}


def _validate_extract_payload(
    payload: dict[str, Any],
) -> tuple[list[str], list[str], float, bool, bool]:
    if not isinstance(payload, dict):
        raise RequestFailure()
    texts = _validate_string_list(payload.get("texts"), "texts", MAX_TEXTS, MAX_TEXT_CHARS)
    labels = _validate_string_list(payload.get("labels"), "labels", MAX_LABELS, MAX_LABEL_CHARS)
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RequestFailure()
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise RequestFailure()
    include_confidence = payload.get("include_confidence")
    include_spans = payload.get("include_spans")
    if not isinstance(include_confidence, bool) or not isinstance(include_spans, bool):
        raise RequestFailure()
    return texts, labels, threshold, include_confidence, include_spans


def _validate_extract_memory_payload(payload: dict[str, Any]) -> tuple[list[str], float]:
    if not isinstance(payload, dict):
        raise RequestFailure()
    if payload.get("schema_version") != MEMORY_EXTRACTION_SCHEMA_VERSION:
        raise RequestFailure()
    texts = _validate_string_list(payload.get("texts"), "texts", MAX_TEXTS, MAX_TEXT_CHARS)
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RequestFailure()
    threshold = float(threshold)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise RequestFailure()
    return texts, threshold


def _filter_scored_objects(value: object, threshold: float, kind: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"FastGLiNER2 returned non-list {kind} results")
    filtered: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"FastGLiNER2 returned malformed {kind} result")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"FastGLiNER2 returned malformed {kind} score")
        score = float(score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"FastGLiNER2 returned malformed {kind} score")
        if score >= threshold:
            filtered.append(dict(item))
    return filtered


def _normalize_entity_offsets(text: str, entity: dict[str, Any]) -> dict[str, Any]:
    value = entity.get("text")
    start = entity.get("start")
    end = entity.get("end")
    if (
        not isinstance(value, str)
        or not value
        or isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        raise ValueError("FastGLiNER2 returned malformed entity offsets")
    normalized = dict(entity)
    if 0 <= start < end <= len(text) and text[start:end] == value:
        return normalized

    encoded = text.encode("utf-8")
    if not 0 <= start < end <= len(encoded):
        raise ValueError("FastGLiNER2 returned invalid entity offsets")
    try:
        prefix = encoded[:start].decode("utf-8")
        byte_value = encoded[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("FastGLiNER2 returned invalid UTF-8 entity offsets") from exc
    if byte_value != value:
        raise ValueError("FastGLiNER2 entity offsets match neither characters nor UTF-8 bytes")
    normalized["start"] = len(prefix)
    normalized["end"] = len(prefix) + len(byte_value)
    return normalized


def _normalize_relation_offsets(text: str, relation: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(relation)
    for endpoint_name in ("subject", "object"):
        endpoint = relation.get(endpoint_name)
        if not isinstance(endpoint, dict):
            raise ValueError("FastGLiNER2 returned malformed relation endpoint")
        normalized[endpoint_name] = _normalize_entity_offsets(text, endpoint)
    return normalized


def _merge_relation_endpoints(
    entities: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(entities)
    identities = {_raw_entity_identity(entity) for entity in merged}
    for relation in relations:
        for endpoint_name in ("subject", "object"):
            endpoint = relation.get(endpoint_name)
            if not isinstance(endpoint, dict):
                raise ValueError("FastGLiNER2 returned malformed relation endpoint")
            identity = _raw_entity_identity(endpoint)
            if identity not in identities:
                merged.append(dict(endpoint))
                identities.add(identity)
    return merged


def _raw_entity_identity(entity: dict[str, Any]) -> tuple[object, object, object, object]:
    required = ("text", "label", "start", "end", "score")
    if any(name not in entity for name in required):
        raise ValueError("FastGLiNER2 returned incomplete entity provenance")
    return entity["text"], entity["label"], entity["start"], entity["end"]


def _normalize_classifications(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("FastGLiNER2 returned malformed classification results")
    classifications: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("FastGLiNER2 returned malformed classification result")
        label, raw_score = item
        if not isinstance(label, str) or not label or label in seen:
            raise ValueError("FastGLiNER2 returned malformed classification label")
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            raise ValueError("FastGLiNER2 returned malformed classification score")
        score = float(raw_score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("FastGLiNER2 returned malformed classification score")
        seen.add(label)
        classifications.append({"label": label, "score": score})
    return classifications


def _validate_string_list(value: Any, name: str, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > max_items:
        raise RequestFailure()
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > max_chars for item in value
    ):
        raise RequestFailure()
    return value
