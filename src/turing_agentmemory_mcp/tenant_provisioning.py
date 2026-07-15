"""Ready-last provisioning for physically isolated tenant databases."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .arcadedb_client import ArcadeDBClient
from .arcadedb_schema import SchemaBootstrapConfig, bootstrap
from .tenant_identity import TenantDatabaseIdentity
from .tenant_registry import TenantRegistry

TENANT_MANIFEST_SINGLETON_ID = "tenant-manifest-v1"


@dataclass(frozen=True, slots=True)
class TenantManifest:
    singleton_id: str
    database_name: str
    digest: str
    naming_version: int
    key_fingerprint: str
    schema_version: int
    created_at: str


@dataclass(frozen=True, slots=True)
class ProvisionedTenantDatabase:
    identity: TenantDatabaseIdentity
    client: ArcadeDBClient
    manifest: TenantManifest


class TenantProvisioningError(RuntimeError):
    """Content-safe failure while reconciling an opaque tenant database."""


BootstrapSchema = Callable[..., SchemaBootstrapConfig]
Clock = Callable[[], str]
Sleep = Callable[[float], None]
Jitter = Callable[[], float]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TenantProvisioner:
    def __init__(
        self,
        base_client: ArcadeDBClient,
        registry: TenantRegistry,
        *,
        naming_key: bytes,
        dimensions: int,
        schema_version: int = 1,
        max_attempts: int = 3,
        retry_base_s: float = 0.25,
        retry_ceiling_s: float = 2.0,
        clock: Clock = _utc_now,
        sleep: Sleep = time.sleep,
        jitter: Jitter = random.random,
        bootstrap_schema: BootstrapSchema = bootstrap,
    ) -> None:
        self.base_client = base_client
        self.registry = registry
        self.naming_key = naming_key
        self.dimensions = dimensions
        self.schema_version = schema_version
        self.max_attempts = max_attempts
        self.retry_base_s = retry_base_s
        self.retry_ceiling_s = retry_ceiling_s
        self.clock = clock
        self.sleep = sleep
        self.jitter = jitter
        self.bootstrap_schema = bootstrap_schema

    def provision(self, user_identifier: str) -> ProvisionedTenantDatabase:
        raise NotImplementedError
