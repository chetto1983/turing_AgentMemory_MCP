from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from turing_agentmemory_mcp.provider_config import (
    api_key_header_value,
    provider_api_key_header,
    provider_api_key_scheme,
    provider_env,
    provider_optional_int,
    provider_secret,
)

MAX_RERANK_DOC_CHARS = 480
RRF_K = 60
T = TypeVar("T")


@dataclass(frozen=True)
class Scored:
    index: int
    score: float


@dataclass(frozen=True)
class OpenAICompatibleReranker:
    base_url: str = "http://127.0.0.1:8085"
    model: str = "local-rerank"
    api_key: str = ""
    api_key_header: str = "Authorization"
    api_key_scheme: str = "Bearer"
    dimensions: int | None = None
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> OpenAICompatibleReranker:
        return cls(
            base_url=provider_env("RERANK_BASE_URL", default="http://127.0.0.1:8085"),
            model=provider_env("RERANK_MODEL", default="local-rerank")
            or "local-rerank",
            api_key=provider_secret("RERANK"),
            api_key_header=provider_api_key_header("RERANK"),
            api_key_scheme=provider_api_key_scheme("RERANK"),
            dimensions=provider_optional_int("RERANK_DIMENSIONS"),
            timeout_s=float(provider_env("RERANK_TIMEOUT_SECONDS", default="30")),
        )

    def rerank(self, query: str, documents: list[str]) -> list[Scored]:
        if not documents:
            return []
        if not self.base_url.strip():
            return identity(documents)
        payload = {
            "model": self.model,
            "query": query,
            "documents": [truncate_runes(doc, MAX_RERANK_DOC_CHARS) for doc in documents],
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self.base_url.rstrip("/") + "/v1/rerank",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header(self.api_key_header, api_key_header_value(self.api_key, self.api_key_scheme))
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
    seed_scores: Sequence[float] | None = None,
    preserve_seed_margin: float = 0.0,
) -> list[tuple[T, float | None]]:
    if len(scored) != len(seed) or len(seed) < 2:
        return [(item, None) for item in seed]
    if blend:
        return blend_rerank_orders(seed, scored)
    if scored[0].score < threshold:
        return [(item, None) for item in seed]
    if should_preserve_top_seed(
        seed_len=len(seed),
        scored=scored,
        seed_scores=seed_scores,
        preserve_seed_margin=preserve_seed_margin,
    ):
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


def should_preserve_top_seed(
    *,
    seed_len: int,
    scored: list[Scored],
    seed_scores: Sequence[float] | None,
    preserve_seed_margin: float,
) -> bool:
    if preserve_seed_margin <= 0.0 or seed_scores is None or not scored:
        return False
    if len(seed_scores) != seed_len:
        return False
    rerank_top_index = scored[0].index
    if rerank_top_index <= 0 or rerank_top_index >= seed_len:
        return False
    return float(seed_scores[0]) - float(seed_scores[rerank_top_index]) >= preserve_seed_margin


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
