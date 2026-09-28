"""
MO NEXUS OMEGA — Request context.

Every MO execution surface (HTTP, voice, workflow, agent, builder) resolves a
RequestContext before doing work. There is no code path that performs a
tenant-scoped operation without one — that is what makes tenant isolation an
enforced boundary rather than an optional query filter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import MoError, ResultState


class SourceChannel(str):
    API = "API"
    VOICE = "VOICE"
    WORKFLOW = "WORKFLOW"
    AGENT = "AGENT"
    BUILDER = "BUILDER"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class RequestContext:
    """Identity + tenant + authority for a single unit of MO work."""

    tenant_id: str
    actor_id: str
    actor_type: str = "user"            # user | agent | system
    actor_label: str = ""
    is_admin: bool = False
    scopes: frozenset[str] = field(default_factory=frozenset)
    source_channel: str = SourceChannel.API
    mfa_verified: bool = False
    data_classification: str = "INTERNAL"   # PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ip_address: Optional[str] = None

    def require_scope(self, scope: str) -> None:
        """Raise POLICY_DENIED unless the caller holds `scope`."""
        if self.is_admin or scope in self.scopes:
            return
        raise MoError(
            ResultState.POLICY_DENIED,
            f"Actor {self.actor_label or self.actor_id} lacks required scope '{scope}'.",
            required_scope=scope,
            actor_id=self.actor_id,
        )

    def require_mfa(self, action: str) -> None:
        """Step-up check for HIGH/CRITICAL actions."""
        if self.mfa_verified:
            return
        raise MoError(
            ResultState.POLICY_DENIED,
            f"'{action}' requires a multi-factor verified session.",
            action=action,
        )

    def require_same_tenant(self, tenant_id: Optional[str], resource: str) -> None:
        """Raise POLICY_DENIED when a resource belongs to a different tenant."""
        if tenant_id is None:
            raise MoError(
                ResultState.POLICY_DENIED,
                f"{resource} has no tenant and cannot be accessed through a tenant-scoped context.",
                resource=resource,
            )
        if tenant_id != self.tenant_id:
            raise MoError(
                ResultState.POLICY_DENIED,
                f"{resource} belongs to another tenant.",
                resource=resource,
            )

    def child(self, *, actor_type: str, actor_label: str, source_channel: str) -> "RequestContext":
        """Derive a context for a subordinate actor (agent, workflow step).

        Scopes never widen: a derived actor holds at most what its parent held.
        """
        return RequestContext(
            tenant_id=self.tenant_id,
            actor_id=self.actor_id,
            actor_type=actor_type,
            actor_label=actor_label,
            is_admin=False,                 # derived actors never inherit admin
            scopes=self.scopes,
            source_channel=source_channel,
            mfa_verified=self.mfa_verified,
            data_classification=self.data_classification,
            trace_id=self.trace_id,
            ip_address=self.ip_address,
        )

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "actor_label": self.actor_label,
            "source_channel": self.source_channel,
            "trace_id": self.trace_id,
            "ip_address": self.ip_address,
            "mfa_verified": self.mfa_verified,
        }


SYSTEM_TENANT = "mo-system"


def system_context(label: str = "system", tenant_id: str = SYSTEM_TENANT) -> RequestContext:
    """Context for internal maintenance work. Not reachable from a request."""
    return RequestContext(
        tenant_id=tenant_id,
        actor_id="system",
        actor_type="system",
        actor_label=label,
        is_admin=True,
        scopes=frozenset({"*"}),
        source_channel=SourceChannel.SYSTEM,
        mfa_verified=True,
    )
