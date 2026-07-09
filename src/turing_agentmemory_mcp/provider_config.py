from __future__ import annotations

import os


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
    value = os.environ.get("TURINGDB_EMBED_DIMENSIONS")
    if value is not None:
        return value
    return default
