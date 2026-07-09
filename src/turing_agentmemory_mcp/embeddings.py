from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
class AuraLlamaEmbedder:
    """OpenAI-compatible client for Aura's local aura-llama-embed sidecar."""

    base_url: str = "http://127.0.0.1:8081"
    dimensions: int = 768
    model: str = "aura-local-embedding"
    api_key: str = ""
    timeout_s: float = 60.0

    @classmethod
    def from_env(cls, *, dimensions: int | None = None) -> AuraLlamaEmbedder:
        configured_dimensions = dimensions or int(os.environ.get("AURA_EMBED_DIMENSIONS", "768"))
        return cls(
            base_url=os.environ.get("AURA_EMBED_BASE_URL", "http://127.0.0.1:8081"),
            dimensions=configured_dimensions,
            model=os.environ.get("AURA_EMBED_MODEL", "aura-local-embedding") or "aura-local-embedding",
            api_key=os.environ.get("AURA_EMBED_API_KEY", ""),
            timeout_s=float(os.environ.get("AURA_EMBED_TIMEOUT_SECONDS", "60")),
        )

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.base_url.strip():
            raise ValueError("AURA_EMBED_BASE_URL is required")
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = Request(
            self.base_url.rstrip("/") + "/v1/embeddings",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urlopen(req, timeout=self.timeout_s) as resp:
                decoded = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"aura-llama-embed HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"aura-llama-embed unavailable at {self.base_url}: {exc.reason}") from exc
        rows = decoded.get("data") or []
        if len(rows) != len(texts):
            raise RuntimeError(
                f"aura-llama-embed returned {len(rows)} embeddings for {len(texts)} inputs"
            )
        vectors: list[list[float]] = []
        for idx, row in enumerate(rows):
            vector = [float(value) for value in row.get("embedding") or []]
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"aura-llama-embed vector {idx} has dimension {len(vector)}, "
                    f"want {self.dimensions}"
                )
            vectors.append(vector)
        return vectors
