"""04-03: idempotent schema bootstrap (D-09) unit tests against a fake client.

Every test here runs against `_FakeArcadeDBClient` (a scripted in-memory stand-in
for `ArcadeDBClient`) -- no live ArcadeDB container is required. The DDL forms
asserted below (`LSM_VECTOR METADATA {...}`, `LSM_SPARSE_VECTOR`, `IF NOT
EXISTS` semantics) were empirically verified live against
`arcadedata/arcadedb:26.7.1` as part of this plan; see `arcadedb_schema.py`'s
module docstring and `04-SPIKE-FINDINGS.md`.
"""

from __future__ import annotations

import re

import pytest

from turing_agentmemory_mcp.arcadedb_schema import (
    _FULL_TEXT_PROPERTY_BY_TYPE,
    EDGE_TYPES,
    STABLE_ID_TYPES,
    TENANT_MANIFEST_TYPE,
    VECTOR_TYPES,
    VERTEX_TYPES,
    bootstrap,
    introspect_vector_dimension,
    versioned_vector_index,
)

_CREATE_INDEX_RE = re.compile(r"^CREATE INDEX ON (\w+) \(([^)]+)\)", re.IGNORECASE)


class _FakeArcadeDBClient:
    """Scripted stand-in for `ArcadeDBClient.command`/`.query`.

    Type/property `CREATE ... IF NOT EXISTS` statements are accepted
    unconditionally (matching ArcadeDB's confirmed native idempotency for
    those two constructs). `CREATE INDEX` statements are NOT idempotent on the
    real server (no `IF NOT EXISTS` support, confirmed live) -- a second
    attempt to create the identical index raises, mirroring the real
    "already exists" error text `arcadedb_schema.py` catches.
    """

    def __init__(self, *, sample_vectors: dict[str, list[float]] | None = None) -> None:
        self.commands: list[tuple[str, dict[str, object] | None, str]] = []
        self._created_indexes: set[str] = set()
        self._sample_vectors = sample_vectors or {}

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.commands.append((statement, params, language))
        match = _CREATE_INDEX_RE.match(statement.strip())
        if match:
            type_name, props = match.group(1), match.group(2).replace(" ", "")
            index_name = f"{type_name}[{props}]"
            if index_name in self._created_indexes:
                raise RuntimeError(
                    "ArcadeDB HTTP 500 at /api/v1/command/agent_memory: "
                    '{"error":"Error on transaction commit",'
                    f'"detail":"Index \'{index_name}\' already exists",'
                    '"exception":"com.arcadedb.exception.CommandExecutionException"}'
                )
            self._created_indexes.add(index_name)
        return []

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        for type_name, vector in self._sample_vectors.items():
            if f"FROM {type_name} " in statement:
                return [{"vector": vector}]
        return []


def test_bootstrap_creates_full_schema_and_is_idempotent_on_rerun() -> None:
    client = _FakeArcadeDBClient()

    bootstrap(client, dimensions=768, version=1)
    statements = [entry[0] for entry in client.commands]

    for vertex_type in VERTEX_TYPES:
        assert any(f"CREATE VERTEX TYPE {vertex_type} IF NOT EXISTS" in s for s in statements)
    for edge_type in EDGE_TYPES:
        assert any(f"CREATE EDGE TYPE {edge_type} IF NOT EXISTS" in s for s in statements)
    for type_name in VECTOR_TYPES:
        assert any(f"CREATE INDEX ON {type_name} (embedding) LSM_VECTOR" in s for s in statements)
        assert any(
            f"CREATE INDEX ON {type_name} (lexical_tokens, lexical_weights) LSM_SPARSE_VECTOR" in s
            for s in statements
        )
    for type_name, text_property in _FULL_TEXT_PROPERTY_BY_TYPE.items():
        assert any(
            f"CREATE INDEX ON {type_name} ({text_property}) FULL_TEXT" in s for s in statements
        )
    for type_name in STABLE_ID_TYPES:
        assert any(f"CREATE INDEX ON {type_name} (id) UNIQUE" in s for s in statements)

    # Re-run must not raise despite the fake's non-idempotent CREATE INDEX behavior --
    # bootstrap()'s own catch-"already exists" logic must absorb it.
    bootstrap(client, dimensions=768, version=1)


def test_bootstrap_creates_immutable_tenant_manifest_contract() -> None:
    client = _FakeArcadeDBClient()

    bootstrap(client, dimensions=768, version=1)
    statements = [entry[0] for entry in client.commands]

    assert f"CREATE VERTEX TYPE {TENANT_MANIFEST_TYPE} IF NOT EXISTS" in statements
    for property_name, data_type in {
        "singleton_id": "STRING",
        "database_name": "STRING",
        "digest": "STRING",
        "naming_version": "INTEGER",
        "key_fingerprint": "STRING",
        "schema_version": "INTEGER",
        "created_at": "STRING",
    }.items():
        assert (
            f"CREATE PROPERTY {TENANT_MANIFEST_TYPE}.{property_name} IF NOT EXISTS {data_type}"
        ) in statements
    assert f"CREATE INDEX ON {TENANT_MANIFEST_TYPE} (singleton_id) UNIQUE" in statements


def test_lsm_vector_ddl_carries_dimensions_and_cosine_full_precision() -> None:
    client = _FakeArcadeDBClient()

    bootstrap(client, dimensions=1024, version=1)
    statements = [entry[0] for entry in client.commands]

    vector_ddl = [s for s in statements if "LSM_VECTOR METADATA" in s and "Memory" in s]
    assert vector_ddl, "expected an LSM_VECTOR METADATA statement for Memory"
    assert '"dimensions": 1024' in vector_ddl[0]
    assert '"similarity": "cosine"' in vector_ddl[0]

    joined = "\n".join(statements).lower()
    assert "int8" not in joined
    assert "binary_quant" not in joined
    assert "quantiz" not in joined


def test_dimension_mismatch_against_existing_data_raises_value_error() -> None:
    client = _FakeArcadeDBClient(sample_vectors={"Memory": [0.1] * 512})

    with pytest.raises(ValueError, match=r"expected 768, found 512"):
        bootstrap(client, dimensions=768, version=1)


def test_versioned_vector_index_contains_tenant_digest_and_version_suffix() -> None:
    name_v1 = versioned_vector_index("agent_memory_vectors", "user-a", 1)
    name_v1_again = versioned_vector_index("agent_memory_vectors", "user-a", 1)
    name_v2 = versioned_vector_index("agent_memory_vectors", "user-a", 2)
    name_other_user = versioned_vector_index("agent_memory_vectors", "user-b", 1)

    assert name_v1 == name_v1_again, "deterministic for identical inputs"
    assert name_v1 != name_v2, "different versions must differ"
    assert name_v1 != name_other_user, "different tenants must differ"
    assert name_v1.endswith("_v1")
    assert name_v2.endswith("_v2")

    with pytest.raises(ValueError):
        versioned_vector_index("agent_memory_vectors", "user-a", 0)


def test_unique_index_is_on_stable_id_property_no_rid_reference() -> None:
    client = _FakeArcadeDBClient()

    bootstrap(client, dimensions=768, version=1)
    statements = [entry[0] for entry in client.commands]
    joined = "\n".join(statements)

    for type_name in STABLE_ID_TYPES:
        assert f"CREATE INDEX ON {type_name} (id) UNIQUE" in joined

    assert "getIdentity" not in joined
    assert "@rid" not in joined.lower()


def test_bootstrap_creates_lucene_full_text_index_alongside_sparse_vector() -> None:
    """Both-channels decision (user decision reconciling D-04 spike with
    pre-spike plans): every VECTOR_TYPE gets a Lucene FULL_TEXT index on its
    raw text property, in addition to the LSM_SPARSE_VECTOR channel -- not
    instead of it. Chunk uses `text`; every other type uses `content`."""
    client = _FakeArcadeDBClient()

    bootstrap(client, dimensions=768, version=1)
    statements = [entry[0] for entry in client.commands]

    assert _FULL_TEXT_PROPERTY_BY_TYPE == {
        "Memory": "content",
        "Chunk": "text",
        "Entity": "content",
        "Fact": "content",
        "Community": "content",
    }
    for type_name in VECTOR_TYPES:
        text_property = _FULL_TEXT_PROPERTY_BY_TYPE[type_name]
        assert any(
            f"CREATE PROPERTY {type_name}.{text_property} IF NOT EXISTS STRING" in s
            for s in statements
        )
        assert any(
            f"CREATE INDEX ON {type_name} ({text_property}) FULL_TEXT" in s for s in statements
        )
        # still present -- FULL_TEXT is additive, not a replacement
        assert any(
            f"CREATE INDEX ON {type_name} (lexical_tokens, lexical_weights) LSM_SPARSE_VECTOR" in s
            for s in statements
        )

    joined = "\n".join(statements).lower()
    assert "search_index" not in joined  # bootstrap only creates the index, never queries it

    # Re-run must not raise despite the fake's non-idempotent CREATE INDEX behavior.
    bootstrap(client, dimensions=768, version=1)


def test_introspect_vector_dimension_returns_none_when_no_sample_exists() -> None:
    client = _FakeArcadeDBClient()
    assert introspect_vector_dimension(client, "Memory[embedding]") is None


def test_introspect_vector_dimension_rejects_malformed_reference() -> None:
    client = _FakeArcadeDBClient()
    with pytest.raises(ValueError):
        introspect_vector_dimension(client, "not-a-valid-reference")
