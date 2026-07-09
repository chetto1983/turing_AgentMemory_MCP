from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
