from __future__ import annotations

import os

RETRYABLE_PROVIDER_CODES = frozenset({429, 500, 502, 503, 504, 529})


def provider_env(name: str, *, default: str = "") -> str:
    return os.environ.get(name, default)


def provider_secret(prefix: str, suffix: str = "API_KEY") -> str:
    specific = os.environ.get(f"{prefix}_{suffix}")
    if specific:
        return specific
    return os.environ.get(f"PROVIDER_{suffix}", "")


def provider_api_key_header(prefix: str) -> str:
    specific = os.environ.get(f"{prefix}_API_KEY_HEADER")
    if specific and specific.strip():
        return specific.strip()
    shared = os.environ.get("PROVIDER_API_KEY_HEADER")
    if shared and shared.strip():
        return shared.strip()
    return "Authorization"


def provider_api_key_scheme(prefix: str) -> str:
    specific = os.environ.get(f"{prefix}_API_KEY_SCHEME")
    if specific is not None:
        return specific.strip()
    shared = os.environ.get("PROVIDER_API_KEY_SCHEME")
    if shared is not None:
        return shared.strip()
    return "Bearer"


def provider_optional_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return int(value)


def api_key_header_value(api_key: str, scheme: str) -> str:
    if not scheme:
        return api_key
    return f"{scheme} {api_key}"


def store_embedding_dimensions(default: str = "768") -> str:
    value = os.environ.get("EMBED_DIMENSIONS")
    if value is not None:
        return value
    return default


def provider_error_code(payload: object) -> int:
    if not isinstance(payload, dict):
        return 0
    error = payload.get("error")
    if not isinstance(error, dict):
        return 0
    code = error.get("code")
    if isinstance(code, bool):
        return 0
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.strip().isdigit():
        return int(code.strip())
    return 0


def retryable_provider_code(code: int) -> bool:
    return code in RETRYABLE_PROVIDER_CODES
