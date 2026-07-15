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
from dataclasses import dataclass

from turing_agentmemory_mcp.tenant_identity import (
    TenantDatabaseIdentity,
    derive_tenant_database_identity,
)

TENANT_CORRELATION_KEY = "tenant_database"


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
