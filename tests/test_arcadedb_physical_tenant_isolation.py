"""Live database-per-tenant isolation and lifecycle proof for Phase 5."""

from __future__ import annotations

import pytest
from _arcadedb_physical_isolation_support import (
    _IDENTITY_VARIANTS,
    _NAMING_KEY,
    _REQUIRED_OPERATIONS,
    _TENANT_RECORD_TYPES,
    _TENANTS,
    _LiveEnvironment,
    _run_physical_isolation_contract,
    live_environment_context,
)

from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity


@pytest.fixture(scope="module")
def live_environment(tmp_path_factory: pytest.TempPathFactory):
    with live_environment_context(tmp_path_factory) as environment:
        yield environment


@pytest.mark.integration
def test_physical_three_tenant_database_and_predicate_isolation(
    live_environment: _LiveEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    proof = _run_physical_isolation_contract(live_environment, monkeypatch, caplog)

    assert proof.expected_databases <= proof.listed_databases
    for tenant in _TENANTS:
        assert proof.operations_by_tenant[tenant] >= _REQUIRED_OPERATIONS
        database_name = derive_tenant_database_identity(
            tenant, naming_key=_NAMING_KEY
        ).database_name
        assert proof.record_tenants_by_database[database_name] == frozenset({tenant})
        assert proof.bound_tenants_by_database[database_name] == frozenset({tenant})
        assert proof.tenant_types_checked[database_name] == _TENANT_RECORD_TYPES
    assert proof.foreign_attempts_denied
    assert proof.manifest_databases == proof.expected_databases

    for raw_identifier in _IDENTITY_VARIANTS:
        assert raw_identifier.encode() not in proof.registry_bytes
        assert raw_identifier not in proof.diagnostic_text
    assert proof.invalid_identity_preserved_state
