"""Exact, opaque tenant identity derivation for physical database routing."""

from __future__ import annotations

from dataclasses import dataclass

TENANT_NAMING_VERSION = 1
TENANT_DATABASE_PREFIX = "agentmem_t_v1_"
TENANT_NAMING_KEY_ENV = "AGENTMEMORY_TENANT_NAMING_KEY"


@dataclass(frozen=True, slots=True)
class TenantDatabaseIdentity:
    database_name: str
    digest: str
    naming_version: int
    key_fingerprint: str


def validate_user_identifier(value: str) -> str:
    raise NotImplementedError


def load_tenant_naming_key(encoded: str | None = None) -> bytes:
    raise NotImplementedError


def tenant_key_fingerprint(key: bytes) -> str:
    raise NotImplementedError


def derive_tenant_database_identity(
    user_identifier: str,
    *,
    naming_key: bytes,
) -> TenantDatabaseIdentity:
    raise NotImplementedError
