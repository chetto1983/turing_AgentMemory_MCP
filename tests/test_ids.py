from turing_agentmemory_mcp.ids import quote


def test_quote_escapes_control_characters_for_cypher_literals() -> None:
    assert quote('a"b\\c\nr\tx') == 'a\\"b\\\\c\\nr\\tx'
