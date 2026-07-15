"""ARC-07 gap closure: keyed TenantBinding contract (05-09 Task 1)."""

from __future__ import annotations

import pytest

import turing_agentmemory_mcp.tenant_binding as tenant_binding_module
from turing_agentmemory_mcp.tenant_binding import (
    TENANT_CORRELATION_KEY,
    TenantBinding,
    TenantBindingError,
)
from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity

_KEY = bytes(range(32))
_OTHER_KEY = bytes(range(1, 33))


def _binding(user_identifier: str, *, naming_key: bytes = _KEY) -> TenantBinding:
    identity = derive_tenant_database_identity(user_identifier, naming_key=naming_key)
    return TenantBinding(identity=identity, naming_key=naming_key)


def test_bound_identifier_verifies_and_returns_exact_value() -> None:
    binding = _binding("Tenant-A")

    assert binding.verify("Tenant-A") == "Tenant-A"


def test_foreign_identifier_fails_closed_with_opaque_message() -> None:
    binding = _binding("Tenant-A")

    with pytest.raises(TenantBindingError) as excinfo:
        binding.verify("Tenant-B")

    message = str(excinfo.value)
    assert binding.identity.database_name in message
    assert "Tenant-B" not in message
    assert "Tenant-A" not in message


def test_invalid_identifier_rejected_before_digest_compare() -> None:
    binding = _binding("Tenant-A")

    for invalid in ("", "   ", " alice", "alice ", "ali\x00ce", "\ud800"):
        with pytest.raises(ValueError) as excinfo:
            binding.verify(invalid)
        assert not isinstance(excinfo.value, TenantBindingError)


def test_verify_reuses_central_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _binding("Tenant-A")
    calls: list[str] = []
    real = tenant_binding_module.derive_tenant_database_identity

    def observed(user_identifier: str, *, naming_key: bytes) -> object:
        calls.append(user_identifier)
        return real(user_identifier, naming_key=naming_key)

    monkeypatch.setattr(tenant_binding_module, "derive_tenant_database_identity", observed)

    assert binding.verify("Tenant-A") == "Tenant-A"
    assert calls == ["Tenant-A"]


def test_unicode_lookalike_identifiers_do_not_share_a_binding() -> None:
    cyrillic_e_lookalike = "Tеnant-A"  # Cyrillic e (U+0435), not Latin e
    latin = _binding("Tenant-A")
    cyrillic = _binding(cyrillic_e_lookalike)

    assert latin.identity.database_name != cyrillic.identity.database_name
    with pytest.raises(TenantBindingError):
        latin.verify(cyrillic_e_lookalike)
    with pytest.raises(TenantBindingError):
        cyrillic.verify("Tenant-A")


def test_correlation_returns_single_entry_keyed_by_database_name() -> None:
    binding = _binding("Tenant-A")

    assert binding.correlation() == {TENANT_CORRELATION_KEY: binding.identity.database_name}


def test_different_naming_keys_produce_incompatible_bindings() -> None:
    binding = _binding("Tenant-A", naming_key=_KEY)
    other_identity = derive_tenant_database_identity("Tenant-A", naming_key=_OTHER_KEY)
    foreign_binding = TenantBinding(identity=other_identity, naming_key=_OTHER_KEY)

    assert binding.identity.database_name != foreign_binding.identity.database_name
