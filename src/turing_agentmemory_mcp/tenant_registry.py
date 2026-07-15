"""Durable pseudonymous lifecycle state for tenant ArcadeDB databases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TENANT_REGISTRY_SCHEMA_VERSION = 1
TENANT_STATE_PROVISIONING = "provisioning"
TENANT_STATE_READY = "ready"


@dataclass(frozen=True, slots=True)
class TenantRegistryRecord:
    database_name: str
    digest: str
    state: str
    created_at: str
    updated_at: str


class TenantRegistry:
    def __init__(
        self,
        path: str | Path,
        *,
        naming_version: int,
        key_fingerprint: str,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.path = Path(path)
        self.naming_version = naming_version
        self.key_fingerprint = key_fingerprint
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        raise NotImplementedError

    def get(self, database_name: str) -> TenantRegistryRecord | None:
        raise NotImplementedError

    def begin_provisioning(
        self,
        database_name: str,
        *,
        digest: str,
        created_at: str,
        updated_at: str,
    ) -> TenantRegistryRecord:
        raise NotImplementedError

    def mark_ready(self, database_name: str, *, updated_at: str) -> TenantRegistryRecord:
        raise NotImplementedError

    def runtime_status(self) -> dict[str, object]:
        raise NotImplementedError
