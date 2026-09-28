"""
MO NEXUS OMEGA — Secrets vault (lease broker).

Secrets stay in the process environment (or whatever the operator maps into it); they are never
copied into memory stores, results, audit records or API responses. A tool adapter asks for a
short-lived *lease* and resolves it in-process at the moment of use. A lease is bound to the
tenant and the requester, expires, and can be revoked.

Limits: the lease table is per process (a restart or another worker does not see it), and the
backing store is the environment — there is no HSM/KMS integration. Mappings come from
`MO_VAULT_SECRETS="id=ENV_VAR,id2=ENV_VAR2"` or `configure()`.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..errors import MoResult, ResultState

MAX_TTL = 900
DEFAULT_TTL = 300
MAX_LEASES = 10_000

_lock = threading.Lock()
_leases: dict[str, dict] = {}
_configured: dict[str, str] = {}


def configure(mapping: dict[str, str]) -> None:
    with _lock:
        _configured.update(mapping)


def reset() -> None:
    with _lock:
        _leases.clear()
        _configured.clear()


def _mapping() -> dict[str, str]:
    out = {}
    for pair in os.getenv("MO_VAULT_SECRETS", "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return {**out, **_configured}


def lease(db: Session, ctx: RequestContext, secret_id: str, ttl_seconds: int = DEFAULT_TTL) -> MoResult:
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= MAX_TTL:
        return MoResult(ResultState.FAILED, f"ttl_seconds must be between 1 and {MAX_TTL}.")
    env_var = _mapping().get(secret_id)
    if env_var is None:
        return MoResult(ResultState.FAILED, f"No such secret '{secret_id}' is registered.")
    if not os.getenv(env_var, "").strip():
        return MoResult.credential_required(f"secret {secret_id}", env_var)
    now = time.time()
    with _lock:
        for k in [k for k, v in _leases.items() if v["expires"] < now]:
            del _leases[k]
        if len(_leases) >= MAX_LEASES:
            return MoResult(ResultState.RATE_LIMITED, "Too many active leases.")
        lease_id = "ls_" + secrets.token_urlsafe(18)
        _leases[lease_id] = {"secret_id": secret_id, "env_var": env_var, "tenant": ctx.tenant_id,
                             "principal": ctx.actor_id, "expires": now + ttl_seconds}
    chain.record(db, ctx, action="vault.leased", result_state=ResultState.SUCCESS, resource_type="secret",
                 resource_id=secret_id, detail=f"ttl {ttl_seconds}s")
    return MoResult.ok({"lease_id": lease_id, "secret_id": secret_id, "expires_in": ttl_seconds,
                        "note": "The secret value is never returned; adapters resolve the lease in-process."})


def resolve(ctx: RequestContext, lease_id: str) -> str:
    """For tool adapters only. Raises PermissionError unless the lease is live and belongs to this caller."""
    with _lock:
        entry = _leases.get(lease_id)
    if entry is None or entry["expires"] < time.time():
        raise PermissionError("Lease is invalid or expired.")
    if entry["tenant"] != ctx.tenant_id or entry["principal"] != ctx.actor_id:
        raise PermissionError("Lease belongs to a different principal.")
    value = os.getenv(entry["env_var"], "")
    if not value:
        raise PermissionError("The secret is no longer available.")
    return value


def revoke(db: Session, ctx: RequestContext, lease_id: str) -> MoResult:
    with _lock:
        entry = _leases.get(lease_id)
        if entry is None or entry["tenant"] != ctx.tenant_id:
            return MoResult(ResultState.FAILED, f"No such lease '{lease_id}'.")
        if entry["principal"] != ctx.actor_id and not ctx.is_admin:
            return MoResult(ResultState.POLICY_DENIED, "Only the holder or an administrator can revoke a lease.")
        del _leases[lease_id]
    chain.record(db, ctx, action="vault.revoked", result_state=ResultState.SUCCESS, resource_type="secret",
                 resource_id=entry["secret_id"])
    return MoResult.ok({"lease_id": lease_id, "revoked": True})


def active_count() -> int:
    now = time.time()
    with _lock:
        return sum(1 for v in _leases.values() if v["expires"] >= now)
