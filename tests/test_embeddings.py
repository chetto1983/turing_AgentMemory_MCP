from turing_agentmemory_mcp.embeddings import HashingEmbedder


def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(dimensions=16)
    first = embedder.embed("espresso memory")
    second = embedder.embed("espresso memory")
    assert first == second
    assert round(sum(value * value for value in first), 6) == 1.0
    assert len(first) == 16
