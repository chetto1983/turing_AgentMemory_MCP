"""Tenant-bound store resolution and bounded in-process view reuse."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.tenant_identity import TenantDatabaseIdentity
from turing_agentmemory_mcp.tenant_provisioning import TenantManifest


@dataclass(frozen=True, slots=True)
class TenantStoreView:
    identity: TenantDatabaseIdentity | None
    manifest: TenantManifest | None
    memory: TuringAgentMemory


@runtime_checkable
class StoreResolver(Protocol):
    def resolve(self, user_identifier: str) -> TenantStoreView: ...


class StaticStoreResolver:
    def __init__(self, view: TenantStoreView | TuringAgentMemory) -> None:
        self._view = view

    def resolve(self, user_identifier: str) -> TenantStoreView:
        raise NotImplementedError


class TenantRouter:
    def __init__(
        self,
        provisioner: Any,
        shared_dependencies: Any,
        *,
        store_factory: Callable[..., TuringAgentMemory] = TuringAgentMemory,
        capacity: int = 128,
        idle_ttl_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provisioner = provisioner
        self.shared_dependencies = shared_dependencies
        self.store_factory = store_factory
        self.capacity = capacity
        self.idle_ttl_s = idle_ttl_s
        self.clock = clock
        self._inflight: dict[str, Future[TenantStoreView]] = {}

    def resolve(self, user_identifier: str) -> TenantStoreView:
        raise NotImplementedError

    def runtime_status(self) -> dict[str, object]:
        raise NotImplementedError

    def tenant_status(self, user_identifier: str) -> dict[str, object]:
        raise NotImplementedError


__all__ = ["StaticStoreResolver", "StoreResolver", "TenantRouter", "TenantStoreView"]
