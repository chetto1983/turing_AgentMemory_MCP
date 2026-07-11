from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RetrievalCandidate:
    candidate_id: str
    kind: str
    content: str
    source_memory_id: str = ""
    evidence_source_ids: tuple[str, ...] = ()
    raw_score: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalEvidence:
    source_memory_id: str
    evidence_id: str
    evidence_kind: str
    raw_score: float
    hop: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FusionChannelScore:
    rank: int
    raw_score: float | None
    weight: float
    contribution: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FusedRetrievalCandidate:
    candidate: RetrievalCandidate
    score: float
    best_rank: int
    channels: dict[str, FusionChannelScore] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "score": self.score,
            "best_rank": self.best_rank,
            "channels": {
                channel: detail.to_dict() for channel, detail in self.channels.items()
            },
        }


@dataclass(frozen=True)
class MemoryItem:
    id: str
    user_identifier: str
    kind: str
    content: str
    score: float
    session_id: str = ""
    role: str = ""
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    score_details: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        if self.score_details is None:
            value.pop("score_details", None)
        return value


@dataclass(frozen=True)
class DocumentHit:
    chunk_id: str
    document_id: str
    title: str
    locator: str
    text: str
    score: float
    context: list[dict[str, object]] = field(default_factory=list)
    expires_at: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    score_details: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        if self.score_details is None:
            value.pop("score_details", None)
        return value


@dataclass(frozen=True)
class IngestedDocument:
    document_id: str
    title: str
    chunk_count: int
    user_identifier: str
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    text_hash: str = ""
    chunk_chars: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
