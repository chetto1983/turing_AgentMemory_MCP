from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:/\\.#-]*")
SPLIT_RE = re.compile(r"[:/\\._#-]+")
PATH_SPLIT_RE = re.compile(r"[:/\\]+")

SEMANTIC_WEIGHT = 0.55
LEXICAL_WEIGHT = 0.45


@dataclass(frozen=True)
class HybridRanked:
    candidate_id: str
    semantic_score: float
    lexical_score: float
    final_score: float
    text: str


def lexical_score(query: str, text: str) -> float:
    query_tokens = expanded_tokens(query)
    if not query_tokens:
        return 0.0
    text_tokens = set(expanded_tokens(text))
    if not text_tokens:
        return 0.0

    query_set = set(query_tokens)
    overlap = query_set & text_tokens
    coverage = len(overlap) / len(query_set)

    special = {token for token in query_set if is_special_token(token)}
    special_coverage = len(special & text_tokens) / len(special) if special else coverage

    normalized_query = normalize_text(query)
    normalized_text = normalize_text(text)
    phrase_score = 1.0 if normalized_query and normalized_query in normalized_text else 0.0

    score = (coverage * 0.55) + (special_coverage * 0.35) + (phrase_score * 0.10)
    return round(min(score, 1.0), 6)


def blend_hybrid_score(*, semantic_score: float, lexical_score: float) -> float:
    semantic = clamp_score(semantic_score)
    lexical = clamp_score(lexical_score)
    return round(min((semantic * SEMANTIC_WEIGHT) + (lexical * LEXICAL_WEIGHT), 1.0), 6)


def rank_hybrid(query: str, candidates: list[tuple[str, float, str]]) -> list[HybridRanked]:
    ranked = [
        HybridRanked(
            candidate_id=candidate_id,
            semantic_score=clamp_score(semantic_score),
            lexical_score=lexical_score(query, text),
            final_score=blend_hybrid_score(
                semantic_score=semantic_score,
                lexical_score=lexical_score(query, text),
            ),
            text=text,
        )
        for candidate_id, semantic_score, text in candidates
    ]
    ranked.sort(
        key=lambda item: (
            -item.final_score,
            -item.lexical_score,
            -item.semantic_score,
            item.candidate_id,
        )
    )
    return ranked


def expanded_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_RE.findall(value):
        token = normalize_token(match)
        add_token(tokens, seen, token)
        for segment in PATH_SPLIT_RE.split(token):
            add_token(tokens, seen, segment)
        for part in SPLIT_RE.split(token):
            add_token(tokens, seen, part)
    return tokens


def normalize_text(value: str) -> str:
    return " ".join(expanded_tokens(value))


def normalize_token(value: str) -> str:
    return value.casefold().strip(".,;:!?()[]{}<>\"'")


def is_special_token(token: str) -> bool:
    return any(char.isdigit() for char in token) or any(char in token for char in ".:/\\_#-")


def clamp_score(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def add_token(tokens: list[str], seen: set[str], token: str) -> None:
    token = normalize_token(token)
    if len(token) < 2 or token in seen:
        return
    seen.add(token)
    tokens.append(token)
