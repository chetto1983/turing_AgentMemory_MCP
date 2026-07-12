"""Guards the flagship 600-LOC cap (CI-01 / D-08): every tracked *.py file is within
the cap, no allowlist. Mirrors scripts/check-file-size.sh line-counting semantics
(wc -l == number of b"\\n" bytes)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

CAP = 600


def _repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f"git unavailable: {exc}")
    return Path(out.stdout.strip())


def _tracked_py_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f"git ls-files failed: {exc}")
    return [root / line for line in out.stdout.splitlines() if line.strip()]


def _wc_l(path: Path) -> int:
    return path.read_bytes().count(b"\n")


def test_every_tracked_py_file_within_cap() -> None:
    root = _repo_root()
    files = _tracked_py_files(root)
    assert files, "no tracked *.py files found — git enumeration is broken"
    offenders = [(f, _wc_l(f)) for f in files if f.is_file() and _wc_l(f) > CAP]
    detail = "\n".join(
        f"  OVER CAP: {f.relative_to(root).as_posix()} ({loc} LOC > {CAP})" for f, loc in offenders
    )
    assert not offenders, f"{len(offenders)} file(s) exceed the {CAP}-LOC cap:\n{detail}"


def test_cap_check_actually_fires_against_low_cap() -> None:
    root = _repo_root()
    files = _tracked_py_files(root)
    low_cap = 50
    over = [f for f in files if f.is_file() and _wc_l(f) > low_cap]
    assert over, (
        f"no tracked *.py file exceeds an artificially low cap of {low_cap} LOC — "
        "the line-counting check may be a no-op that passes everything"
    )
