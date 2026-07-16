from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("utcp")
pytest.importorskip("utcp_text")

# utcp/utcp_text are optional spike dependencies, not always installed. This
# module is unmarked (not integration/gpu) so CI's no-skip-as-green guard
# (which only enforces integration/gpu markers) never trips when spike deps are
# absent -- importorskip above is the only skip path, and it is not CI-enforced.

from turing_agentmemory_mcp.utcp import utcp_manual_from_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_manual_with_auth_fails_current_utcp_pydantic_validation(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMEMORY_UTCP_SERVER_NAME", "turing-agentmemory-mcp")
    monkeypatch.setenv("AGENTMEMORY_AUTH_TOKEN", "throwaway-dummy-token")
    manual = utcp_manual_from_env()

    from utcp.data.utcp_manual import UtcpManualSerializer
    from utcp.exceptions import UtcpSerializerValidationError

    try:
        UtcpManualSerializer().validate_dict(manual)
        raised = False
    except UtcpSerializerValidationError:
        raised = True
    assert raised, "expected api_key-on-mcp-template to fail current python-utcp validation"
    assert "throwaway-dummy-token" not in json.dumps(manual)


def test_readme_utcp_config_example_is_stale() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "call_template_type" in readme
    assert "file_path" in readme

    from utcp.exceptions import UtcpSerializerValidationError
    from utcp_text.text_call_template import TextCallTemplateSerializer

    try:
        TextCallTemplateSerializer().validate_dict(
            {"call_template_type": "text", "file_path": "some/path.json"}
        )
        raised = False
    except UtcpSerializerValidationError:
        raised = True
    assert raised, "README's UTCP_CONFIG_FILE example uses the deprecated file_path field"
