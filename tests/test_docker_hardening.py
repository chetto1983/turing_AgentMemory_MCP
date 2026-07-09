from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PINNED_PYTHON_RE = re.compile(r"^FROM python:3\.14-slim@sha256:[a-f0-9]{64}$", re.MULTILINE)


def test_runtime_dockerfiles_pin_base_image_and_run_as_non_root() -> None:
    app = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    turingdb = (ROOT / "docker" / "turingdb.Dockerfile").read_text(encoding="utf-8")

    for dockerfile in (app, turingdb):
        assert PINNED_PYTHON_RE.search(dockerfile)
        assert "10001" in dockerfile
        assert "USER app" in dockerfile


def test_compose_declares_runtime_hardening_controls() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    for name in ("turingdb", "turing-agentmemory-mcp"):
        service = services[name]
        assert service["restart"] == "unless-stopped"
        assert "healthcheck" in service
        assert service["security_opt"] == ["no-new-privileges:true"]
        limits = service["deploy"]["resources"]["limits"]
        assert limits["cpus"]
        assert limits["memory"]

    app = services["turing-agentmemory-mcp"]
    assert app["read_only"] is True
    assert {"/tmp", "/run"} <= set(app["tmpfs"])


def test_compose_routes_non_root_runtime_caches_to_tmpfs() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    app_env = set(services["turing-agentmemory-mcp"]["environment"])
    assert "HOME=/tmp" in app_env
    assert "XDG_CACHE_HOME=/tmp/.cache" in app_env
    assert "PYTHONPYCACHEPREFIX=/tmp/pycache" in app_env

    e2e_env = services["e2e"]["environment"]
    assert e2e_env["RUFF_CACHE_DIR"] == "/tmp/ruff-cache"
    assert e2e_env["PYTHONPYCACHEPREFIX"] == "/tmp/pycache"


def test_e2e_writes_report_to_container_scratch_space() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    entrypoint = compose["services"]["e2e"]["entrypoint"]

    assert entrypoint[entrypoint.index("--out") + 1] == "/tmp/e2e-results.json"


def test_compose_repairs_legacy_volume_ownership_before_turingdb_start() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    init = services["turingdb-volume-init"]
    assert init["user"] == "0:0"
    assert init["restart"] == "no"
    assert init["entrypoint"] == ["/bin/sh", "-c", "chown -R 10001:10001 /turing"]

    turingdb_deps = services["turingdb"]["depends_on"]
    assert turingdb_deps["turingdb-volume-init"]["condition"] == "service_completed_successfully"
    assert services["turingdb"]["user"] == "10001:10001"


def test_readme_documents_backup_restore_and_build_attestation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Backup And Restore" in readme
    assert "docker run --rm -v turing-agentmemory-mcp_turing-data:/turing:ro" in readme
    assert "docker run --rm -v turing-agentmemory-mcp_turing-data:/turing" in readme
    assert "## Build Attestation" in readme
    assert "docker buildx build --provenance=true --sbom=true" in readme
