"""Typed, versioned contract for semantic memory extraction."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MEMORY_EXTRACTION_SCHEMA_VERSION = "memory-v1"
MAX_MEMORY_EXTRACTION_TEXT_CHARS = 1024
MAX_MEMORY_EXTRACTION_BATCH_TEXTS = 256
MEMORY_ENTITY_LABELS = (
    "person",
    "organization",
    "group",
    "location",
    "event",
    "activity",
    "product",
    "object",
    "topic",
    "date",
    "time",
    "quantity",
)
MEMORY_KIND_LABELS = (
    "episodic_event",
    "semantic_fact",
    "preference",
    "plan",
    "social_relationship",
    "profile_attribute",
)
MEMORY_RELATION_SCHEMA = (
    {
        "relation": "participated_in",
        "subject_labels": ["person"],
        "object_labels": ["event", "activity", "organization", "group"],
    },
    {
        "relation": "member_of",
        "subject_labels": ["person", "organization"],
        "object_labels": ["organization", "group"],
    },
    {
        "relation": "located_in",
        "subject_labels": ["person", "organization", "group", "event", "activity"],
        "object_labels": ["location"],
    },
    {
        "relation": "occurred_on",
        "subject_labels": ["event", "activity"],
        "object_labels": ["date", "time"],
    },
    {
        "relation": "works_for",
        "subject_labels": ["person"],
        "object_labels": ["organization", "group"],
    },
    {
        "relation": "owns",
        "subject_labels": ["person", "organization"],
        "object_labels": ["product", "object"],
    },
    {
        "relation": "prefers",
        "subject_labels": ["person"],
        "object_labels": ["activity", "product", "object", "topic", "location"],
    },
    {
        "relation": "dislikes",
        "subject_labels": ["person"],
        "object_labels": ["activity", "product", "object", "topic", "location"],
    },
    {
        "relation": "plans",
        "subject_labels": ["person", "organization", "group"],
        "object_labels": ["event", "activity", "product", "object", "topic", "location"],
    },
    {
        "relation": "created",
        "subject_labels": ["person", "organization", "group"],
        "object_labels": ["organization", "group", "event", "product", "object"],
    },
    {
        "relation": "recommended",
        "subject_labels": ["person", "organization", "group"],
        "object_labels": ["activity", "product", "object", "topic", "location"],
    },
    {
        "relation": "friend_of",
        "subject_labels": ["person"],
        "object_labels": ["person"],
    },
    {
        "relation": "family_of",
        "subject_labels": ["person"],
        "object_labels": ["person"],
    },
)


@dataclass(frozen=True, slots=True)
class EntityMention:
    text: str
    label: str
    score: float
    start: int
    end: int

    @property
    def span(self) -> tuple[int, int]:
        return self.start, self.end


@dataclass(frozen=True, slots=True)
class RelationMention:
    relation: str
    subject: EntityMention
    object: EntityMention
    score: float


@dataclass(frozen=True, slots=True)
class Classification:
    label: str
    score: float


@dataclass(frozen=True, slots=True)
class MemoryExtraction:
    entities: tuple[EntityMention, ...]
    relations: tuple[RelationMention, ...]
    memory_kind: Classification
    model: str
    device: str
    schema_version: str


class MemoryExtractor(Protocol):
    def extract_many(self, texts: list[str]) -> tuple[MemoryExtraction, ...]: ...


@dataclass(frozen=True, slots=True)
class HTTPMemoryExtractor:
    base_url: str
    model_name: str
    threshold: float = 0.5
    timeout_s: float = 30.0

    def __post_init__(self) -> None:
        normalized_url = self.base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("memory extractor base URL must be non-empty")
        if not self.model_name.strip():
            raise ValueError("memory extractor model name must be non-empty")
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("memory extractor threshold must be finite and between zero and one")
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("memory extractor timeout must be a positive finite number")
        object.__setattr__(self, "base_url", normalized_url)

    def extract_many(self, texts: list[str]) -> tuple[MemoryExtraction, ...]:
        if not texts:
            return ()
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("memory extraction texts must be non-empty strings")
        chunks = [
            (text_index, offset, chunk)
            for text_index, text in enumerate(texts)
            for offset, chunk in _bounded_text_chunks(text)
        ]
        chunk_extractions: list[MemoryExtraction] = []
        for start in range(0, len(chunks), MAX_MEMORY_EXTRACTION_BATCH_TEXTS):
            batch = chunks[start : start + MAX_MEMORY_EXTRACTION_BATCH_TEXTS]
            chunk_extractions.extend(self._extract_provider_batch([chunk for _, _, chunk in batch]))
        return _merge_chunk_extractions(texts, chunks, chunk_extractions)

    def _extract_provider_batch(self, texts: list[str]) -> tuple[MemoryExtraction, ...]:
        payload = {
            "texts": texts,
            "threshold": self.threshold,
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        }
        request = Request(
            self.base_url + "/extract-memory",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(
                f"memory extraction provider HTTP {exc.code} at {self.base_url}"
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise RuntimeError(
                f"memory extraction provider unavailable at {self.base_url}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"memory extraction provider returned invalid JSON at {self.base_url}"
            ) from exc

        if not isinstance(decoded, dict):
            raise RuntimeError(
                f"memory extraction provider returned invalid JSON at {self.base_url}"
            )
        if decoded.get("model") != self.model_name:
            raise RuntimeError(f"memory extraction provider model mismatch at {self.base_url}")
        schema_version = decoded.get("schema_version")
        if schema_version != MEMORY_EXTRACTION_SCHEMA_VERSION:
            raise RuntimeError(f"memory extraction provider schema mismatch at {self.base_url}")
        device = decoded.get("device")
        if device not in {"cpu", "cuda"}:
            raise RuntimeError(f"memory extraction provider device is invalid at {self.base_url}")
        try:
            return normalize_memory_extractions(
                texts,
                decoded.get("results"),
                model=self.model_name,
                device=device,
                schema_version=schema_version,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"memory extraction provider returned invalid extraction results at {self.base_url}"
            ) from exc


def _bounded_text_chunks(text: str) -> tuple[tuple[int, str], ...]:
    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_MEMORY_EXTRACTION_TEXT_CHARS, len(text))
        if end < len(text):
            boundary = end
            while boundary > start and not text[boundary - 1].isspace():
                boundary -= 1
            if boundary > start + MAX_MEMORY_EXTRACTION_TEXT_CHARS // 2:
                end = boundary
        chunks.append((start, text[start:end]))
        start = end
    return tuple(chunks)


def _merge_chunk_extractions(
    texts: list[str],
    chunks: list[tuple[int, int, str]],
    extractions: list[MemoryExtraction],
) -> tuple[MemoryExtraction, ...]:
    if len(chunks) != len(extractions):
        raise RuntimeError("memory extraction chunk result count mismatch")
    grouped: list[list[tuple[int, MemoryExtraction]]] = [[] for _ in texts]
    for (text_index, offset, _), extraction in zip(chunks, extractions, strict=True):
        grouped[text_index].append((offset, extraction))

    merged: list[MemoryExtraction] = []
    for parts in grouped:
        devices = {extraction.device for _, extraction in parts}
        if len(devices) != 1:
            raise RuntimeError("memory extraction provider device changed between chunks")
        entity_candidates: list[EntityMention] = []
        relation_candidates: list[RelationMention] = []
        classifications: list[Classification] = []
        for offset, extraction in parts:
            shifted = {
                _entity_identity(entity): EntityMention(
                    entity.text,
                    entity.label,
                    entity.score,
                    entity.start + offset,
                    entity.end + offset,
                )
                for entity in extraction.entities
            }
            entity_candidates.extend(shifted.values())
            for relation in extraction.relations:
                relation_candidates.append(
                    RelationMention(
                        relation.relation,
                        shifted[_entity_identity(relation.subject)],
                        shifted[_entity_identity(relation.object)],
                        relation.score,
                    )
                )
            classifications.append(extraction.memory_kind)

        entity_index: dict[tuple[str, str, int, int], EntityMention] = {}
        for entity in entity_candidates:
            identity = _entity_identity(entity)
            previous = entity_index.get(identity)
            if previous is None or entity.score > previous.score:
                entity_index[identity] = entity
        relation_index: dict[
            tuple[str, tuple[str, str, int, int], tuple[str, str, int, int]],
            RelationMention,
        ] = {}
        for relation in relation_candidates:
            subject_identity = _entity_identity(relation.subject)
            object_identity = _entity_identity(relation.object)
            identity = (relation.relation, subject_identity, object_identity)
            canonical = RelationMention(
                relation.relation,
                entity_index[subject_identity],
                entity_index[object_identity],
                relation.score,
            )
            previous = relation_index.get(identity)
            if previous is None or canonical.score > previous.score:
                relation_index[identity] = canonical
        first = parts[0][1]
        merged.append(
            MemoryExtraction(
                entities=tuple(entity_index.values()),
                relations=tuple(relation_index.values()),
                memory_kind=max(classifications, key=lambda item: item.score),
                model=first.model,
                device=first.device,
                schema_version=first.schema_version,
            )
        )
    return tuple(merged)


def normalize_memory_extraction(
    text: str,
    raw: object,
    *,
    model: str,
    device: str,
    schema_version: str,
) -> MemoryExtraction:
    """Validate an extraction result while retaining exact source provenance."""
    if not isinstance(text, str) or not text:
        raise ValueError("source text must be non-empty")
    if not isinstance(raw, dict):
        raise ValueError("memory extraction result must be an object")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be non-empty")
    if not isinstance(device, str) or not device.strip():
        raise ValueError("device must be non-empty")
    if schema_version != MEMORY_EXTRACTION_SCHEMA_VERSION:
        raise ValueError("unsupported memory extraction schema version")

    raw_entities = _require_list(raw.get("entities"), "entities")
    entities = tuple(_normalize_entity(text, item) for item in raw_entities)
    entity_index = {_entity_identity(entity): entity for entity in entities}
    if len(entity_index) != len(entities):
        raise ValueError("duplicate entity provenance")

    raw_relations = _require_list(raw.get("relations"), "relations")
    relations = tuple(_normalize_relation(text, item, entity_index) for item in raw_relations)

    classifications = raw.get("classifications")
    if not isinstance(classifications, dict):
        raise ValueError("classifications must be an object")
    raw_memory_kinds = _require_list(
        classifications.get("memory_kind"), "classifications.memory_kind"
    )
    if not raw_memory_kinds:
        raise ValueError("classifications.memory_kind must not be empty")
    memory_kinds = tuple(_normalize_classification(item) for item in raw_memory_kinds)
    memory_kind = max(memory_kinds, key=lambda item: item.score)

    return MemoryExtraction(
        entities=entities,
        relations=relations,
        memory_kind=memory_kind,
        model=model,
        device=device,
        schema_version=schema_version,
    )


def normalize_memory_extractions(
    texts: list[str],
    raw_results: object,
    *,
    model: str,
    device: str,
    schema_version: str,
) -> tuple[MemoryExtraction, ...]:
    if not isinstance(raw_results, list):
        raise ValueError("memory extraction results must be a list")
    if len(raw_results) != len(texts):
        raise ValueError("model result count must match text count")
    return tuple(
        normalize_memory_extraction(
            text,
            raw,
            model=model,
            device=device,
            schema_version=schema_version,
        )
        for text, raw in zip(texts, raw_results, strict=True)
    )


def _normalize_entity(text: str, raw: object) -> EntityMention:
    if not isinstance(raw, dict):
        raise ValueError("entity must be an object")
    entity_text = _require_non_empty_string(raw.get("text"), "entity text")
    label = _require_non_empty_string(raw.get("label"), "entity label")
    score = _require_score(raw.get("score"), "entity score")
    start = _require_offset(raw.get("start"), "entity start")
    end = _require_offset(raw.get("end"), "entity end")
    if start >= end or end > len(text) or text[start:end] != entity_text:
        raise ValueError("entity span does not match source text")
    return EntityMention(entity_text, label, score, start, end)


def _normalize_relation(
    text: str,
    raw: object,
    entity_index: dict[tuple[str, str, int, int], EntityMention],
) -> RelationMention:
    if not isinstance(raw, dict):
        raise ValueError("relation must be an object")
    relation = _require_non_empty_string(raw.get("relation"), "relation label")
    score = _require_score(raw.get("score"), "relation score")
    raw_subject = _normalize_entity(text, raw.get("subject"))
    raw_object = _normalize_entity(text, raw.get("object"))
    try:
        subject = entity_index[_entity_identity(raw_subject)]
        object_ = entity_index[_entity_identity(raw_object)]
    except KeyError as exc:
        raise ValueError("relation endpoint must reference a declared entity") from exc
    return RelationMention(relation, subject, object_, score)


def _normalize_classification(raw: object) -> Classification:
    if not isinstance(raw, dict):
        raise ValueError("classification must be an object")
    return Classification(
        label=_require_non_empty_string(raw.get("label"), "classification label"),
        score=_require_score(raw.get("score"), "classification score"),
    )


def _entity_identity(entity: EntityMention) -> tuple[str, str, int, int]:
    return entity.text, entity.label, entity.start, entity.end


def _require_list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


def _require_score(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError(f"{name} must be finite and between zero and one")
    return score


def _require_offset(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value
