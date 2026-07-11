"""Central no-skip-as-green guard: under CI=true, a skip on a marked integration/gpu
tier is a failure, not a pass. See D-03/CI-07."""

from __future__ import annotations

import os

import pytest

_CI_ENFORCED_MARKERS = {"integration", "gpu"}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    outcome = yield
    if os.environ.get("CI") != "true":
        return
    report = outcome.get_result()
    if not report.skipped:
        return
    markers = {marker.name for marker in item.iter_markers()} & _CI_ENFORCED_MARKERS
    if not markers:
        return
    report.outcome = "failed"
    report.longrepr = (
        f"no-skip-as-green: {item.nodeid} skipped under CI=true (markers={sorted(markers)}). "
        "A skipped integration/gpu tier must never pass green in CI."
    )
