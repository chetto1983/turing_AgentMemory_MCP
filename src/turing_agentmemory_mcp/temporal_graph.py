"""Deterministic temporal graph projection from grounded memory extraction."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from .ids import stable_id
from .memory_extraction import EntityMention, MemoryExtraction

_WHITESPACE_RE = re.compile(r"\s+")
_IDENTIFIER_RE = re.compile(r"[^a-z0-9_]+")
_YEAR_RE = re.compile(r"^(\d{4})$")


@dataclass(frozen=True, slots=True)
class EpisodeContext:
    user_identifier: str
    memory_id: str
    content: str
    session_id: str
    role: str
    observed_at: str
    source: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    expires_at: str = ""

    def __post_init__(self) -> None:
        for name in ("user_identifier", "memory_id", "content", "session_id", "role"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"episode {name} must be non-empty")
        object.__setattr__(
            self, "observed_at", _normalize_timestamp(self.observed_at, "observed_at")
        )
        if self.expires_at:
            object.__setattr__(
                self,
                "expires_at",
                _normalize_timestamp(self.expires_at, "expires_at"),
            )
        if any(not isinstance(tag, str) or not tag.strip() for tag in self.tags):
            raise ValueError("episode tags must be non-empty strings")
        object.__setattr__(self, "tags", tuple(dict.fromkeys(tag.strip() for tag in self.tags)))
        if not isinstance(self.metadata, dict):
            raise ValueError("episode metadata must be an object")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class EntityProjection:
    id: str
    user_identifier: str
    entity_type: str
    canonical_name: str
    display_name: str
    content: str
    confidence: float
    observed_at: str
    source_memory_id: str
    schema_version: str
    model: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class FactProjection:
    id: str
    user_identifier: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    content: str
    confidence: float
    observed_at: str
    valid_from: str
    valid_to: str
    valid_time_precision: str
    source_memory_id: str
    session_id: str
    speaker: str
    source: str
    tags: tuple[str, ...]
    metadata: dict[str, object]
    schema_version: str
    model: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class MentionProjection:
    id: str
    episode_id: str
    entity_id: str
    start: int
    end: int
    score: float


@dataclass(frozen=True, slots=True)
class EdgeProjection:
    id: str
    source_id: str
    target_id: str
    kind: str
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TemporalProjection:
    entities: tuple[EntityProjection, ...]
    facts: tuple[FactProjection, ...]
    mentions: tuple[MentionProjection, ...]
    edges: tuple[EdgeProjection, ...]


def plan_temporal_projection(
    episode: EpisodeContext,
    extraction: MemoryExtraction,
) -> TemporalProjection:
    """Build a deterministic, side-effect-free projection for one evidence episode."""
    canonical_by_key: dict[tuple[str, str], EntityProjection] = {}
    entity_id_by_mention: dict[tuple[str, str, int, int], str] = {}
    mentions: list[MentionProjection] = []
    mention_edges: list[EdgeProjection] = []

    for mention in extraction.entities:
        _validate_mention_against_episode(mention, episode.content)
        entity_type = _normalize_identifier(mention.label)
        canonical_name = canonicalize_entity_name(mention.text)
        key = entity_type, canonical_name
        entity = canonical_by_key.get(key)
        if entity is None:
            entity_id = stable_id("ent", episode.user_identifier, entity_type, canonical_name)
            entity = EntityProjection(
                id=entity_id,
                user_identifier=episode.user_identifier,
                entity_type=entity_type,
                canonical_name=canonical_name,
                display_name=mention.text,
                content=f"{mention.text} ({entity_type})",
                confidence=mention.score,
                observed_at=episode.observed_at,
                source_memory_id=episode.memory_id,
                schema_version=extraction.schema_version,
                model=extraction.model,
                expires_at=episode.expires_at,
            )
            canonical_by_key[key] = entity
        elif mention.score > entity.confidence:
            entity = replace(
                entity,
                display_name=mention.text,
                content=f"{mention.text} ({entity_type})",
                confidence=mention.score,
            )
            canonical_by_key[key] = entity
        identity = _mention_identity(mention)
        entity_id_by_mention[identity] = entity.id
        mention_id = stable_id(
            "mention",
            episode.user_identifier,
            episode.memory_id,
            entity.id,
            str(mention.start),
            str(mention.end),
        )
        mention_plan = MentionProjection(
            id=mention_id,
            episode_id=episode.memory_id,
            entity_id=entity.id,
            start=mention.start,
            end=mention.end,
            score=mention.score,
        )
        mentions.append(mention_plan)
        mention_edges.append(
            EdgeProjection(
                id=stable_id("edge", mention_id, "MENTIONS"),
                source_id=episode.memory_id,
                target_id=entity.id,
                kind="MENTIONS",
                properties={
                    "mention_id": mention_id,
                    "start": mention.start,
                    "end": mention.end,
                    "score": mention.score,
                    "schema_version": extraction.schema_version,
                    "model": extraction.model,
                },
            )
        )

    facts_by_id: dict[str, FactProjection] = {}
    for relation in extraction.relations:
        predicate = _normalize_identifier(relation.relation)
        subject_id = _entity_id_for_endpoint(relation.subject, entity_id_by_mention)
        object_id = _entity_id_for_endpoint(relation.object, entity_id_by_mention)
        valid_from, precision = (
            normalize_date_expression(relation.object.text)
            if _normalize_identifier(relation.object.label) in {"date", "time"}
            else ("", "")
        )
        fact_id = stable_id(
            "fact",
            episode.user_identifier,
            episode.memory_id,
            subject_id,
            predicate,
            object_id,
        )
        fact = FactProjection(
            id=fact_id,
            user_identifier=episode.user_identifier,
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            content=f"{relation.subject.text} {predicate.replace('_', ' ')} {relation.object.text}",
            confidence=relation.score,
            observed_at=episode.observed_at,
            valid_from=valid_from,
            valid_to="",
            valid_time_precision=precision,
            source_memory_id=episode.memory_id,
            session_id=episode.session_id,
            speaker=episode.role,
            source=episode.source,
            tags=episode.tags,
            metadata=dict(episode.metadata),
            schema_version=extraction.schema_version,
            model=extraction.model,
            expires_at=episode.expires_at,
        )
        previous = facts_by_id.get(fact_id)
        if previous is None or fact.confidence > previous.confidence:
            facts_by_id[fact_id] = fact

    facts = [facts_by_id[fact_id] for fact_id in sorted(facts_by_id)]
    fact_edges: list[EdgeProjection] = []
    for fact in facts:
        shared = {
            "fact_id": fact.id,
            "confidence": fact.confidence,
            "source_memory_id": episode.memory_id,
            "observed_at": episode.observed_at,
        }
        fact_edges.extend(
            (
                _edge(fact.subject_entity_id, fact.id, "SUBJECT_OF", shared),
                _edge(fact.object_entity_id, fact.id, "OBJECT_OF", shared),
                _edge(fact.id, episode.memory_id, "SUPPORTED_BY", shared),
                _edge(
                    fact.subject_entity_id,
                    fact.object_entity_id,
                    fact.predicate.upper(),
                    shared,
                ),
            )
        )

    return TemporalProjection(
        entities=tuple(canonical_by_key.values()),
        facts=tuple(facts),
        mentions=tuple(mentions),
        edges=tuple(mention_edges + fact_edges),
    )


def canonicalize_entity_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip().casefold()
    if not normalized:
        raise ValueError("entity name must be non-empty")
    return normalized


def canonicalize_entity_type(value: str) -> str:
    return _normalize_identifier(value)


def normalize_date_expression(value: str) -> tuple[str, str]:
    """Normalize explicit absolute dates while retaining their source precision."""
    normalized = _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip()
    if not normalized:
        return "", ""
    year_match = _YEAR_RE.fullmatch(normalized)
    if year_match:
        return year_match.group(1), "year"
    for pattern in ("%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(normalized, pattern)
        except ValueError:
            continue
        return parsed.strftime("%Y-%m"), "month"
    try:
        return date.fromisoformat(normalized).isoformat(), "day"
    except ValueError:
        pass
    for pattern in (
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            parsed = datetime.strptime(normalized, pattern)
        except ValueError:
            continue
        return parsed.date().isoformat(), "day"
    return "", ""


def _edge(
    source_id: str,
    target_id: str,
    kind: str,
    properties: dict[str, object],
) -> EdgeProjection:
    return EdgeProjection(
        id=stable_id("edge", source_id, kind, target_id, str(properties.get("fact_id", ""))),
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        properties=dict(properties),
    )


def _normalize_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold().replace("-", "_")
    normalized = _IDENTIFIER_RE.sub("_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise ValueError("graph identifier must be non-empty")
    return normalized


def _mention_identity(mention: EntityMention) -> tuple[str, str, int, int]:
    return mention.text, mention.label, mention.start, mention.end


def _entity_id_for_endpoint(
    mention: EntityMention,
    entity_id_by_mention: dict[tuple[str, str, int, int], str],
) -> str:
    try:
        return entity_id_by_mention[_mention_identity(mention)]
    except KeyError as exc:
        raise ValueError("relation endpoint does not reference an extracted entity") from exc


def _validate_mention_against_episode(mention: EntityMention, content: str) -> None:
    if mention.start < 0 or mention.end > len(content) or mention.start >= mention.end:
        raise ValueError("entity mention span is outside episode content")
    if content[mention.start : mention.end] != mention.text:
        raise ValueError("entity mention span does not match episode content")


def _normalize_timestamp(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"episode {name} must be non-empty")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"episode {name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
