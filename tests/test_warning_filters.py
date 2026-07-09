from __future__ import annotations

import warnings

from turing_agentmemory_mcp.warning_filters import suppress_fastmcp_authlib_warning


def test_suppress_fastmcp_authlib_warning_hides_only_known_third_party_warning() -> None:
    category: type[Warning] = Warning
    try:
        from authlib.deprecate import AuthlibDeprecationWarning

        category = AuthlibDeprecationWarning
    except Exception:
        pass
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("default")
        suppress_fastmcp_authlib_warning()

        warnings.warn(
            "authlib.jose module is deprecated, please use joserfc instead.\n"
            "It will be compatible before version 2.0.0.",
            category,
            stacklevel=1,
        )
        warnings.warn("unrelated provider warning", Warning, stacklevel=1)

    assert [str(item.message) for item in caught] == ["unrelated provider warning"]
