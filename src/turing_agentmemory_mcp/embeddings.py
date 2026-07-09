from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from turing_agentmemory_mcp.provider_config import (
    api_key_header_value,
    provider_api_key_header,
    provider_api_key_scheme,
    provider_env,
    provider_secret,
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
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.base_url.strip():
            raise ValueError("EMBED_BASE_URL is required")
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = Request(
            self.base_url.rstrip("/") + "/v1/embeddings",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header(self.api_key_header, api_key_header_value(self.api_key, self.api_key_scheme))
        try:
            with urlopen(req, timeout=self.timeout_s) as resp:
                decoded = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"embedding provider HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"embedding provider unavailable at {self.base_url}: {exc.reason}") from exc
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
