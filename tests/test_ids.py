from turing_agentmemory_mcp.ids import cypher_var, stable_id


def test_stable_id_is_deterministic_for_the_same_input() -> None:
    assert stable_id("memory", "alice", "m1") == stable_id("memory", "alice", "m1")


def test_stable_id_differs_for_different_inputs() -> None:
    assert stable_id("memory", "alice", "m1") != stable_id("memory", "bob", "m1")


def test_stable_id_is_prefixed() -> None:
    assert stable_id("memory", "alice", "m1").startswith("memory_")


def test_cypher_var_sanitizes_unsafe_characters() -> None:
    assert cypher_var("alice-1.2 3") == "alice_1_2_3"


def test_cypher_var_prefixes_a_leading_digit() -> None:
    assert cypher_var("123abc") == "n_123abc"
