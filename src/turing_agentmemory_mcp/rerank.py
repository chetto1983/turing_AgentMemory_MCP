from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from turing_agentmemory_mcp.provider_config import (
    api_key_header_value,
    provider_api_key_header,
    provider_api_key_scheme,
    provider_env,
    provider_error_code,
    provider_optional_int,
    provider_secret,
    retryable_provider_code,
)

DEFAULT_MAX_RERANK_DOCUMENT_CHARS = 2048
DEFAULT_MAX_RERANK_TOTAL_BYTES = 32768
DEFAULT_MAX_RERANK_ESTIMATED_TOKENS = 8192
DEFAULT_RERANK_CHARS_PER_TOKEN = 4.0
RRF_K = 60
T = TypeVar("T")


@dataclass(frozen=True)
class Scored:
    index: int
    score: float


@dataclass(frozen=True)
class RerankLimits:
    max_document_chars: int = DEFAULT_MAX_RERANK_DOCUMENT_CHARS
    max_total_bytes: int = DEFAULT_MAX_RERANK_TOTAL_BYTES
    max_estimated_tokens: int = DEFAULT_MAX_RERANK_ESTIMATED_TOKENS
    chars_per_token: float = DEFAULT_RERANK_CHARS_PER_TOKEN

    def __post_init__(self) -> None:
        for name in (
            "max_document_chars",
            "max_total_bytes",
            "max_estimated_tokens",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.chars_per_token, bool)
            or not isinstance(self.chars_per_token, (int, float))
            or not math.isfinite(float(self.chars_per_token))
            or float(self.chars_per_token) <= 0
        ):
            raise ValueError("chars_per_token must be a positive finite number")


@dataclass(frozen=True)
class RerankResult:
    scores: list[Scored]
    status: str
    model: str
    document_count: int = 0
    wire_bytes: int = 0
    estimated_tokens: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model": self.model,
            "document_count": self.document_count,
            "wire_bytes": self.wire_bytes,
            "estimated_tokens": self.estimated_tokens,
        }


@dataclass(frozen=True)
class OpenAICompatibleReranker:
    base_url: str = "http://127.0.0.1:8085"
    model: str = "local-rerank"
    api_key: str = ""
    api_key_header: str = "Authorization"
    api_key_scheme: str = "Bearer"
    dimensions: int | None = None
    timeout_s: float = 30.0
    provider_min_score: float = 0.0
    max_attempts: int = 3
    retry_base_s: float = 0.5
    limits: RerankLimits = RerankLimits()

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
            raise ValueError("rerank max attempts must be positive")
        if self.retry_base_s < 0:
            raise ValueError("rerank retry base seconds must not be negative")

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
            provider_min_score=max(0.0, float(provider_env("RERANK_PROVIDER_MIN_SCORE", default="0"))),
            max_attempts=int(provider_env("RERANK_MAX_ATTEMPTS", default="3")),
            retry_base_s=float(provider_env("RERANK_RETRY_BASE_SECONDS", default="0.5")),
            limits=RerankLimits(
                max_document_chars=int(
                    provider_env(
                        "RERANK_MAX_DOCUMENT_CHARS",
                        default=str(DEFAULT_MAX_RERANK_DOCUMENT_CHARS),
                    )
                ),
                max_total_bytes=int(
                    provider_env(
                        "RERANK_MAX_TOTAL_BYTES",
                        default=str(DEFAULT_MAX_RERANK_TOTAL_BYTES),
                    )
                ),
                max_estimated_tokens=int(
                    provider_env(
                        "RERANK_MAX_ESTIMATED_TOKENS",
                        default=str(DEFAULT_MAX_RERANK_ESTIMATED_TOKENS),
                    )
                ),
                chars_per_token=float(
                    provider_env(
                        "RERANK_CHARS_PER_TOKEN",
                        default=str(DEFAULT_RERANK_CHARS_PER_TOKEN),
                    )
                ),
            ),
        )

    def rerank(self, query: str, documents: list[str]) -> list[Scored]:
        return self.rerank_with_status(query, documents).scores

    def rerank_with_status(self, query: str, documents: list[str]) -> RerankResult:
        if not documents:
            return RerankResult([], "empty", self.model)
        if not self.base_url.strip():
            return self._result(identity(documents), "disabled", documents)
        bounded_documents = bound_rerank_documents(documents, self.limits)
        payload = {
            "model": self.model,
            "query": query,
            "documents": bounded_documents,
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
        decoded: object = None
        for attempt in range(self.max_attempts):
            try:
                with urlopen(req, timeout=self.timeout_s) as resp:
                    decoded = json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                if retryable_provider_code(exc.code) and attempt + 1 < self.max_attempts:
                    time.sleep(self.retry_base_s * (2**attempt))
                    continue
                return self._result(identity(documents), "provider_error", bounded_documents)
            except (URLError, json.JSONDecodeError, TimeoutError, OSError):
                return self._result(identity(documents), "provider_error", bounded_documents)
            error_code = provider_error_code(decoded)
            if error_code and retryable_provider_code(error_code) and attempt + 1 < self.max_attempts:
                time.sleep(self.retry_base_s * (2**attempt))
                continue
            if error_code:
                return self._result(identity(documents), "provider_error", bounded_documents)
            break
        if not isinstance(decoded, dict):
            return self._result(identity(documents), "invalid_response", bounded_documents)
        results = decoded.get("results")
        if not isinstance(results, list) or len(results) != len(documents):
            return self._result(identity(documents), "invalid_response", bounded_documents)
        scored: list[Scored] = []
        seen_indices: set[int] = set()
        for row in results:
            if not isinstance(row, dict):
                return self._result(identity(documents), "invalid_response", bounded_documents)
            raw_index = row.get("index")
            raw_score = row.get("relevance_score")
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                return self._result(identity(documents), "invalid_response", bounded_documents)
            if raw_index < 0 or raw_index >= len(documents) or raw_index in seen_indices:
                return self._result(identity(documents), "invalid_response", bounded_documents)
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                return self._result(identity(documents), "invalid_response", bounded_documents)
            score = float(raw_score)
            if not math.isfinite(score):
                return self._result(identity(documents), "invalid_response", bounded_documents)
            seen_indices.add(raw_index)
            scored.append(Scored(index=raw_index, score=score))
        ordered = sorted(scored, key=lambda item: item.score, reverse=True)
        if self.provider_min_score > 0.0 and ordered[0].score < self.provider_min_score:
            return self._result(
                lexical_rerank(query, bounded_documents),
                "provider_floor_fallback",
                bounded_documents,
            )
        return self._result(ordered, "applied", bounded_documents)

    def _result(
        self,
        scores: list[Scored],
        status: str,
        documents: list[str],
    ) -> RerankResult:
        total_chars = sum(len(document) for document in documents)
        return RerankResult(
            scores=scores,
            status=status,
            model=self.model,
            document_count=len(documents),
            wire_bytes=sum(len(document.encode("utf-8")) for document in documents),
            estimated_tokens=math.ceil(total_chars / self.limits.chars_per_token),
        )


def identity(documents: list[str]) -> list[Scored]:
    return [Scored(index=index, score=0.0) for index in range(len(documents))]


def lexical_rerank(query: str, documents: list[str]) -> list[Scored]:
    query_terms = _terms(query)
    if not query_terms:
        return identity(documents)
    query_set = set(query_terms)
    query_norm = _normalize_text(query)
    scored: list[Scored] = []
    for index, document in enumerate(documents):
        doc_terms = set(_terms(document))
        overlap = len(query_set & doc_terms)
        score = float(overlap) / float(len(query_set))
        if query_norm and query_norm in _normalize_text(document):
            score += 1.0
        scored.append(Scored(index=index, score=score))
    return sorted(scored, key=lambda item: (-item.score, item.index))


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


def assemble_rerank_document(
    *,
    content: str,
    provenance: Mapping[str, object],
) -> str:
    preferred = (
        "memory_id",
        "kind",
        "source",
        "session_id",
        "role",
        "created_at",
        "updated_at",
        "path",
        "locator",
        "conversation_id",
        "evidence_ids",
    )
    keys = [key for key in preferred if key in provenance]
    keys.extend(sorted(key for key in provenance if key not in preferred))
    lines = ["[provenance]"]
    for key in keys:
        value = provenance[key]
        if value is None or value == "" or value == [] or value == ():
            continue
        if isinstance(value, (list, tuple, set)):
            rendered = ", ".join(_one_line(str(item)) for item in value)
        else:
            rendered = _one_line(str(value))
        lines.append(f"{key}: {rendered}")
    lines.append("[/provenance]")
    lines.append(content)
    return "\n".join(lines)


def bound_rerank_documents(
    documents: Sequence[str],
    limits: RerankLimits,
) -> list[str]:
    remaining_bytes = limits.max_total_bytes
    remaining_chars = math.floor(
        limits.max_estimated_tokens * limits.chars_per_token
    )
    bounded: list[str] = []
    for index, document in enumerate(documents):
        remaining_documents = len(documents) - index
        char_share = remaining_chars // remaining_documents
        byte_share = remaining_bytes // remaining_documents
        char_limit = max(0, min(limits.max_document_chars, char_share))
        value = truncate_runes(document, char_limit)
        value = _truncate_utf8(value, max(0, byte_share))
        bounded.append(value)
        remaining_chars -= len(value)
        remaining_bytes -= len(value.encode("utf-8"))
    return bounded


def _truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    if len(value.encode("utf-8")) <= max_bytes:
        return value
    low = 0
    high = len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if len(value[:middle].encode("utf-8")) <= max_bytes:
            low = middle
        else:
            high = middle - 1
    return value[:low]


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _terms(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    terms: list[str] = []
    for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE):
        if token and all(_is_cjk(char) for char in token):
            terms.extend(token)
        else:
            terms.append(token)
    return terms


def _normalize_text(value: str) -> str:
    return " ".join(_terms(value))


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )
