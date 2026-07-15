"""Exact, opaque tenant identity derivation for physical database routing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import unicodedata
from dataclasses import dataclass

TENANT_NAMING_VERSION = 1
TENANT_DATABASE_PREFIX = "agentmem_t_v1_"
TENANT_NAMING_KEY_ENV = "AGENTMEMORY_TENANT_NAMING_KEY"

_TENANT_DATABASE_DOMAIN = b"turing-agentmemory/tenant-db/v1\x00"
_TENANT_KEY_FINGERPRINT_DOMAIN = b"turing-agentmemory/tenant-key-fingerprint/v1\x00"
_MINIMUM_NAMING_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class TenantDatabaseIdentity:
    database_name: str
    digest: str
    naming_version: int
    key_fingerprint: str


def validate_user_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("user_identifier must be a string")
    if not value:
        raise ValueError("user_identifier is required")
    for character in value:
        code_point = ord(character)
        if 0xD800 <= code_point <= 0xDFFF:
            raise ValueError("user_identifier contains an invalid Unicode code point")
        if unicodedata.category(character) == "Cc":
            raise ValueError("user_identifier contains a control character")
    encoded = value.encode("utf-8")
    if not hmac.compare_digest(encoded, value.strip().encode("utf-8")):
        raise ValueError("user_identifier must not have surrounding whitespace")
    return value


def load_tenant_naming_key(encoded: str | None = None) -> bytes:
    configured = os.environ.get(TENANT_NAMING_KEY_ENV) if encoded is None else encoded
    if not isinstance(configured, str) or not configured:
        raise ValueError(f"{TENANT_NAMING_KEY_ENV} is required")
    try:
        key = base64.b64decode(configured, validate=True)
    except Exception as exc:
        raise ValueError(f"{TENANT_NAMING_KEY_ENV} must be strict base64") from exc
    return _require_naming_key(key)


def tenant_key_fingerprint(key: bytes) -> str:
    validated_key = _require_naming_key(key)
    return hashlib.sha256(_TENANT_KEY_FINGERPRINT_DOMAIN + validated_key).hexdigest()


def derive_tenant_database_identity(
    user_identifier: str,
    *,
    naming_key: bytes,
) -> TenantDatabaseIdentity:
    exact_identifier = validate_user_identifier(user_identifier)
    validated_key = _require_naming_key(naming_key)
    digest = hmac.new(
        validated_key,
        _TENANT_DATABASE_DOMAIN + exact_identifier.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return TenantDatabaseIdentity(
        database_name=f"{TENANT_DATABASE_PREFIX}{digest}",
        digest=digest,
        naming_version=TENANT_NAMING_VERSION,
        key_fingerprint=tenant_key_fingerprint(validated_key),
    )


def _require_naming_key(key: bytes) -> bytes:
    if not isinstance(key, bytes):
        raise ValueError("tenant naming key must be bytes")
    if len(key) < _MINIMUM_NAMING_KEY_BYTES:
        raise ValueError("tenant naming key must contain at least 32 bytes")
    return key
