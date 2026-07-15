"""Tenant-bound store resolution and bounded in-process view reuse."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.store_core import StoreSharedDependencies
from turing_agentmemory_mcp.tenant_binding import TenantBinding
from turing_agentmemory_mcp.tenant_identity import (
    TenantDatabaseIdentity,
    derive_tenant_database_identity,
    validate_user_identifier,
)
from turing_agentmemory_mcp.tenant_provisioning import (
    ProvisionedTenantDatabase,
    TenantManifest,
    TenantProvisioner,
)


@dataclass(frozen=True, slots=True)
class TenantStoreView:
    identity: TenantDatabaseIdentity | None
    manifest: TenantManifest | None
    memory: TuringAgentMemory


@runtime_checkable
class StoreResolver(Protocol):
    def resolve(self, user_identifier: str) -> TenantStoreView: ...

    def runtime_status(self) -> dict[str, object]: ...


class StaticStoreResolver:
    def __init__(self, view: TenantStoreView | TuringAgentMemory) -> None:
        self._view = (
            view if isinstance(view, TenantStoreView) else TenantStoreView(None, None, view)
        )

    def resolve(self, user_identifier: str) -> TenantStoreView:
        validate_user_identifier(user_identifier)
        return self._view

    def runtime_status(self) -> dict[str, object]:
        status = getattr(self._view.memory, "runtime_status", None)
        if callable(status):
            result = status()
            if isinstance(result, dict):
                return result
        return {"ready": True, "static_store": True}


@dataclass(slots=True)
class _CacheEntry:
    view: TenantStoreView
    last_access: float


class TenantRouter:
    def __init__(
        self,
        provisioner: TenantProvisioner,
        shared_dependencies: StoreSharedDependencies,
        *,
        store_factory: Callable[..., TuringAgentMemory] = TuringAgentMemory,
        capacity: int = 128,
        idle_ttl_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("tenant router capacity must be a positive integer")
        if (
            isinstance(idle_ttl_s, bool)
            or not isinstance(idle_ttl_s, (int, float))
            or not math.isfinite(idle_ttl_s)
            or idle_ttl_s <= 0
        ):
            raise ValueError("tenant router idle_ttl_s must be positive and finite")
        self.provisioner = provisioner
        self.shared_dependencies = shared_dependencies
        self.store_factory = store_factory
        self.capacity = capacity
        self.idle_ttl_s = idle_ttl_s
        self.clock = clock
        self._lock = threading.RLock()
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._inflight: dict[str, Future[TenantStoreView]] = {}

    def resolve(self, user_identifier: str) -> TenantStoreView:
        exact_identifier = validate_user_identifier(user_identifier)
        identity = self._identity(exact_identifier)
        database_name = identity.database_name
        now = self._now()
        leader = False
        with self._lock:
            self._prune_expired(now)
            entry = self._cache.get(database_name)
            if entry is not None:
                entry.last_access = now
                self._cache.move_to_end(database_name)
                return entry.view
            future = self._inflight.get(database_name)
            if future is None:
                future = Future()
                self._inflight[database_name] = future
                leader = True

        if not leader:
            return future.result()

        try:
            provisioned = self.provisioner.provision(exact_identifier)
            self._validate_provisioned(identity, provisioned)
            binding = TenantBinding(
                identity=provisioned.identity, naming_key=self.provisioner.naming_key
            )
            memory = self.store_factory(
                provisioned.client,
                shared_dependencies=self.shared_dependencies,
                tenant_binding=binding,
            )
            if getattr(memory, "client", None) is not provisioned.client:
                raise RuntimeError(f"tenant database {database_name} store client is not bound")
            if getattr(memory, "tenant_binding", None) is not binding:
                raise RuntimeError(f"tenant database {database_name} store binding is not bound")
            view = TenantStoreView(
                identity=provisioned.identity,
                manifest=provisioned.manifest,
                memory=memory,
            )
            with self._lock:
                now = self._now()
                self._prune_expired(now)
                self._cache[database_name] = _CacheEntry(view=view, last_access=now)
                self._cache.move_to_end(database_name)
                while len(self._cache) > self.capacity:
                    self._cache.popitem(last=False)
            future.set_result(view)
            return view
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                if self._inflight.get(database_name) is future:
                    del self._inflight[database_name]

    def runtime_status(self) -> dict[str, object]:
        try:
            base_ready = bool(self.provisioner.base_client.is_ready())
            base_status: dict[str, object] = {"ready": base_ready}
        except Exception as exc:
            base_ready = False
            base_status = {"ready": False, "error_type": type(exc).__name__}
        try:
            registry_status = dict(self.provisioner.registry.runtime_status())
            registry_ready = registry_status.get("ready") is True
        except Exception as exc:
            registry_ready = False
            registry_status = {"ready": False, "error_type": type(exc).__name__}
        with self._lock:
            cache_entries = len(self._cache)
            inflight_entries = len(self._inflight)
        return {
            "ready": base_ready and registry_ready,
            "arcadedb": base_status,
            "registry": registry_status,
            "router": {
                "ready": True,
                "capacity": self.capacity,
                "idle_ttl_s": self.idle_ttl_s,
                "cached_tenants": cache_entries,
                "inflight_tenants": inflight_entries,
            },
        }

    def tenant_status(self, user_identifier: str) -> dict[str, object]:
        exact_identifier = validate_user_identifier(user_identifier)
        database_name = self._identity(exact_identifier).database_name
        now = self._now()
        with self._lock:
            self._prune_expired(now)
            cached = database_name in self._cache
            in_flight = database_name in self._inflight
        record = self.provisioner.registry.get(database_name)
        return {
            "database_name": database_name,
            "cached": cached,
            "in_flight": in_flight,
            "registry_state": getattr(record, "state", "absent") if record else "absent",
        }

    def _identity(self, user_identifier: str) -> TenantDatabaseIdentity:
        return derive_tenant_database_identity(
            user_identifier,
            naming_key=self.provisioner.naming_key,
        )

    def _now(self) -> float:
        value = self.clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("tenant router clock must return a finite number")
        return float(value)

    def _prune_expired(self, now: float) -> None:
        expired = [
            database_name
            for database_name, entry in self._cache.items()
            if now - entry.last_access >= self.idle_ttl_s
        ]
        for database_name in expired:
            del self._cache[database_name]

    @staticmethod
    def _validate_provisioned(
        expected: TenantDatabaseIdentity,
        provisioned: ProvisionedTenantDatabase,
    ) -> None:
        database_name = expected.database_name
        if (
            provisioned.identity != expected
            or provisioned.manifest.database_name != database_name
            or getattr(provisioned.client, "database", None) != database_name
        ):
            raise RuntimeError(f"tenant database {database_name} binding does not match")


__all__ = ["StaticStoreResolver", "StoreResolver", "TenantRouter", "TenantStoreView"]
