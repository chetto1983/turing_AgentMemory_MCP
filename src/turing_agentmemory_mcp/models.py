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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentHit:
    chunk_id: str
    document_id: str
    title: str
    locator: str
    text: str
    score: float
    context: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IngestedDocument:
    document_id: str
    title: str
    chunk_count: int
    user_identifier: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
