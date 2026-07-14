"""D-02 hard-gate smoke test (live) for the full `ArcadeDBClient` transaction/
retry/readiness surface against a real ArcadeDB container.

Mocked-HTTP unit tests (04-02, Task 1/2 -- no live container required) live in
the sibling `test_arcadedb_client_transport.py` (split out MD-03, 600-LOC cap).

The live-container tests below resolve the five §3 capability unknowns against a
LIVE `arcadedata/arcadedb:26.7.1` container (not a mock, not a doc-sourced guess)
and are each marked `integration` individually (pyproject.toml): a skip is
silent-green locally when ArcadeDB isn't running, but a CI failure under CI=true
(tests/conftest.py's no-skip-as-green guard) -- this hard gate must never pass
green without actually exercising the pinned image.

Resolves (see 04-SPIKE-FINDINGS.md for the full write-up):
  1. `vectorNeighbors('Type[property]', vec, k)` is the winning HNSW spelling.
  2. Filtered-ANN k-underfill IS present (post-filter, not pushdown) -- D-03's
     over-fetch-then-filter default stays.
  3. Intra-transaction read-your-writes (property-filtered SELECT, not just
     `$var`) works via the `arcadedb-session-id` header session model.
  4. `SEARCH_INDEX('Type[property]', query)` exposes an orderable `$score`;
     `CONTAINSTEXT` is boolean-only (returns 0.0 for `$score`).
  5. `arcadedata/arcadedb` requires `-Darcadedb.server.rootPassword`; wrong/absent
     credentials are rejected (401/403), confirmed live below.
"""

from __future__ import annotations

import os

import pytest

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient

TEST_DATABASE = "arcadedb_client_smoke"


def _client() -> ArcadeDBClient:
    return ArcadeDBClient(
        base_url=os.environ.get("ARCADEDB_URL", "http://127.0.0.1:2480"),
        database=TEST_DATABASE,
        username=os.environ.get("ARCADEDB_USER", "root"),
        password=os.environ.get("ARCADEDB_PASSWORD", "agentmemory-arcadedb-dev"),
    )


@pytest.fixture(scope="module")
def client() -> ArcadeDBClient:
    candidate = _client()
    if not candidate.is_ready():
        pytest.skip(
            f"ArcadeDB not reachable at {candidate.base_url} -- start it with "
            "`docker compose up -d arcadedb` before running this hard-gate smoke test.",
            allow_module_level=True,
        )
    return candidate


@pytest.fixture(scope="module", autouse=True)
def _fresh_database(client: ArcadeDBClient):
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass
    client.ensure_database()
    client.command("CREATE VERTEX TYPE Chunk")
    client.command("CREATE PROPERTY Chunk.id STRING")
    client.command("CREATE PROPERTY Chunk.content STRING")
    client.command("CREATE PROPERTY Chunk.embedding ARRAY_OF_FLOATS")
    client.command("CREATE PROPERTY Chunk.status STRING")
    client.command(
        "CREATE INDEX ON Chunk (embedding) LSM_VECTOR METADATA "
        '{"dimensions": 4, "similarity": "cosine", "maxConnections": 16, "beamWidth": 100}'
    )
    client.command("CREATE INDEX ON Chunk (id) UNIQUE")
    client.command("CREATE INDEX ON Chunk (content) FULL_TEXT")
    client.command("CREATE EDGE TYPE NextChunk")
    yield
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass


def _insert_chunk(
    client: ArcadeDBClient, *, id_: str, content: str, embedding: list[float], status: str
) -> None:
    client.command(
        "INSERT INTO Chunk SET id = :id, content = :content, embedding = :embedding, "
        "status = :status",
        params={"id": id_, "content": content, "embedding": embedding, "status": status},
    )


# -- Unknown 1 (+ A4 vector DDL, + the vector-literal-is-bindable correction) --


@pytest.mark.integration
def test_vector_neighbors_resolves_and_returns_record_plus_score(client: ArcadeDBClient) -> None:
    _insert_chunk(
        client, id_="v1", content="alpha", embedding=[1.0, 0.0, 0.0, 0.0], status="active"
    )
    _insert_chunk(client, id_="v2", content="beta", embedding=[0.0, 1.0, 0.0, 0.0], status="active")
    _insert_chunk(
        client, id_="v3", content="gamma", embedding=[0.9, 0.1, 0.0, 0.0], status="active"
    )

    # The query vector is bound as a named param (`:vec`) -- CONTEXT.md's locked
    # assumption that vector literals must be inlined is WRONG for 26.7.1;
    # corrected here and recorded in 04-SPIKE-FINDINGS.md.
    rows = client.query(
        'SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))',
        params={"vec": [1.0, 0.0, 0.0, 0.0], "k": 3},
    )

    assert [row["id"] for row in rows] == ["v1", "v3", "v2"]
    assert rows[0]["distance"] == pytest.approx(0.0, abs=1e-6)
    assert rows[0]["distance"] < rows[1]["distance"] < rows[2]["distance"]


# -- Unknown 2 (D-03 filtered-ANN k-underfill) --


@pytest.mark.integration
def test_filtered_vector_search_underfills_k_confirming_d03_overfetch_default(
    client: ArcadeDBClient,
) -> None:
    for index in range(7):
        _insert_chunk(
            client,
            id_=f"inactive{index}",
            content=f"inactive-{index}",
            embedding=[0.95, 0.05, 0.0, 0.0],
            status="inactive",
        )
    # 3 active fixtures (v1/v2/v3) already exist from the previous test; only
    # v1/v3 are near [1,0,0,0], v2 is far -- exactly the shape that exposes
    # post-filter k-underfill if the WHERE predicate does not push into HNSW.
    small_k = client.query(
        "SELECT id, status FROM "
        '(SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))) '
        "WHERE status = :status",
        params={"vec": [1.0, 0.0, 0.0, 0.0], "k": 2, "status": "active"},
    )
    large_k = client.query(
        "SELECT id, status FROM "
        '(SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))) '
        "WHERE status = :status",
        params={"vec": [1.0, 0.0, 0.0, 0.0], "k": 20, "status": "active"},
    )

    # k=2 under-fills: only 1 of the 3 active records surfaces because the
    # filter is applied AFTER the top-2 ANN results, not pushed into the search.
    assert len(small_k) < 3
    # Over-fetching (k=20) recovers all 3 active records -- confirms D-03's
    # locked over-fetch-then-filter default must stay; do not switch to native
    # predicate pushdown.
    assert len(large_k) == 3


# -- Unknown 4 (full-text analyzer + score exposure) --


@pytest.mark.integration
def test_search_index_exposes_orderable_score_but_containstext_does_not(
    client: ArcadeDBClient,
) -> None:
    matched = client.query(
        'SELECT id, $score FROM Chunk WHERE SEARCH_INDEX("Chunk[content]", :q) ORDER BY $score DESC',
        params={"q": "alpha"},
    )
    assert matched
    assert matched[0]["id"] == "v1"
    assert matched[0]["$score"] > 0.0

    contains_text = client.query(
        "SELECT id, $score FROM Chunk WHERE content CONTAINSTEXT :q",
        params={"q": "alpha"},
    )
    assert contains_text
    assert contains_text[0]["id"] == "v1"
    # CONTAINSTEXT is a boolean filter -- $score is NOT populated through it
    # (winning form for D-04/D-06 scoring is SEARCH_INDEX, not CONTAINSTEXT).
    assert contains_text[0]["$score"] == 0.0


# -- Unknown 3 (A5 intra-transaction read-your-writes) --


@pytest.mark.integration
def test_intra_transaction_read_your_writes_by_property_filter(client: ArcadeDBClient) -> None:
    session_id = client.begin()
    try:
        client.command(
            "CREATE VERTEX Chunk SET id = :id, content = :content, embedding = :embedding, "
            "status = :status",
            params={
                "id": "tx-a",
                "content": "tx-content",
                "embedding": [0.5, 0.5, 0.0, 0.0],
                "status": "active",
            },
            session_id=session_id,
        )

        in_tx = client.query(
            "SELECT id FROM Chunk WHERE id = :id", params={"id": "tx-a"}, session_id=session_id
        )
        assert [row["id"] for row in in_tx] == ["tx-a"]

        outside_tx_before_commit = client.query(
            "SELECT id FROM Chunk WHERE id = :id", params={"id": "tx-a"}
        )
        assert outside_tx_before_commit == []

        client.commit(session_id)
    except Exception:
        client.rollback(session_id)
        raise

    outside_tx_after_commit = client.query(
        "SELECT id FROM Chunk WHERE id = :id", params={"id": "tx-a"}
    )
    assert [row["id"] for row in outside_tx_after_commit] == ["tx-a"]


# -- Unknown 5 (auth requirement) --


@pytest.mark.integration
def test_credentials_are_required_and_enforced(client: ArcadeDBClient) -> None:
    # Empty credentials still send a (malformed) Basic Auth header, so ArcadeDB
    # rejects with 403 here, not the header-omitted 401 confirmed manually
    # against the raw HTTP API (see 04-SPIKE-FINDINGS.md) -- both paths prove
    # T-04-01-01's mitigation (no default-open access) holds.
    unauthenticated = ArcadeDBClient(
        base_url=client.base_url, database=client.database, username="", password=""
    )
    with pytest.raises(RuntimeError, match="ArcadeDB HTTP 403"):
        unauthenticated.query("SELECT 1 as x")

    wrong_password = ArcadeDBClient(
        base_url=client.base_url,
        database=client.database,
        username=client.username,
        password="definitely-not-the-password",
    )
    with pytest.raises(RuntimeError, match="ArcadeDB HTTP 403"):
        wrong_password.query("SELECT 1 as x")


# -- sqlscript LET-chaining (Pattern 1 groundwork; graph edge creation in one tx) --


@pytest.mark.integration
def test_sqlscript_let_chaining_creates_edge_across_two_new_vertices(
    client: ArcadeDBClient,
) -> None:
    client.command(
        "BEGIN;\n"
        'LET $a = CREATE VERTEX Chunk SET id = "scr-a", content = "scrA", '
        'embedding = [0.1,0.2,0.0,0.0], status = "active";\n'
        'LET $b = CREATE VERTEX Chunk SET id = "scr-b", content = "scrB", '
        'embedding = [0.2,0.1,0.0,0.0], status = "active";\n'
        "CREATE EDGE NextChunk FROM $a TO $b;\n"
        "COMMIT;\n",
        language="sqlscript",
    )

    rows = client.query(
        'SELECT out("NextChunk").id as nxt FROM Chunk WHERE id = :id', params={"id": "scr-a"}
    )
    assert rows[0]["nxt"] == ["scr-b"]


# -- D-05 groundwork: both graph-query surfaces bind params cleanly --


@pytest.mark.integration
def test_sql_match_and_opencypher_both_bind_params_for_two_hop_traversal(
    client: ArcadeDBClient,
) -> None:
    sql_rows = client.query(
        'MATCH {type: Chunk, as: c, where: (id = :id)}.out("NextChunk"){as: n} RETURN n.id',
        params={"id": "scr-a"},
    )
    assert sql_rows[0]["n.id"] == "scr-b"

    cypher_rows = client.query(
        "MATCH (c:Chunk {id: $id})-[:NextChunk]->(n:Chunk) RETURN n.id",
        params={"id": "scr-a"},
        language="opencypher",
    )
    assert cypher_rows[0]["n.id"] == "scr-b"
