from __future__ import annotations

import hashlib
import re

SAFE_RE = re.compile(r"[^a-zA-Z0-9_]+")


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts)
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()
    return f"{prefix}_{digest}"


def cypher_var(identifier: str) -> str:
    value = SAFE_RE.sub("_", identifier)
    value = value.strip("_") or "node"
    if value[0].isdigit():
        value = f"n_{value}"
    return value[:80]
