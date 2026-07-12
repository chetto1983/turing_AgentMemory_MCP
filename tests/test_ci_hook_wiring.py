"""Guards the hook + CI wiring contract (CI-01..CI-06, CI-08) against silent
deletion/regression by parsing the config files — never executing hooks or CI."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


def _repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return Path(__file__).resolve().parent.parent


ROOT = _repo_root()


def _load_yaml(rel: str) -> dict:
    path = ROOT / rel
    if not path.exists():
        pytest.fail(f"expected config file missing: {rel}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _commands_text(hook: dict) -> str:
    return yaml.safe_dump(hook.get("commands", {}))


def test_lefthook_pre_commit_wires_lint_format_and_file_size() -> None:
    cfg = _load_yaml("lefthook.yml")
    pre_commit = _commands_text(cfg["pre-commit"])
    assert "ruff format" in pre_commit
    assert "ruff-format" in cfg["pre-commit"]["commands"]
    assert "ruff check" in pre_commit
    assert "ruff-check" in cfg["pre-commit"]["commands"]
    assert "check-file-size.sh" in pre_commit


def test_lefthook_pre_push_wires_compile_tests_and_compose() -> None:
    cfg = _load_yaml("lefthook.yml")
    pre_push = _commands_text(cfg["pre-push"])
    assert "compileall" in pre_push
    assert "run-fast-tests.sh" in pre_push
    assert "docker compose config" in pre_push


def test_ci_jobs_are_exactly_the_five_wired_jobs() -> None:
    cfg = _load_yaml(".github/workflows/ci.yml")
    jobs = set(cfg["jobs"].keys())
    expected = {
        "lint",
        "unit-tests",
        "compose-validate",
        "supply-chain",
        "dockerized-integration",
    }
    assert jobs == expected, f"CI jobs drifted: {sorted(jobs)}"


def test_ci_supply_chain_pins_pip_audit() -> None:
    cfg = _load_yaml(".github/workflows/ci.yml")
    supply_chain = yaml.safe_dump(cfg["jobs"]["supply-chain"])
    assert "pip-audit==2.10.1" in supply_chain


def test_ci_lint_pins_ruff() -> None:
    cfg = _load_yaml(".github/workflows/ci.yml")
    lint = yaml.safe_dump(cfg["jobs"]["lint"])
    assert "ruff==0.15.21" in lint


def test_ci_unit_tests_enforces_coverage_floor_and_arms_guard() -> None:
    cfg = _load_yaml(".github/workflows/ci.yml")
    unit_tests = yaml.safe_dump(cfg["jobs"]["unit-tests"])
    assert "--cov-fail-under=78" in unit_tests
    assert "true" in unit_tests
    assert "CI" in unit_tests
