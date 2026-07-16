"""Keyed logical-to-physical tenant binding (ARC-07 gap closure).

Physical database separation (`tenant_router.py`) has no logical counterpart
without this module: a routed store's `ArcadeDBClient` is bound to exactly one
tenant database, but nothing previously checked that the *caller-supplied*
`user_identifier` for a given request actually belongs to that database. A
`TenantBinding` closes that gap by recomputing the same keyed HMAC-SHA-256
digest `tenant_identity.derive_tenant_database_identity` used to name the
database, and comparing it in constant time before any client, span, or audit
activity runs. The digest is recomputable from `(user_identifier, naming_key)`,
so the binding never retains the raw identifier -- keeping the store
pseudonymous (D-07).
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass

from turing_agentmemory_mcp.tenant_identity import (
    TenantDatabaseIdentity,
    derive_tenant_database_identity,
)

TENANT_CORRELATION_KEY = "tenant_database"
TENANT_IDENTITY_KEYS = frozenset({"user_identifier", "identifier"})


class TenantBindingError(ValueError):
    """A valid-but-foreign identifier does not belong to the bound database."""


@dataclass(frozen=True, slots=True)
class TenantBinding:
    identity: TenantDatabaseIdentity
    naming_key: bytes

    def verify(self, user_identifier: str) -> str:
        # derive_tenant_database_identity runs validate_user_identifier first,
        # so an invalid identifier raises ValueError before any digest compare.
        candidate = derive_tenant_database_identity(user_identifier, naming_key=self.naming_key)
        if not hmac.compare_digest(
            candidate.digest.encode("utf-8"), self.identity.digest.encode("utf-8")
        ):
            raise TenantBindingError(
                f"user_identifier does not belong to tenant database {self.identity.database_name}"
            )
        # validate_user_identifier (invoked above via derive_tenant_database_identity)
        # returns its input unchanged when valid, so user_identifier is already exact.
        return user_identifier

    def correlation(self) -> dict[str, str]:
        return {TENANT_CORRELATION_KEY: self.identity.database_name}


def sanitize_tenant_attributes(
    attributes: Mapping[str, object] | None, binding: TenantBinding | None
) -> dict[str, object]:
    """Strip raw tenant-identity keys, then merge in the opaque correlation.

    This is the shared sanitizer `_StoreCore._span`/`_audit` call before
    anything reaches the process-wide observer or audit sink (ARC-07/D-07),
    so a mixin that still passes a raw identifier attribute cannot leak it.
    Stripping is key-based, not value-based: value scrubbing would need the
    raw identity in hand and would be defeated by substring or normalization
    differences. It does not reach into arbitrary strings -- that is the
    redactor's job (`governance.PatternRedactor`), a different threat.
    """
    clean = {
        str(key): _strip_nested_identity(value)
        for key, value in (attributes or {}).items()
        if str(key).lower() not in TENANT_IDENTITY_KEYS
    }
    if binding is not None:
        clean.update(binding.correlation())
    return clean


def _strip_nested_identity(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_nested_identity(item)
            for key, item in value.items()
            if str(key).lower() not in TENANT_IDENTITY_KEYS
        }
    return value
