from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_RERANK_DOC_CHARS = 480
RRF_K = 60
T = TypeVar("T")


@dataclass(frozen=True)
class Scored:
    index: int
    score: float


@dataclass(frozen=True)
class AuraReranker:
    base_url: str = "http://127.0.0.1:8085"
    model: str = "aura-rerank"
    api_key: str = ""
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> AuraReranker:
        return cls(
            base_url=os.environ.get("AURA_RERANK_BASE_URL", "http://127.0.0.1:8085"),
            model=os.environ.get("AURA_RERANK_MODEL", "aura-rerank") or "aura-rerank",
            api_key=os.environ.get("AURA_RERANK_API_KEY", ""),
            timeout_s=float(os.environ.get("AURA_RERANK_TIMEOUT_SECONDS", "30")),
        )

    def rerank(self, query: str, documents: list[str]) -> list[Scored]:
        if not documents:
            return []
        if not self.base_url.strip():
            return identity(documents)
        body = json.dumps(
            {
                "model": self.model,
                "query": query,
                "documents": [truncate_runes(doc, MAX_RERANK_DOC_CHARS) for doc in documents],
            }
        ).encode("utf-8")
        req = Request(
            self.base_url.rstrip("/") + "/v1/rerank",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urlopen(req, timeout=self.timeout_s) as resp:
                decoded = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError, TimeoutError, OSError):
            return identity(documents)
        results = decoded.get("results") or []
        if len(results) != len(documents):
            return identity(documents)
        scored: list[Scored] = []
        for row in results:
            index = int(row.get("index", -1))
            if index < 0 or index >= len(documents):
                return identity(documents)
            scored.append(Scored(index=index, score=float(row.get("relevance_score", 0.0))))
        return sorted(scored, key=lambda item: item.score, reverse=True)


def identity(documents: list[str]) -> list[Scored]:
    return [Scored(index=index, score=0.0) for index in range(len(documents))]


def apply_rerank_guard(
    seed: list[T],
    scored: list[Scored],
    *,
    threshold: float = 0.0,
    blend: bool = False,
) -> list[tuple[T, float | None]]:
    if len(scored) != len(seed) or len(seed) < 2:
        return [(item, None) for item in seed]
    if blend:
        return blend_rerank_orders(seed, scored)
    if scored[0].score < threshold:
        return [(item, None) for item in seed]
    reordered: list[tuple[T, float | None]] = []
    changed = False
    for rank, item in enumerate(scored):
        if item.index < 0 or item.index >= len(seed):
            return [(value, None) for value in seed]
        if item.index != rank:
            changed = True
        reordered.append((seed[item.index], item.score))
    if not changed:
        return [(item, None) for item in seed]
    return reordered


def blend_rerank_orders(seed: list[T], scored: list[Scored]) -> list[tuple[T, float | None]]:
    rerank_rank = [0] * len(seed)
    for rank, item in enumerate(scored):
        if item.index < 0 or item.index >= len(seed):
            return [(value, None) for value in seed]
        rerank_rank[item.index] = rank
    ranked = [
        (idx, seed_item, 1.0 / float(RRF_K + idx) + 1.0 / float(RRF_K + rerank_rank[idx]))
        for idx, seed_item in enumerate(seed)
    ]
    ranked.sort(key=lambda item: (-item[2], item[0]))
    return [(item, score) for _, item, score in ranked]


def truncate_runes(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]
