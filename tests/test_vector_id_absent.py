"""Phase 4 Plan 09, Task 1: repo-scoped regression guard proving the retired
`vector_id` int-join machinery (ARC-05 "delete, don't port") never returns, and
that no ArcadeDB native RID (`#12:34`/`@rid`) is ever captured as an
identifier anywhere in the store's read/write paths.

`stable_id()`/`cypher_var()` are the ONLY identifier helpers kept in
`ids.py` -- every store module builds its own identifiers from `stable_id()`,
never from a synthetic integer join column or the database's own record id.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp"

# Every store read/write module (the mixins TuringAgentMemory composes) plus
# the id/util modules the vector_id machinery used to live in.
STORE_MODULE_PATHS = sorted(SRC_DIR.glob("store*.py")) + [SRC_DIR / "ids.py"]

_VECTOR_ID_PATTERN = re.compile(
    r"\bvector_id\b|_memory_vector_id|_entity_vector_id|_fact_vector_id"
    r"|_community_vector_id|_document_vector_id"
)

# ArcadeDB's own record identity is `#<bucket>:<position>` (e.g. `#12:34`) or
# the `@rid`/`@RID` metadata property -- neither is ever a valid application
# identifier (stable_id() is canonical); this pattern catches either form
# being captured/stored/compared as an id.
_RID_PATTERN = re.compile(r"@rid\b|@RID\b|#\d+:\d+")


def test_importing_store_package_succeeds_after_vector_id_deletion() -> None:
    import turing_agentmemory_mcp.store  # noqa: F401


def test_stable_id_and_cypher_var_still_defined() -> None:
    from turing_agentmemory_mcp import ids

    assert callable(ids.stable_id)
    assert callable(ids.cypher_var)
    assert not hasattr(ids, "vector_id")
    assert not hasattr(ids, "quote")


@pytest.mark.parametrize("path", STORE_MODULE_PATHS, ids=lambda p: p.name)
def test_no_vector_id_token_or_helper_symbol_remains(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    match = _VECTOR_ID_PATTERN.search(source)
    assert match is None, f"{path.name} still references {match.group(0)!r} (vector_id machinery)"


@pytest.mark.parametrize("path", STORE_MODULE_PATHS, ids=lambda p: p.name)
def test_no_arcadedb_rid_used_as_identifier(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    match = _RID_PATTERN.search(source)
    assert match is None, f"{path.name} captures an ArcadeDB RID form ({match.group(0)!r})"


def test_ids_module_defines_only_stable_id_and_cypher_var_helpers() -> None:
    source = (SRC_DIR / "ids.py").read_text(encoding="utf-8")
    assert "def vector_id(" not in source
    assert "def quote(" not in source
    assert "def stable_id(" in source
    assert "def cypher_var(" in source
