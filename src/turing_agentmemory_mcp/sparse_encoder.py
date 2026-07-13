"""Shared BOTH-channels sparse lexical encoder (04-05).

Promoted verbatim from the D-04 spike's winning `_sparse_vector`
(`scripts/arcadedb_spike.py`) into a reusable `src/` module per the user's
both-channels lexical decision (`.planning/phases/04-arcadedb-direct-port/
04-EXECUTION-STATE.md`): every content-bearing vertex (Memory/Entity/Fact/
Community/Chunk) carries TWO independent lexical channels alongside its dense
`embedding` (04-03's schema bootstrap) -- the raw text property (`content`, or
`text` for Chunk) is auto-indexed by ArcadeDB's native Lucene `FULL_TEXT`
channel with no Python-side encoding step, and `lexical_tokens`/
`lexical_weights` feed the native `LSM_SPARSE_VECTOR` channel via
`sparse_vector()` below.

Write-side (04-05/06/08) and query-side (04-07) callers MUST import this
exact function -- never re-derive a second tokenizer -- or the two sides
silently diverge and sparse retrieval degrades; byte-identical tokenization
is the entire point of promoting this out of the throwaway spike script.
`idf` defaults to raw term-frequency weighting (every token weight 1.0):
this milestone does not maintain a live corpus-wide document-frequency
table, so a future wave that wants real IDF must compute one explicitly and
pass it in here, reusing this exact `token_id`/`VOCAB_SIZE` bucketing rather
than inventing a second scheme.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter

VOCAB_SIZE = 4096

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
    return _NON_WORD_RE.sub(" ", text).strip()


def normalized_tokens(value: object) -> list[str]:
    normalized = normalize_text(value)
    return normalized.split(" ") if normalized else []


def token_id(token: str, vocab_size: int = VOCAB_SIZE) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % vocab_size


def sparse_vector(text: str, idf: dict[str, float] | None = None) -> tuple[list[int], list[float]]:
    """blake2b hash-bucketed TF(-IDF) sparse vector.

    Returns `(tokens, weights)` -- ArcadeDB's `LSM_SPARSE_VECTOR` property
    pair (`lexical_tokens`, `lexical_weights`). Tokenizer and bucketing are
    unchanged from the D-04 spike bake-off's winning channel.
    """
    weights = idf or {}
    counts = Counter(normalized_tokens(text))
    by_bucket: dict[int, float] = {}
    for token, count in counts.items():
        bucket = token_id(token, VOCAB_SIZE)
        weight = count * weights.get(token, 1.0)
        by_bucket[bucket] = by_bucket.get(bucket, 0.0) + weight
    if not by_bucket:
        return [], []
    buckets = sorted(by_bucket)
    return buckets, [by_bucket[bucket] for bucket in buckets]
