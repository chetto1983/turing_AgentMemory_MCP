"""Phase 4 Plan 09, Task 2 Test 1 (ARC-08): `stable_id()` for a fixed input
must resolve to the SAME ArcadeDB-stored `id` property both before and after
a `rebuild_vector_projection()` call -- the D-07 versioned atomic swap
(04-08) stages a fresh embedding/lexical payload into a scratch property and
then copies it into the SAME live `embedding`/`lexical_tokens`/`lexical_weights`
fields; it must never touch the record's own `id` (no vector-ID drift,
Pitfall 6). Runs against `_arcadedb_rebuild_fake.FakeArcadeDBClient`, the
same fake `tests/test_store_arcadedb_rebuild.py` (04-08) already exercises
this exact rebuild path with -- no live ArcadeDB container required.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _arcadedb_rebuild_fake import FakeArcadeDBClient, make_store, row, seed_vertex
from _batch_memory_shared import CountingBatchEmbedder

from turing_agentmemory_mcp.ids import stable_id


def test_stable_id_survives_rebuild_for_a_fixed_input(tmp_path: Path) -> None:
    fixed_id = stable_id("mem", "alice", "s1", "user", "original content")

    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(
        client,
        "Memory",
        id=fixed_id,
        user_identifier="alice",
        content="original content",
        embedding=[0.0, 0.0, 0.0],
        lexical_tokens=[],
        lexical_weights=[],
    )

    before_id = row(client, "Memory", fixed_id)["id"]
    assert before_id == fixed_id

    result = store.rebuild_vector_projection(user_identifier="alice")

    after_id = row(client, "Memory", fixed_id)["id"]
    assert after_id == fixed_id
    assert after_id == before_id
    assert result["counts"]["memory"] == 1
    # The rebuild must have actually run (embedding/lexical payload refreshed)
    # -- proving id-stability isn't merely a no-op fixture artifact.
    refreshed = row(client, "Memory", fixed_id)
    assert refreshed["embedding"] == CountingBatchEmbedder()._vector("original content")


def test_stable_id_survives_two_consecutive_rebuilds(tmp_path: Path) -> None:
    fixed_id = stable_id("mem", "bob", "s1", "user", "some durable content")

    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(
        client,
        "Memory",
        id=fixed_id,
        user_identifier="bob",
        content="some durable content",
        embedding=[0.0, 0.0, 0.0],
        lexical_tokens=[],
        lexical_weights=[],
    )

    store.rebuild_vector_projection(user_identifier="bob")
    first_id = row(client, "Memory", fixed_id)["id"]

    store.rebuild_vector_projection(user_identifier="bob")
    second_id = row(client, "Memory", fixed_id)["id"]

    assert first_id == fixed_id
    assert second_id == fixed_id
