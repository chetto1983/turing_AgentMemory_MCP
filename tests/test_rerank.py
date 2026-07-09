from turing_agentmemory_mcp.rerank import Scored, apply_rerank_guard, identity, truncate_runes


def test_identity_is_input_order() -> None:
    assert identity(["a", "b"]) == [Scored(index=0, score=0.0), Scored(index=1, score=0.0)]


def test_apply_rerank_guard_reorders_confident_scores() -> None:
    seed = ["seed-0", "seed-1", "seed-2"]
    out = apply_rerank_guard(
        seed,
        [Scored(index=2, score=0.9), Scored(index=0, score=0.2), Scored(index=1, score=0.1)],
        threshold=0.5,
    )
    assert [item for item, _ in out] == ["seed-2", "seed-0", "seed-1"]
    assert out[0][1] == 0.9


def test_apply_rerank_guard_keeps_seed_below_threshold() -> None:
    seed = ["seed-0", "seed-1"]
    out = apply_rerank_guard(
        seed,
        [Scored(index=1, score=0.2), Scored(index=0, score=0.1)],
        threshold=0.5,
    )
    assert [item for item, _ in out] == seed
    assert [score for _, score in out] == [None, None]


def test_truncate_runes_caps_wire_body() -> None:
    assert truncate_runes("abcdef", 3) == "abc"
