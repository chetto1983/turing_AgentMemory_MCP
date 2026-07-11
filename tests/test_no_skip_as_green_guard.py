"""Proves the conftest.py no-skip-as-green guard actually fires (D-04). Uses pytest's
own `pytester` fixture (the documented mechanism for testing conftest/plugin hooks) so the
probe test never pollutes the real collected suite."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_REPO_CONFTEST = Path(__file__).resolve().parent / "conftest.py"

_PROBE = """
import pytest

@pytest.mark.integration
def test_deliberately_skipped():
    pytest.skip("proves the no-skip-as-green guard fires under CI=true")
"""


def test_ci_guard_converts_a_marked_skip_into_a_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "true")
    pytester.makeconftest(_REPO_CONFTEST.read_text())
    pytester.makepyfile(_PROBE)
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*no-skip-as-green*"])


def test_without_ci_env_the_same_skip_still_passes_green(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    pytester.makeconftest(_REPO_CONFTEST.read_text())
    pytester.makepyfile(_PROBE)
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(skipped=1)
