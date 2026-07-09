from __future__ import annotations

import hashlib
import re

SAFE_RE = re.compile(r"[^a-zA-Z0-9_]+")


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts)
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()
    return f"{prefix}_{digest}"


def vector_id(namespace: str, identifier: str) -> int:
    payload = f"{namespace}:{identifier}".encode()
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") % 2_000_000_000 + 1


def cypher_var(identifier: str) -> str:
    value = SAFE_RE.sub("_", identifier)
    value = value.strip("_") or "node"
    if value[0].isdigit():
        value = f"n_{value}"
    return value[:80]


def quote(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
