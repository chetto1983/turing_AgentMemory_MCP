"""Deterministic weighted reciprocal-rank fusion for retrieval channels."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .models import (
    FusedRetrievalCandidate,
    FusionChannelScore,
    RetrievalCandidate,
)
from .search_controls import validate_fusion_weights

DEFAULT_RRF_K = 60
DEFAULT_CHANNEL_CAP = 200


@dataclass(slots=True)
class _Accumulator:
    candidate: RetrievalCandidate
    score: float = 0.0
    best_rank: int = 2**31 - 1
    channels: dict[str, FusionChannelScore] = field(default_factory=dict)


def fuse_rankings(
    rankings: Mapping[str, Sequence[RetrievalCandidate]],
    *,
    weights: Mapping[str, object],
    rank_constant: float = DEFAULT_RRF_K,
    channel_caps: int | Mapping[str, int] = DEFAULT_CHANNEL_CAP,
) -> list[FusedRetrievalCandidate]:
    validated_weights = validate_fusion_weights(weights)
    if isinstance(rank_constant, bool) or not isinstance(rank_constant, (int, float)):
        raise ValueError("rank_constant must be a positive finite number")
    rank_constant = float(rank_constant)
    if not math.isfinite(rank_constant) or rank_constant <= 0:
        raise ValueError("rank_constant must be a positive finite number")
    caps = _validate_channel_caps(channel_caps, rankings)

    accumulators: dict[str, _Accumulator] = {}
    if any(not isinstance(channel, str) or not channel.strip() for channel in rankings):
        raise ValueError("retrieval channel must be non-empty")
    for channel in sorted(rankings):
        if channel not in validated_weights:
            raise ValueError(f"fusion weight is missing for channel {channel}")
        unique: list[RetrievalCandidate] = []
        seen: dict[str, RetrievalCandidate] = {}
        for candidate in rankings[channel]:
            _validate_candidate(candidate)
            existing = accumulators.get(candidate.candidate_id)
            if existing is not None and not _same_candidate_identity(
                existing.candidate, candidate
            ):
                raise ValueError(
                    f"conflicting candidate identity for {candidate.candidate_id}"
                )
            duplicate = seen.get(candidate.candidate_id)
            if duplicate is not None:
                if not _same_candidate_identity(duplicate, candidate):
                    raise ValueError(
                        f"conflicting candidate identity for {candidate.candidate_id}"
                    )
                continue
            seen[candidate.candidate_id] = candidate
            unique.append(candidate)
            if len(unique) >= caps[channel]:
                break
        weight = validated_weights[channel]
        for rank, candidate in enumerate(unique, start=1):
            accumulator = accumulators.get(candidate.candidate_id)
            if accumulator is None:
                accumulator = _Accumulator(candidate=candidate)
                accumulators[candidate.candidate_id] = accumulator
            contribution = weight / (rank_constant + rank)
            accumulator.score += contribution
            accumulator.best_rank = min(accumulator.best_rank, rank)
            accumulator.channels[channel] = FusionChannelScore(
                rank=rank,
                raw_score=candidate.raw_score,
                weight=weight,
                contribution=contribution,
            )

    fused = [
        FusedRetrievalCandidate(
            candidate=accumulator.candidate,
            score=accumulator.score,
            best_rank=accumulator.best_rank,
            channels={
                channel: accumulator.channels[channel]
                for channel in sorted(accumulator.channels)
            },
        )
        for accumulator in accumulators.values()
    ]
    fused.sort(
        key=lambda item: (
            -item.score,
            item.best_rank,
            item.candidate.candidate_id,
        )
    )
    return fused


def diversify_fused(
    candidates: Sequence[FusedRetrievalCandidate],
    *,
    limit: int,
    max_per_source: int = 1,
) -> list[FusedRetrievalCandidate]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("diversity limit must be a positive integer")
    if (
        isinstance(max_per_source, bool)
        or not isinstance(max_per_source, int)
        or max_per_source <= 0
    ):
        raise ValueError("max_per_source must be a positive integer")
    selected: list[FusedRetrievalCandidate] = []
    source_counts: dict[str, int] = {}
    for candidate in candidates:
        source_id = (
            candidate.candidate.source_memory_id
            or candidate.candidate.candidate_id
        )
        if source_counts.get(source_id, 0) >= max_per_source:
            continue
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _validate_channel_caps(
    channel_caps: int | Mapping[str, int],
    rankings: Mapping[str, Sequence[RetrievalCandidate]],
) -> dict[str, int]:
    if isinstance(channel_caps, bool):
        raise ValueError("channel cap must be a positive integer")
    if isinstance(channel_caps, int):
        if channel_caps <= 0:
            raise ValueError("channel cap must be a positive integer")
        return {channel: channel_caps for channel in rankings}
    if not isinstance(channel_caps, Mapping):
        raise ValueError("channel caps must be an integer or mapping")
    caps: dict[str, int] = {}
    for channel in rankings:
        cap = channel_caps.get(channel, DEFAULT_CHANNEL_CAP)
        if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
            raise ValueError(f"channel cap for {channel} must be a positive integer")
        caps[channel] = cap
    return caps


def _validate_candidate(candidate: RetrievalCandidate) -> None:
    if not isinstance(candidate, RetrievalCandidate):
        raise ValueError("retrieval ranking contains an invalid candidate")
    if not candidate.candidate_id.strip() or not candidate.kind.strip() or not candidate.content.strip():
        raise ValueError("retrieval candidate identity fields must be non-empty")
    if candidate.raw_score is not None:
        if isinstance(candidate.raw_score, bool) or not isinstance(candidate.raw_score, (int, float)):
            raise ValueError("retrieval candidate raw score must be finite")
        if not math.isfinite(float(candidate.raw_score)):
            raise ValueError("retrieval candidate raw score must be finite")


def _same_candidate_identity(
    left: RetrievalCandidate,
    right: RetrievalCandidate,
) -> bool:
    return (
        left.candidate_id,
        left.kind,
        left.content,
        left.source_memory_id,
        left.evidence_source_ids,
        left.metadata,
    ) == (
        right.candidate_id,
        right.kind,
        right.content,
        right.source_memory_id,
        right.evidence_source_ids,
        right.metadata,
    )
