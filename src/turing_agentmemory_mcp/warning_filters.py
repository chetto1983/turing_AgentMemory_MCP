from __future__ import annotations

import warnings


def suppress_fastmcp_authlib_warning() -> None:
    category: type[Warning] = Warning
    try:
        from authlib.deprecate import AuthlibDeprecationWarning

        category = AuthlibDeprecationWarning
    except Exception:
        pass
    warnings.filterwarnings(
        "ignore",
        message=r"^authlib\.jose module is deprecated, please use joserfc instead\.",
        category=category,
    )
