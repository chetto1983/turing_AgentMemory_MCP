from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


_NAMING_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
_ROUTER_ENV = {
    "AGENTMEMORY_TENANT_CACHE_CAPACITY": "7",
    "AGENTMEMORY_TENANT_CACHE_IDLE_TTL_SECONDS": "45.5",
    "AGENTMEMORY_TENANT_PROVISION_ATTEMPTS": "4",
    "AGENTMEMORY_TENANT_PROVISION_BACKOFF_BASE_SECONDS": "0.125",
    "AGENTMEMORY_TENANT_PROVISION_BACKOFF_MAX_SECONDS": "1.5",
}
_TENANT_ENV_NAMES = (
    "AGENTMEMORY_TENANT_NAMING_KEY",
    "AGENTMEMORY_TENANT_REGISTRY_PATH",
    "AGENTMEMORY_TENANT_CACHE_CAPACITY",
    "AGENTMEMORY_TENANT_CACHE_IDLE_TTL_SECONDS",
    "AGENTMEMORY_TENANT_PROVISION_ATTEMPTS",
    "AGENTMEMORY_TENANT_PROVISION_BACKOFF_BASE_SECONDS",
    "AGENTMEMORY_TENANT_PROVISION_BACKOFF_MAX_SECONDS",
)


def _configure_router_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    registry_path = tmp_path / "registry" / "tenants.sqlite3"
    monkeypatch.setenv("AGENTMEMORY_TENANT_NAMING_KEY", _NAMING_KEY)
    monkeypatch.setenv("AGENTMEMORY_TENANT_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("TURINGDB_HOME", str(tmp_path))
    for name, value in _ROUTER_ENV.items():
        monkeypatch.setenv(name, value)
    return registry_path


def test_tenant_router_from_env_requires_explicit_strict_naming_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from turing_agentmemory_mcp import server

    monkeypatch.delenv("AGENTMEMORY_TENANT_NAMING_KEY", raising=False)

    with pytest.raises(ValueError, match="AGENTMEMORY_TENANT_NAMING_KEY is required"):
        server.tenant_router_from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENTMEMORY_TENANT_CACHE_CAPACITY", "0"),
        ("AGENTMEMORY_TENANT_CACHE_IDLE_TTL_SECONDS", "inf"),
        ("AGENTMEMORY_TENANT_PROVISION_ATTEMPTS", "0"),
        ("AGENTMEMORY_TENANT_PROVISION_BACKOFF_BASE_SECONDS", "nan"),
        ("AGENTMEMORY_TENANT_PROVISION_BACKOFF_MAX_SECONDS", "0"),
    ],
)
def test_tenant_router_from_env_rejects_unbounded_or_non_positive_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    from turing_agentmemory_mcp import server

    _configure_router_env(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        server.tenant_router_from_env()


def test_tenant_router_from_env_builds_shared_dependencies_without_bootstrapping_legacy_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from turing_agentmemory_mcp import server
    from turing_agentmemory_mcp.tenant_router import TenantRouter

    registry_path = _configure_router_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ARCADEDB_DATABASE", "legacy-shared-must-not-bootstrap")
    shared = object()

    class AssemblyStore:
        instances: list[AssemblyStore] = []

        def __init__(self, client: object, **kwargs: object) -> None:
            self.client = client
            self.kwargs = kwargs
            self.bootstrap_calls = 0
            self.__class__.instances.append(self)

        def shared_dependencies(self) -> object:
            return shared

        def bootstrap(self) -> None:
            self.bootstrap_calls += 1

    monkeypatch.setattr(server, "TuringAgentMemory", AssemblyStore)

    router = server.tenant_router_from_env()

    assert isinstance(router, TenantRouter)
    assert router.capacity == 7
    assert router.idle_ttl_s == 45.5
    assert router.shared_dependencies is shared
    assert router.store_factory is AssemblyStore
    assert router.provisioner.max_attempts == 4
    assert router.provisioner.retry_base_s == 0.125
    assert router.provisioner.retry_ceiling_s == 1.5
    assert router.provisioner.registry.path == registry_path
    assert router.provisioner.registry.runtime_status()["ready"] is True
    assert router.provisioner.base_client.database == "legacy-shared-must-not-bootstrap"
    assert len(AssemblyStore.instances) == 1
    assert AssemblyStore.instances[0].bootstrap_calls == 0


def test_create_mcp_app_static_store_bypasses_router_config_and_rejects_ambiguous_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from turing_agentmemory_mcp import server

    monkeypatch.delenv("AGENTMEMORY_TENANT_NAMING_KEY", raising=False)
    memory = SimpleNamespace(runtime_status=lambda: {"stages": {"graph": {"ready": True}}})
    captured: list[object] = []

    class RecordingStaticResolver:
        def __init__(self, store: object) -> None:
            captured.append(store)

        def runtime_status(self) -> dict[str, object]:
            return memory.runtime_status()

    monkeypatch.setattr(server, "StaticStoreResolver", RecordingStaticResolver)
    monkeypatch.setattr(server, "register_memory_tools", lambda *_args: None)
    monkeypatch.setattr(server, "register_document_tools", lambda *_args: None)

    app = server.create_mcp_app(store=memory, start_document_worker=False)

    assert app is not None
    assert captured == [memory]
    with pytest.raises(ValueError, match="store and resolver"):
        server.create_mcp_app(
            store=memory,
            resolver=SimpleNamespace(),
            start_document_worker=False,
        )


def test_global_health_uses_non_provisioning_resolver_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from turing_agentmemory_mcp import server

    class RecordingResolver:
        def __init__(self) -> None:
            self.resolve_calls = 0
            self.tenant_failure = True

        def resolve(self, _user_identifier: str) -> object:
            self.resolve_calls += 1
            raise AssertionError("global health must not resolve or provision a tenant")

        def runtime_status(self) -> dict[str, object]:
            return {
                "ready": True,
                "arcadedb": {"ready": True},
                "registry": {"ready": True},
                "router": {"ready": True},
            }

    resolver = RecordingResolver()
    monkeypatch.setattr(server, "register_memory_tools", lambda *_args: None)
    monkeypatch.setattr(server, "register_document_tools", lambda *_args: None)
    app = server.create_mcp_app(resolver=resolver, start_document_worker=False)

    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app.http_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json()["runtime"]["router"]["ready"] is True
    assert resolver.resolve_calls == 0


def test_compose_and_env_example_publish_required_router_settings_without_key_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    example = (root / ".env.example").read_text(encoding="utf-8")

    for name in _TENANT_ENV_NAMES:
        assert name in compose
        assert name in example
    assert "- AGENTMEMORY_TENANT_NAMING_KEY" in compose
    assert "AGENTMEMORY_TENANT_NAMING_KEY=${" not in compose
    assert "AGENTMEMORY_TENANT_NAMING_KEY=" in example
