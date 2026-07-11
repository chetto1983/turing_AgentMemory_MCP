from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Protocol
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

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


class Embedder(Protocol):
    dimensions: int

    def embed(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class HashingEmbedder:
    dimensions: int = 64

    def embed(self, text: str) -> list[float]:
        if self.dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        vec = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [value / norm for value in vec]


@dataclass(frozen=True)
class OpenAICompatibleEmbedder:
    """OpenAI-compatible HTTP client for an embedding provider."""

    base_url: str = "http://127.0.0.1:8081"
    dimensions: int = 768
    model: str = "local-embedding"
    api_key: str = ""
    api_key_header: str = "Authorization"
    api_key_scheme: str = "Bearer"
    timeout_s: float = 60.0
    batch_size: int = 128
    request_dimensions: int | None = None
    max_attempts: int = 3
    retry_base_s: float = 0.5
    query_prefix: str = ""
    document_prefix: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int):
            raise ValueError("embedding batch size must be an integer")
        if self.batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        if self.request_dimensions is not None and self.request_dimensions != self.dimensions:
            raise ValueError("embedding request dimensions must match store dimensions")
        if isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
            raise ValueError("embedding max attempts must be positive")
        if self.retry_base_s < 0:
            raise ValueError("embedding retry base seconds must not be negative")

    @classmethod
    def from_env(cls, *, dimensions: int | None = None) -> OpenAICompatibleEmbedder:
        configured_dimensions = dimensions or int(provider_env("EMBED_DIMENSIONS", default="768"))
        return cls(
            base_url=provider_env("EMBED_BASE_URL", default="http://127.0.0.1:8081"),
            dimensions=configured_dimensions,
            model=provider_env("EMBED_MODEL", default="local-embedding")
            or "local-embedding",
            api_key=provider_secret("EMBED"),
            api_key_header=provider_api_key_header("EMBED"),
            api_key_scheme=provider_api_key_scheme("EMBED"),
            timeout_s=float(provider_env("EMBED_TIMEOUT_SECONDS", default="60")),
            batch_size=int(provider_env("EMBED_BATCH_SIZE", default="128")),
            request_dimensions=provider_optional_int("EMBED_REQUEST_DIMENSIONS"),
            max_attempts=int(provider_env("EMBED_MAX_ATTEMPTS", default="3")),
            retry_base_s=float(provider_env("EMBED_RETRY_BASE_SECONDS", default="0.5")),
            query_prefix=provider_env("EMBED_QUERY_PREFIX"),
            document_prefix=provider_env("EMBED_DOCUMENT_PREFIX"),
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_many([f"{self.query_prefix}{text}"])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_many([f"{self.document_prefix}{text}" for text in texts])

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.base_url.strip():
            raise ValueError("EMBED_BASE_URL is required")
        payload: dict[str, object] = {"model": self.model, "input": texts}
        if self.request_dimensions is not None:
            payload["dimensions"] = self.request_dimensions
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self.base_url.rstrip("/") + "/v1/embeddings",
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
                raise RuntimeError(f"embedding provider HTTP {exc.code}") from exc
            except URLError as exc:
                raise RuntimeError(
                    f"embedding provider unavailable at {self.base_url}: {exc.reason}"
                ) from exc
            error_code = provider_error_code(decoded)
            if error_code and retryable_provider_code(error_code) and attempt + 1 < self.max_attempts:
                time.sleep(self.retry_base_s * (2**attempt))
                continue
            if error_code:
                raise RuntimeError(f"embedding provider error {error_code}")
            break
        if not isinstance(decoded, dict):
            raise RuntimeError("embedding provider returned an invalid response")
        rows = decoded.get("data") or []
        if len(rows) != len(texts):
            raise RuntimeError(
                f"embedding provider returned {len(rows)} embeddings for {len(texts)} inputs"
            )
        vectors: list[list[float]] = []
        for idx, row in enumerate(rows):
            vector = [float(value) for value in row.get("embedding") or []]
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"embedding provider vector {idx} has dimension {len(vector)}, "
                    f"want {self.dimensions}"
                )
            vectors.append(vector)
        return vectors
