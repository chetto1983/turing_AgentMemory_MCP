from __future__ import annotations

from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score, rank_hybrid


def test_exact_identifier_and_path_match_scores_higher_than_vague_overlap() -> None:
    query = "INC-7781 E42-ALPHA router.yml"
    exact = "Incident INC-7781 affects C:\\ops\\delta\\router.yml with error E42-ALPHA."
    vague = "Incident notes mention a router issue with an alpha release."

    assert lexical_score(query, exact) > lexical_score(query, vague)
    assert lexical_score(query, exact) >= 0.9


def test_hybrid_blend_boosts_semantic_score_when_lexical_match_is_strong() -> None:
    semantic = 0.42
    lexical = 0.95

    assert blend_hybrid_score(semantic_score=semantic, lexical_score=lexical) > semantic


def test_rank_hybrid_places_exact_code_match_above_semantic_only_candidate() -> None:
    ranked = rank_hybrid(
        query="incident INC-7781 E42-ALPHA router.yml",
        candidates=[
            ("semantic-only", 0.88, "General network incident notes about retry policy."),
            (
                "exact-code",
                0.35,
                "Incident INC-7781 in C:\\ops\\delta\\router.yml failed with E42-ALPHA.",
            ),
        ],
    )

    assert ranked[0].candidate_id == "exact-code"
    assert ranked[0].lexical_score > ranked[1].lexical_score
