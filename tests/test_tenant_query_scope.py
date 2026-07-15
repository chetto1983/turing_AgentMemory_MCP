"""Mechanical defense-in-depth audit for every public ArcadeDB query builder."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import ModuleType

import pytest

from turing_agentmemory_mcp import (
    store_documents,
    store_documents_queries,
    store_memory_queries,
    store_memory_read,
    store_memory_write,
    store_rebuild,
    store_rebuild_queries,
    store_retrieval_queries,
    store_search,
)
from turing_agentmemory_mcp.temporal_graph import (
    EdgeProjection,
    EntityProjection,
    FactProjection,
)

TENANT = "tenant-scope-audit"
RESOURCE_ID = "foreign-resource-id"

QUERY_MODULES: tuple[ModuleType, ...] = (
    store_memory_queries,
    store_documents_queries,
    store_rebuild_queries,
    store_retrieval_queries,
)


@dataclass(frozen=True)
class BuilderCase:
    builder: Callable[..., object]
    argument_factory: Callable[[], dict[str, object]]


def _qualified(builder: Callable[..., object]) -> str:
    return f"{builder.__module__}.{builder.__name__}"


def _entity() -> EntityProjection:
    return EntityProjection(
        id=RESOURCE_ID,
        user_identifier=TENANT,
        entity_type="person",
        canonical_name="alice",
        display_name="Alice",
        content="Alice",
        confidence=0.9,
        observed_at="2026-07-15T00:00:00Z",
        source_memory_id="memory-id",
        schema_version="1",
        model="test",
        expires_at="",
    )


def _fact() -> FactProjection:
    return FactProjection(
        id=RESOURCE_ID,
        user_identifier=TENANT,
        subject_entity_id="entity-a",
        predicate="KNOWS",
        object_entity_id="entity-b",
        content="Alice knows Bob",
        confidence=0.8,
        observed_at="2026-07-15T00:00:00Z",
        valid_from="",
        valid_to="",
        valid_time_precision="unknown",
        source_memory_id="memory-id",
        session_id="session-id",
        speaker="user",
        source="test",
        tags=(),
        metadata={},
        schema_version="1",
        model="test",
        expires_at="",
    )


def _prepared_community() -> list[dict[str, object]]:
    return [
        {
            "id": RESOURCE_ID,
            "content": "community",
            "member_ids": ["entity-a"],
            "member_ids_json": '["entity-a"]',
            "source_memory_ids_json": '["memory-id"]',
            "fact_ids_json": "[]",
            "confidence": 0.8,
            "level": 0,
            "parent_id": "",
            "edge_weight": 1.0,
            "embedding": [0.1, 0.2],
            "lexical_tokens": [1],
            "lexical_weights": [1.0],
        }
    ]


_ARGUMENTS: dict[str, object] = {
    "active_status": "active",
    "chunk_chars": 100,
    "chunk_count": 1,
    "chunk_id": RESOURCE_ID,
    "community_ids": [RESOURCE_ID],
    "content": "content",
    "created_at": "2026-07-15T00:00:00Z",
    "dimensions": 2,
    "document_id": RESOURCE_ID,
    "edge_kind": "SUBJECT_OF",
    "embedding": [0.1, 0.2],
    "entity": _entity(),
    "entity_ids": [RESOURCE_ID],
    "edges": (
        EdgeProjection(
            id="edge-id",
            source_id="memory-id",
            target_id="entity-id",
            kind="MENTIONS",
        ),
    ),
    "existing_ids": set(),
    "expires_at": "",
    "extra_fields": (),
    "fact": _fact(),
    "fact_ids": [RESOURCE_ID],
    "filename": "document.txt",
    "hop": 1,
    "k": 2,
    "kind": "message",
    "lexical_tokens": [1],
    "lexical_weights": [1.0],
    "limit": 2,
    "locator": "line:1",
    "memory_id": RESOURCE_ID,
    "memory_ids": [RESOURCE_ID],
    "metadata_json": "{}",
    "ordinal": 0,
    "prepared": _prepared_community(),
    "previous_chunk_id": "previous-chunk-id",
    "property_name": "embedding_v2",
    "query": "query",
    "record_id": RESOURCE_ID,
    "role": "user",
    "session_id": "session-id",
    "source": "test",
    "staging_embedding_property": "embedding_v2",
    "staging_tokens_property": "tokens_v2",
    "staging_weights_property": "weights_v2",
    "status": "active",
    "tags_json": "[]",
    "text": "document text",
    "text_hash": "hash",
    "text_property": "content",
    "timestamp": "2026-07-15T00:00:00Z",
    "title": "Document",
    "tokens": [1],
    "tokens_property": "tokens_v2",
    "type_name": "Memory",
    "updated_at": "2026-07-15T00:00:00Z",
    "user_identifier": TENANT,
    "version": 2,
    "version_id": RESOURCE_ID,
    "weights": [1.0],
    "weights_property": "weights_v2",
}


def _arguments_for(builder: Callable[..., object]) -> dict[str, object]:
    arguments: dict[str, object] = {}
    for name, parameter in inspect.signature(builder).parameters.items():
        if parameter.default is not inspect.Parameter.empty:
            continue
        if name not in _ARGUMENTS:
            raise AssertionError(
                f"missing representative argument for {_qualified(builder)}:{name}"
            )
        arguments[name] = _ARGUMENTS[name]
    return arguments


def _case(builder: Callable[..., object]) -> BuilderCase:
    return BuilderCase(builder=builder, argument_factory=lambda: _arguments_for(builder))


TENANT_SCOPED_BUILDERS: tuple[BuilderCase, ...] = tuple(
    _case(builder)
    for builder in (
        store_memory_queries.memory_create_statement,
        store_memory_queries.memory_edge_statement,
        store_memory_queries.entity_create_statement,
        store_memory_queries.fact_create_statement,
        store_memory_queries.projection_edge_statements,
        store_memory_queries.memory_select_statement,
        store_memory_queries.memory_list_statement,
        store_memory_queries.memory_update_statement,
        store_memory_queries.memory_delete_statements,
        store_documents_queries.document_create_statement,
        store_documents_queries.document_edge_statement,
        store_documents_queries.chunk_create_statement,
        store_documents_queries.has_chunk_edge_statement,
        store_documents_queries.next_chunk_edge_statement,
        store_documents_queries.document_select_statement,
        store_documents_queries.document_update_statement,
        store_documents_queries.chunk_metadata_update_statement,
        store_documents_queries.document_delete_statement,
        store_documents_queries.chunk_delete_statement,
        store_documents_queries.document_hard_delete_statement,
        store_documents_queries.chunk_hard_delete_statement,
        store_documents_queries.chunk_context_statement,
        store_documents_queries.chunk_vector_search_statement,
        store_documents_queries.chunk_lucene_search_statement,
        store_rebuild_queries.vector_version_select_statement,
        store_rebuild_queries.vector_version_create_statement,
        store_rebuild_queries.vector_version_update_statement,
        store_rebuild_queries.stage_vector_statement,
        store_rebuild_queries.swap_vector_statement,
        store_rebuild_queries.canonical_vector_records_statement,
        store_rebuild_queries.fact_ids_for_memory_statement,
        store_rebuild_queries.existing_entity_ids_statement,
        store_rebuild_queries.community_entities_statement,
        store_rebuild_queries.community_mentions_statement,
        store_rebuild_queries.community_facts_statement,
        store_rebuild_queries.active_community_ids_statement,
        store_rebuild_queries.community_replace_sqlscript,
        store_retrieval_queries.dense_search_statement,
        store_retrieval_queries.sparse_search_statement,
        store_retrieval_queries.lucene_search_statement,
        store_retrieval_queries.entity_traversal_statement,
        store_retrieval_queries.fact_sources_by_ids_statement,
        store_retrieval_queries.community_sources_by_ids_statement,
        store_retrieval_queries.memory_rows_by_ids_statement,
    )
)

TENANT_SCOPE_EXEMPTIONS: dict[Callable[..., object], str] = {
    store_rebuild_queries.vector_version_schema_ddl: (
        "schema-only VectorVersion type/property/index lifecycle in the selected database"
    ),
    store_rebuild_queries.staging_vector_schema_ddl: (
        "schema-only scratch vector property/index lifecycle in the selected database"
    ),
    store_rebuild_queries.staging_lexical_schema_ddl: (
        "schema-only scratch lexical property lifecycle in the selected database"
    ),
    store_rebuild_queries.drop_staging_vector_index_ddl: (
        "schema-only scratch vector index removal in the selected database"
    ),
    store_rebuild_queries.drop_staging_property_ddl: (
        "schema-only scratch property removal in the selected database"
    ),
}

EDGE_BUILDERS: tuple[BuilderCase, ...] = tuple(
    case
    for case in TENANT_SCOPED_BUILDERS
    if case.builder
    in {
        store_memory_queries.memory_edge_statement,
        store_memory_queries.projection_edge_statements,
        store_documents_queries.document_edge_statement,
        store_documents_queries.has_chunk_edge_statement,
        store_documents_queries.next_chunk_edge_statement,
        store_rebuild_queries.community_replace_sqlscript,
    }
)

STABLE_ID_BUILDERS: dict[Callable[..., object], str] = {
    store_memory_queries.memory_select_statement: "id",
    store_memory_queries.memory_update_statement: "id",
    store_memory_queries.memory_delete_statements: "id",
    store_documents_queries.document_select_statement: "id",
    store_documents_queries.document_update_statement: "id",
    store_documents_queries.document_delete_statement: "id",
    store_documents_queries.document_hard_delete_statement: "id",
    store_documents_queries.chunk_hard_delete_statement: "document_id",
    store_documents_queries.chunk_context_statement: "id",
    store_rebuild_queries.vector_version_select_statement: "id",
    store_rebuild_queries.vector_version_create_statement: "id",
    store_rebuild_queries.vector_version_update_statement: "id",
    store_rebuild_queries.stage_vector_statement: "id",
}


def _public_query_builders(module: ModuleType) -> set[Callable[..., object]]:
    builders: set[Callable[..., object]] = set()
    for name, candidate in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_") or candidate.__module__ != module.__name__:
            continue
        return_type = str(inspect.signature(candidate).return_annotation)
        if "Statement" in return_type or name.endswith(
            ("_statement", "_statements", "_sqlscript", "_ddl")
        ):
            builders.add(candidate)
    return builders


def _statements(case: BuilderCase) -> list[tuple[str, dict[str, object]]]:
    result = case.builder(**case.argument_factory())
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
        return [result]  # type: ignore[list-item]
    assert isinstance(result, list), _qualified(case.builder)
    assert all(
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], str)
        and isinstance(item[1], dict)
        for item in result
    ), _qualified(case.builder)
    return result  # type: ignore[return-value]


def _edge_commands(sql: str) -> Iterable[str]:
    for line in sql.splitlines():
        for fragment in line.split(";"):
            start = fragment.find("CREATE EDGE ")
            if start >= 0:
                yield fragment[start:].strip()


def _endpoint_clause(command: str, keyword: str) -> str | None:
    marker = f"{keyword} (SELECT FROM "
    start = command.find(marker)
    if start < 0:
        return None
    end = command.find(")", start)
    assert end >= 0, command
    return command[start:end]


def test_all_query_builders_are_classified() -> None:
    discovered = set().union(*(_public_query_builders(module) for module in QUERY_MODULES))
    classified = {case.builder for case in TENANT_SCOPED_BUILDERS} | set(TENANT_SCOPE_EXEMPTIONS)

    assert discovered == classified, (
        f"unclassified={sorted(_qualified(item) for item in discovered - classified)}; "
        f"stale={sorted(_qualified(item) for item in classified - discovered)}"
    )


def test_tenant_scope_exemptions_are_narrow_and_reasoned() -> None:
    allowed_reason_terms = ("schema-only", "ready manifest", "server lifecycle")
    for builder, reason in TENANT_SCOPE_EXEMPTIONS.items():
        assert builder.__name__.endswith("_ddl"), _qualified(builder)
        assert any(term in reason.lower() for term in allowed_reason_terms), _qualified(builder)
        assert "*" not in _qualified(builder)
        result = builder(**_arguments_for(builder))
        statements = result if isinstance(result, list) else [result]
        assert statements and all(
            isinstance(statement, str)
            and statement.lstrip().upper().startswith(("CREATE ", "DROP "))
            for statement in statements
        ), _qualified(builder)


@pytest.mark.parametrize("case", TENANT_SCOPED_BUILDERS, ids=lambda case: case.builder.__name__)
def test_every_tenant_builder_binds_user_identifier(case: BuilderCase) -> None:
    for sql, params in _statements(case):
        assert params.get("user_identifier") == TENANT, _qualified(case.builder)
        assert "user_identifier = :user_identifier" in sql, _qualified(case.builder)
        assert TENANT not in sql, _qualified(case.builder)


@pytest.mark.parametrize("case", EDGE_BUILDERS, ids=lambda case: case.builder.__name__)
def test_every_edge_endpoint_is_tenant_scoped(case: BuilderCase) -> None:
    for sql, params in _statements(case):
        for command in _edge_commands(sql):
            source = _endpoint_clause(command, "FROM")
            target = _endpoint_clause(command, "TO")
            assert source is not None, _qualified(case.builder)
            if "SELECT FROM User " in source:
                assert "identifier = :identifier" in source, _qualified(case.builder)
                assert params.get("identifier") == TENANT, _qualified(case.builder)
            else:
                assert "user_identifier = :user_identifier" in source, _qualified(case.builder)
            if target is not None:
                assert "user_identifier = :user_identifier" in target, _qualified(case.builder)


@pytest.mark.parametrize(
    ("builder", "id_param"),
    STABLE_ID_BUILDERS.items(),
    ids=lambda value: value.__name__ if callable(value) else str(value),
)
def test_stable_resource_ids_are_paired_with_tenant_scope(
    builder: Callable[..., object], id_param: str
) -> None:
    case = _case(builder)
    resource_id_bound = False
    for sql, params in _statements(case):
        if params.get(id_param) == RESOURCE_ID:
            resource_id_bound = True
        assert params.get("user_identifier") == TENANT, _qualified(builder)
        assert "user_identifier = :user_identifier" in sql, _qualified(builder)
        assert RESOURCE_ID not in sql, _qualified(builder)
    assert resource_id_bound, _qualified(builder)


# -- 05-10 Task 1/2: anti-regression catalog over the store mixin surface,
# not the query-builder surface classified above. A future public store
# method that accepts `user_identifier` but omits the binding-aware guard
# must fail this test by name (D-18) -- mirrors the query-builder
# classification pattern's fail-on-unclassified-discovery shape.

STORE_MIXIN_MODULES: tuple[ModuleType, ...] = (
    store_memory_write,
    store_memory_read,
    store_search,
    store_documents,
    store_rebuild,
)


def _public_store_methods(module: ModuleType) -> list[Callable[..., object]]:
    methods: list[Callable[..., object]] = []
    for _name, klass in inspect.getmembers(module, inspect.isclass):
        if klass.__module__ != module.__name__:
            continue
        for method_name, candidate in inspect.getmembers(klass, inspect.isfunction):
            if method_name.startswith("_") or candidate.__module__ != module.__name__:
                continue
            if "user_identifier" in inspect.signature(candidate).parameters:
                methods.append(candidate)
    return methods


def test_every_public_store_method_requires_user() -> None:
    missing = sorted(
        f"{module.__name__}.{method.__qualname__}"
        for module in STORE_MIXIN_MODULES
        for method in _public_store_methods(module)
        if "_require_user(" not in inspect.getsource(method)
    )
    assert not missing, f"public store methods missing the _require_user guard: {missing}"
