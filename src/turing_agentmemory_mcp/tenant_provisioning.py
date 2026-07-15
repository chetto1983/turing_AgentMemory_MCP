"""Ready-last provisioning for physically isolated tenant databases."""

from __future__ import annotations

import hmac
import math
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError

from .arcadedb_client import ArcadeDBClient, is_mvcc_conflict
from .arcadedb_schema import SchemaBootstrapConfig, bootstrap
from .tenant_identity import TenantDatabaseIdentity, derive_tenant_database_identity
from .tenant_registry import TENANT_STATE_READY, TenantRegistry, TenantRegistryRecord

TENANT_MANIFEST_SINGLETON_ID = "tenant-manifest-v1"
_ALREADY_EXISTS_MARKER = "already exists"
_STALE_REGISTRY_TRANSITION = "tenant registry has no matching provisioning tenant database"
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_MANIFEST_FIELDS = (
    "singleton_id",
    "database_name",
    "digest",
    "naming_version",
    "key_fingerprint",
    "schema_version",
    "created_at",
)
_MANIFEST_SELECT = (
    "SELECT "
    + ", ".join(_MANIFEST_FIELDS)
    + " FROM TenantManifest WHERE singleton_id = :singleton_id LIMIT 2"
)
_MANIFEST_INSERT = "CREATE VERTEX TenantManifest SET " + ", ".join(
    f"{field} = :{field}" for field in _MANIFEST_FIELDS
)


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
        self._validate_config()

    def provision(self, user_identifier: str) -> ProvisionedTenantDatabase:
        identity = derive_tenant_database_identity(user_identifier, naming_key=self.naming_key)
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._provision_once(identity)
            except Exception as exc:
                if not _is_transient(exc):
                    raise
                last_error = exc
                if attempt + 1 >= self.max_attempts:
                    break
                jitter = self.jitter()
                if (
                    isinstance(jitter, bool)
                    or not isinstance(jitter, (int, float))
                    or not math.isfinite(jitter)
                    or not 0 <= jitter <= 1
                ):
                    raise ValueError(
                        "tenant provisioning jitter must be between zero and one"
                    ) from exc
                delay = min(
                    self.retry_ceiling_s,
                    self.retry_base_s * (2**attempt) * (1.0 + jitter),
                )
                self.sleep(delay)
        raise TenantProvisioningError(
            f"tenant database {identity.database_name} exhausted transient provisioning retries"
        ) from last_error

    def _provision_once(self, identity: TenantDatabaseIdentity) -> ProvisionedTenantDatabase:
        now = self.clock()
        record = self.registry.begin_provisioning(
            identity.database_name,
            digest=identity.digest,
            created_at=now,
            updated_at=now,
        )
        expected = _expected_manifest(identity, record, self.schema_version)
        client = replace(self.base_client, database=identity.database_name)
        databases = client.list_databases()
        exists = identity.database_name in databases

        if record.state == TENANT_STATE_READY and not exists:
            raise TenantProvisioningError(
                f"ready tenant database {identity.database_name} is missing"
            )
        if not exists:
            try:
                client.create_database()
            except RuntimeError as exc:
                if _ALREADY_EXISTS_MARKER not in str(exc).lower():
                    raise
                if identity.database_name not in client.list_databases():
                    raise TenantProvisioningError(
                        f"tenant database {identity.database_name} create race was not reconciled"
                    ) from exc
                exists = True

        if exists:
            manifest = _read_manifest(client)
            if manifest is not None:
                _verify_manifest(expected, manifest)
                return self._finish(identity, client, manifest, record)
            if record.state == TENANT_STATE_READY:
                raise TenantProvisioningError(
                    f"ready tenant database {identity.database_name} manifest is missing"
                )

        self.bootstrap_schema(
            client,
            dimensions=self.dimensions,
            version=self.schema_version,
        )
        try:
            client.command(_MANIFEST_INSERT, params=asdict(expected))
        except RuntimeError as exc:
            if _ALREADY_EXISTS_MARKER not in str(exc).lower():
                raise
        manifest = _read_manifest(client)
        if manifest is None:
            raise TenantProvisioningError(
                f"tenant database {identity.database_name} manifest write was not durable"
            )
        _verify_manifest(expected, manifest)
        return self._finish(identity, client, manifest, record)

    def _finish(
        self,
        identity: TenantDatabaseIdentity,
        client: ArcadeDBClient,
        manifest: TenantManifest,
        record: TenantRegistryRecord,
    ) -> ProvisionedTenantDatabase:
        if record.state != TENANT_STATE_READY:
            try:
                self.registry.mark_ready(identity.database_name, updated_at=self.clock())
            except RuntimeError as exc:
                if str(exc) != _STALE_REGISTRY_TRANSITION:
                    raise
                current = self.registry.get(identity.database_name)
                if (
                    current is None
                    or current.state != TENANT_STATE_READY
                    or current.created_at != record.created_at
                ):
                    raise
        return ProvisionedTenantDatabase(identity=identity, client=client, manifest=manifest)

    def _validate_config(self) -> None:
        for name, value in (
            ("dimensions", self.dimensions),
            ("schema_version", self.schema_version),
            ("max_attempts", self.max_attempts),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"tenant provisioning {name} must be a positive integer")
        if (
            not isinstance(self.retry_base_s, (int, float))
            or isinstance(self.retry_base_s, bool)
            or not isinstance(self.retry_ceiling_s, (int, float))
            or isinstance(self.retry_ceiling_s, bool)
            or not math.isfinite(self.retry_base_s)
            or not math.isfinite(self.retry_ceiling_s)
            or self.retry_base_s < 0
            or self.retry_ceiling_s < 0
        ):
            raise ValueError("tenant provisioning retry delays must not be negative")
        if self.retry_ceiling_s < self.retry_base_s:
            raise ValueError("tenant provisioning retry ceiling must cover the base delay")


def _expected_manifest(
    identity: TenantDatabaseIdentity,
    record: TenantRegistryRecord,
    schema_version: int,
) -> TenantManifest:
    return TenantManifest(
        singleton_id=TENANT_MANIFEST_SINGLETON_ID,
        database_name=identity.database_name,
        digest=identity.digest,
        naming_version=identity.naming_version,
        key_fingerprint=identity.key_fingerprint,
        schema_version=schema_version,
        created_at=record.created_at,
    )


def _read_manifest(client: ArcadeDBClient) -> TenantManifest | None:
    rows = client.query(
        _MANIFEST_SELECT,
        params={"singleton_id": TENANT_MANIFEST_SINGLETON_ID},
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise TenantProvisioningError(f"tenant database {client.database} manifest is ambiguous")
    row = rows[0]
    try:
        return TenantManifest(
            singleton_id=_string_field(row, "singleton_id"),
            database_name=_string_field(row, "database_name"),
            digest=_string_field(row, "digest"),
            naming_version=_integer_field(row, "naming_version"),
            key_fingerprint=_string_field(row, "key_fingerprint"),
            schema_version=_integer_field(row, "schema_version"),
            created_at=_string_field(row, "created_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TenantProvisioningError(
            f"tenant database {client.database} manifest is malformed"
        ) from exc


def _verify_manifest(expected: TenantManifest, actual: TenantManifest) -> None:
    matches = (
        actual.singleton_id == expected.singleton_id
        and actual.database_name == expected.database_name
        and hmac.compare_digest(actual.digest, expected.digest)
        and actual.naming_version == expected.naming_version
        and hmac.compare_digest(actual.key_fingerprint, expected.key_fingerprint)
        and actual.schema_version == expected.schema_version
        and actual.created_at == expected.created_at
    )
    if not matches:
        raise TenantProvisioningError(
            f"tenant database {expected.database_name} manifest does not match"
        )


def _string_field(row: dict[str, object], name: str) -> str:
    value = row[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest {name} must be a non-empty string")
    return value


def _integer_field(row: dict[str, object], name: str) -> int:
    value = row[name]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"manifest {name} must be a positive integer")
    return value


def _is_transient(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, (URLError, TimeoutError, OSError)):
            return True
        if isinstance(current, HTTPError) and current.code in _RETRYABLE_HTTP_CODES:
            return True
        current = current.__cause__
    detail = str(exc)
    if is_mvcc_conflict(detail) or "ArcadeDB unavailable" in detail:
        return True
    return any(f"ArcadeDB HTTP {code}" in detail for code in _RETRYABLE_HTTP_CODES)
