from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import FrozenInstanceError, fields

import pytest

from turing_agentmemory_mcp.tenant_identity import (
    TENANT_DATABASE_PREFIX,
    TENANT_NAMING_KEY_ENV,
    TENANT_NAMING_VERSION,
    TenantDatabaseIdentity,
    derive_tenant_database_identity,
    load_tenant_naming_key,
    tenant_key_fingerprint,
    validate_user_identifier,
)

_TEST_KEY = bytes(range(32))
_DOMAIN_SEPARATOR = b"turing-agentmemory/tenant-db/v1\x00"


def test_database_name_uses_full_hmac_sha256_digest() -> None:
    user_identifier = "T\u00e9nant@example.com"
    expected_digest = hmac.new(
        _TEST_KEY,
        _DOMAIN_SEPARATOR + user_identifier.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    identity = derive_tenant_database_identity(user_identifier, naming_key=_TEST_KEY)

    assert identity.database_name == f"{TENANT_DATABASE_PREFIX}{expected_digest}"
    assert identity.digest == expected_digest
    assert identity.naming_version == TENANT_NAMING_VERSION
    assert re.fullmatch(r"agentmem_t_v1_[0-9a-f]{64}", identity.database_name)


def test_database_identity_is_deterministic() -> None:
    first = derive_tenant_database_identity("tenant-alpha", naming_key=_TEST_KEY)
    second = derive_tenant_database_identity("tenant-alpha", naming_key=_TEST_KEY)

    assert first == second


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Tenant", "tenant"),
        ("caf\u00e9", "cafe\u0301"),
        ("tenant-a", "tenant-\u0430"),
    ],
    ids=["case", "composed-decomposed", "latin-cyrillic-lookalike"],
)
def test_exact_identifier_variants_derive_distinct_database_names(
    left: str,
    right: str,
) -> None:
    left_identity = derive_tenant_database_identity(left, naming_key=_TEST_KEY)
    right_identity = derive_tenant_database_identity(right, naming_key=_TEST_KEY)

    assert left_identity.database_name != right_identity.database_name


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "\u2003",
        " leading",
        "trailing ",
        "tenant\x00name",
        "tenant\nname",
        "tenant\x7fname",
        "tenant\x85name",
        "tenant\ud800name",
        "tenant\udfffname",
    ],
    ids=[
        "empty",
        "ascii-whitespace-only",
        "unicode-whitespace-only",
        "leading-whitespace",
        "trailing-whitespace",
        "nul-control",
        "newline-control",
        "delete-control",
        "c1-control",
        "high-surrogate",
        "low-surrogate",
    ],
)
def test_validator_rejects_invalid_identifiers(value: str) -> None:
    with pytest.raises(ValueError):
        validate_user_identifier(value)


@pytest.mark.parametrize("value", [None, 7, b"tenant"])
def test_validator_requires_a_string(value: object) -> None:
    with pytest.raises(ValueError):
        validate_user_identifier(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        "tenant alpha",
        "tenant\u00a0alpha",
        "tenant\u200dalpha",
        "tenant\ue000alpha",
        "tenant\u0378alpha",
        "cafe\u0301",
    ],
    ids=[
        "internal-ascii-space",
        "internal-nonbreaking-space",
        "format-control-cf",
        "private-use-co",
        "unassigned-cn",
        "combining-sequence",
    ],
)
def test_validator_preserves_valid_opaque_unicode(value: str) -> None:
    validated = validate_user_identifier(value)

    assert validated == value
    assert [ord(character) for character in validated] == [ord(character) for character in value]


def test_missing_naming_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TENANT_NAMING_KEY_ENV, raising=False)

    with pytest.raises(ValueError):
        load_tenant_naming_key()


@pytest.mark.parametrize("encoded", ["", "not base64!", "Zm9v\nYmFy", "===="])
def test_naming_key_rejects_malformed_base64(encoded: str) -> None:
    with pytest.raises(ValueError):
        load_tenant_naming_key(encoded)


@pytest.mark.parametrize("length", [0, 1, 31])
def test_naming_key_rejects_short_decoded_values(length: int) -> None:
    encoded = base64.b64encode(b"k" * length).decode("ascii")

    with pytest.raises(ValueError):
        load_tenant_naming_key(encoded)


def test_explicit_naming_key_is_used_without_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TENANT_NAMING_KEY_ENV, raising=False)
    encoded = base64.b64encode(_TEST_KEY).decode("ascii")

    assert load_tenant_naming_key(encoded) == _TEST_KEY


def test_naming_key_loads_from_the_named_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = base64.b64encode(_TEST_KEY).decode("ascii")
    monkeypatch.setenv(TENANT_NAMING_KEY_ENV, encoded)

    assert load_tenant_naming_key() == _TEST_KEY


def test_explicit_empty_key_does_not_fall_back_to_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TENANT_NAMING_KEY_ENV, base64.b64encode(_TEST_KEY).decode("ascii"))

    with pytest.raises(ValueError):
        load_tenant_naming_key("")


def test_key_fingerprint_is_stable_distinct_and_non_secret() -> None:
    fingerprint = tenant_key_fingerprint(_TEST_KEY)

    assert fingerprint == tenant_key_fingerprint(_TEST_KEY)
    assert fingerprint != tenant_key_fingerprint(b"x" * 32)
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    assert _TEST_KEY.hex() not in fingerprint
    assert base64.b64encode(_TEST_KEY).decode("ascii") not in fingerprint


def test_identity_object_has_only_pseudonymous_fields() -> None:
    assert [field.name for field in fields(TenantDatabaseIdentity)] == [
        "database_name",
        "digest",
        "naming_version",
        "key_fingerprint",
    ]
    identity = TenantDatabaseIdentity(
        database_name=f"{TENANT_DATABASE_PREFIX}{'a' * 64}",
        digest="a" * 64,
        naming_version=TENANT_NAMING_VERSION,
        key_fingerprint="b" * 64,
    )

    with pytest.raises(FrozenInstanceError):
        identity.digest = "c" * 64  # type: ignore[misc]


def test_identity_repr_does_not_expose_raw_identifier() -> None:
    raw_identifier = "private-tenant-identity@example.test"

    identity = derive_tenant_database_identity(raw_identifier, naming_key=_TEST_KEY)

    assert raw_identifier not in repr(identity)
    assert raw_identifier not in identity.database_name
    assert raw_identifier not in identity.digest
    assert raw_identifier not in identity.key_fingerprint


def test_validation_diagnostic_does_not_expose_raw_identifier() -> None:
    raw_identifier = " private-tenant-identity@example.test"

    with pytest.raises(ValueError) as error:
        validate_user_identifier(raw_identifier)

    assert raw_identifier not in str(error.value)
