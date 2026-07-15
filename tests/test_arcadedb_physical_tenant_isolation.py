"""Live database-per-tenant isolation proof for Phase 5."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity

_NAMING_KEY = b"0123456789abcdef0123456789abcdef"
_TENANTS = ("Tenant-A", "Tenant-B", "Tenant-C")
_IDENTITY_VARIANTS = (*_TENANTS, "tenant-a", "T\u0435nant-A")
_REQUIRED_OPERATIONS = {
    "memory_store",
    "memory_search",
    "memory_list",
    "memory_get",
    "memory_update",
    "memory_delete",
    "document_ingest",
    "document_search",
    "document_reindex",
    "document_delete",
}


@dataclass(frozen=True)
class _PhysicalIsolationProof:
    expected_databases: frozenset[str]
    listed_databases: frozenset[str] = frozenset()
    operations_by_tenant: dict[str, frozenset[str]] = field(default_factory=dict)
    record_tenants_by_database: dict[str, frozenset[str]] = field(default_factory=dict)
    manifest_databases: frozenset[str] = frozenset()
    foreign_attempts_denied: bool = False
    registry_bytes: bytes = b""
    diagnostic_text: str = ""
    invalid_identity_preserved_state: bool = False


def _run_physical_isolation_contract(_tmp_path: Path) -> _PhysicalIsolationProof:
    expected = frozenset(
        derive_tenant_database_identity(identity, naming_key=_NAMING_KEY).database_name
        for identity in _IDENTITY_VARIANTS
    )
    return _PhysicalIsolationProof(expected_databases=expected)


@pytest.mark.integration
def test_physical_three_tenant_database_and_predicate_isolation(tmp_path: Path) -> None:
    proof = _run_physical_isolation_contract(tmp_path)

    assert proof.expected_databases <= proof.listed_databases, (
        "the live harness must provision every derived opaque physical database"
    )
    for tenant in _TENANTS:
        assert proof.operations_by_tenant[tenant] >= _REQUIRED_OPERATIONS
        database_name = derive_tenant_database_identity(
            tenant, naming_key=_NAMING_KEY
        ).database_name
        assert proof.record_tenants_by_database[database_name] == frozenset({tenant})
    assert proof.foreign_attempts_denied
    assert proof.manifest_databases == proof.expected_databases

    for raw_identifier in _IDENTITY_VARIANTS:
        assert raw_identifier.encode() not in proof.registry_bytes
        assert raw_identifier not in proof.diagnostic_text
    assert proof.invalid_identity_preserved_state
