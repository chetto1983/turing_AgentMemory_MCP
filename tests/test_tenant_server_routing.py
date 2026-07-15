from __future__ import annotations

import asyncio
import base64
import inspect
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
_FOREGROUND_DATA_CASES = (
    ("memory_store_message", {"session_id": "s", "role": "user", "content": "c"}, "store_message"),
    ("memory_store_messages", {"messages": [{"role": "user", "content": "c"}]}, "store_messages"),
    ("memory_rebuild_communities", {}, "rebuild_communities"),
    ("memory_rebuild_vector_projection", {}, "rebuild_vector_projection"),
    ("memory_get", {"memory_id": "m"}, "get_memory"),
    ("memory_list", {}, "list_memories"),
    ("memory_update", {"memory_id": "m"}, "update_memory"),
    ("memory_delete", {"memory_id": "m"}, "delete_memory"),
    ("memory_search", {"query": "q"}, "search_memory"),
    ("memory_get_context", {"query": "q"}, "get_context"),
    ("memory_add_entity", {"name": "n", "entity_type": "t"}, "add_entity"),
    ("memory_add_preference", {"category": "c", "preference": "p"}, "add_preference"),
    ("memory_add_fact", {"subject": "s", "predicate": "p", "object": "o"}, "add_fact"),
    ("document_ingest_text", {"title": "t", "text": "body"}, "ingest_document_text"),
    (
        "document_reindex_text",
        {"document_id": "d", "title": "t", "text": "body"},
        "reindex_document_text",
    ),
    ("document_delete", {"document_id": "d"}, "delete_document"),
    ("document_search", {"query": "q"}, "search_documents"),
)


class _CapturingApp:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def register(function: Any) -> Any:
            self.tools[function.__name__] = function
            return function

        return register


class _SerializableResult:
    def __init__(self, method: str) -> None:
        self.method = method

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method}


class _RecordingStore:
    _LIST_METHODS = {"store_messages", "list_memories", "search_memory", "search_documents"}
    _DICT_METHODS = {
        "rebuild_communities",
        "rebuild_vector_projection",
        "delete_memory",
        "get_context",
        "delete_document",
    }

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, method: str) -> Any:
        def call(**kwargs: object) -> object:
            self.calls.append((method, kwargs))
            if method in self._LIST_METHODS:
                return [_SerializableResult(method)]
            if method in self._DICT_METHODS:
                return {"method": method}
            return _SerializableResult(method)

        return call


class _RecordingResolver:
    def __init__(self) -> None:
        self.resolve_calls: list[str] = []
        self.runtime_calls = 0
        self.stores: dict[str, _RecordingStore] = {}

    def resolve(self, user_identifier: str) -> object:
        from turing_agentmemory_mcp.tenant_identity import validate_user_identifier

        exact = validate_user_identifier(user_identifier)
        self.resolve_calls.append(exact)
        store = self.stores.setdefault(exact, _RecordingStore())
        return SimpleNamespace(memory=store)

    def runtime_status(self) -> dict[str, object]:
        self.runtime_calls += 1
        return {"ready": True, "router": {"ready": True}}


def _registered_foreground_tools(resolver: object) -> _CapturingApp:
    from turing_agentmemory_mcp.server_document_tools import register_document_tools
    from turing_agentmemory_mcp.server_memory_tools import register_memory_tools

    app = _CapturingApp()
    register_memory_tools(app, resolver, lambda _tool: nullcontext())  # type: ignore[arg-type]
    register_document_tools(  # type: ignore[arg-type]
        app,
        resolver,
        SimpleNamespace(),
        lambda: SimpleNamespace(),
        lambda _tool: nullcontext(),
    )
    return app


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
    shared = SimpleNamespace(dimensions=768)

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


@pytest.mark.parametrize(
    ("tool_name", "arguments", "store_method"),
    _FOREGROUND_DATA_CASES,
    ids=[case[0] for case in _FOREGROUND_DATA_CASES],
)
def test_each_tenant_tool_resolves_once_and_passes_exact_identifier_to_store(
    tool_name: str,
    arguments: dict[str, object],
    store_method: str,
) -> None:
    exact_identifier = "Tenant-\u212b-\u03c2"
    resolver = _RecordingResolver()
    app = _registered_foreground_tools(resolver)

    app.tools[tool_name](**arguments, user_identifier=exact_identifier)

    assert resolver.resolve_calls == [exact_identifier]
    assert list(resolver.stores) == [exact_identifier]
    store_calls = resolver.stores[exact_identifier].calls
    assert len(store_calls) == 1
    assert store_calls[0][0] == store_method
    assert store_calls[0][1]["user_identifier"] == exact_identifier


def test_case_and_unicode_variants_select_distinct_views_without_transformation() -> None:
    identifiers = ("Tenant", "tenant", "Tenant-\u00c5", "Tenant-A\u030a")
    resolver = _RecordingResolver()
    app = _registered_foreground_tools(resolver)

    for identifier in identifiers:
        app.tools["memory_get"](memory_id="m", user_identifier=identifier)

    assert resolver.resolve_calls == list(identifiers)
    assert list(resolver.stores) == list(identifiers)
    for identifier in identifiers:
        assert resolver.stores[identifier].calls == [
            ("get_memory", {"memory_id": "m", "user_identifier": identifier})
        ]


@pytest.mark.parametrize("tool_name", ["memory_get", "document_search"])
@pytest.mark.parametrize("invalid_identifier", [" tenant", "tenant ", "ten\x00ant"])
def test_invalid_identity_fails_before_foreground_store_action(
    tool_name: str,
    invalid_identifier: str,
) -> None:
    resolver = _RecordingResolver()
    app = _registered_foreground_tools(resolver)
    arguments = {"memory_id": "m"} if tool_name == "memory_get" else {"query": "q"}

    with pytest.raises(ValueError):
        app.tools[tool_name](**arguments, user_identifier=invalid_identifier)

    assert resolver.resolve_calls == []
    assert resolver.stores == {}


def test_memory_runtime_status_uses_global_resolver_without_tenant_resolution() -> None:
    resolver = _RecordingResolver()
    app = _registered_foreground_tools(resolver)

    status = app.tools["memory_runtime_status"]()

    assert status == {"ready": True, "router": {"ready": True}}
    assert resolver.runtime_calls == 1
    assert resolver.resolve_calls == []


def test_foreground_registrars_depend_on_resolver_not_singleton_store() -> None:
    from turing_agentmemory_mcp import server_document_tools, server_memory_tools

    for module in (server_memory_tools, server_document_tools):
        source = inspect.getsource(module)
        assert "TuringAgentMemory" not in source
        assert "resolver.resolve" in source
