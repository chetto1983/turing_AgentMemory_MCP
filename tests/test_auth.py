from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import yaml

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.server import auth_from_env, create_mcp_app

ROOT = Path(__file__).resolve().parents[1]


def test_auth_from_env_is_disabled_without_static_token(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMEMORY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AGENTMEMORY_AUTH_TOKENS", raising=False)

    assert auth_from_env() is None


def test_auth_from_env_builds_static_token_verifier(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "dev-secret")
    monkeypatch.setenv("AGENTMEMORY_AUTH_CLIENT_ID", "local-client")
    monkeypatch.setenv("AGENTMEMORY_AUTH_SCOPES", "memory:read,memory:write")
    monkeypatch.setenv("AGENTMEMORY_AUTH_REQUIRED_SCOPES", "memory:read")

    verifier = auth_from_env()

    assert verifier is not None
    accepted = asyncio.run(verifier.verify_token("dev-secret"))
    rejected = asyncio.run(verifier.verify_token("wrong-secret"))

    assert accepted is not None
    assert accepted.client_id == "local-client"
    assert accepted.scopes == ["memory:read", "memory:write"]
    assert rejected is None


def test_create_mcp_app_uses_static_auth_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKENS", "token-a,token-b")
    monkeypatch.setenv("AGENTMEMORY_AUTH_CLIENT_ID", "agentmemory")
    monkeypatch.delenv("AGENTMEMORY_AUTH_REQUIRED_SCOPES", raising=False)

    app = create_mcp_app(store=object())  # type: ignore[arg-type]

    assert app.auth is not None
    assert asyncio.run(app.auth.verify_token("token-a")) is not None
    assert asyncio.run(app.auth.verify_token("token-b")) is not None
    assert asyncio.run(app.auth.verify_token("token-c")) is None


def test_static_auth_is_documented_and_exposed_in_compose() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    env = set(compose["services"]["turing-agentmemory-mcp"]["environment"])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "AGENTMEMORY_AUTH_TOKEN" in env
    assert "AGENTMEMORY_AUTH_TOKENS" in env
    assert "AGENTMEMORY_AUTH_REQUIRED_SCOPES" in env
    assert "AGENTMEMORY_AUTH_TOKEN" in readme
    assert "Authorization: Bearer" in readme
