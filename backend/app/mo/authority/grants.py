"""
MO NEXUS OMEGA — Capability requests and one-time grants.

`request_capability` raises a normal MO approval (so two-party, MFA and expiry rules all
apply) that records exactly what is being asked: tool, action, resource and the hash of the
arguments. After it is granted, `issue_grant` mints a token bound to that exact request. The
token is shown once; only its hash is stored. It works once, before it expires, for the same
tenant and the same arguments — change any of them and it is refused.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..approvals import engine as approvals
from ..audit import chain
from ..context import RequestContext
from ..db import ApprovalRequest, CapabilityGrant
from ..errors import MoResult, ResultState
from ..tools.spec import ToolRegistry, get_tool_registry
from .policy import DENY, Risk, decide, effective_risk

_TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

GRANT_TTL_SECONDS = 300


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def request_hash(tool: str, action: str, resource: str, args_hash: str) -> str:
    return stable_hash([tool, action, resource, args_hash])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def request_capability(db: Session, ctx: RequestContext, *, tool: str, action: str, resource: str, risk: Risk,
                       args: dict[str, Any], reason: str = "", account_access: bool = False,
                       registry: Optional[ToolRegistry] = None) -> MoResult:
    spec = (registry or get_tool_registry()).get(tool)
    if spec is None:
        return MoResult(ResultState.FAILED, f"No tool named '{tool}' is registered.")
    risk = effective_risk(risk, spec.risk_level)          # a caller cannot ask for a lighter approval than the tool needs
    decision = decide(tool, action, risk, account_access=account_access)
    if decision.verdict == DENY:
        chain.record(db, ctx, action="capability.denied", result_state=ResultState.POLICY_DENIED,
                     resource_type="capability", resource_id=f"{tool}.{action}", detail=decision.reason)
        return MoResult(ResultState.POLICY_DENIED, decision.reason, meta={"decision": decision.to_dict()})
    if decision.tier is None:
        return MoResult.ok({"decision": decision.to_dict(), "approval_id": None})
    args_hash = stable_hash(args)
    req = approvals.request_approval(
        db, ctx, action=f"capability:{tool}.{action}", resource_type="capability", resource_id=resource[:120],
        reason=reason or decision.reason, risk_tier=decision.tier,
        payload={"tool": tool, "action": action, "resource": resource, "args_hash": args_hash,
                 "risk": decision.risk.value})
    return MoResult(ResultState.PENDING_APPROVAL, "Waiting for approval.",
                    data={"approval_id": req.id, "args_hash": args_hash, "decision": decision.to_dict()},
                    meta={"approval_id": req.id})


def issue_grant(db: Session, ctx: RequestContext, approval_id: str) -> MoResult:
    req: Optional[ApprovalRequest] = db.get(ApprovalRequest, approval_id)
    if req is None or req.tenant_id != ctx.tenant_id:
        return MoResult(ResultState.FAILED, f"No such approval '{approval_id}'.")
    if not req.action.startswith("capability:") or not req.payload_json:
        return MoResult(ResultState.BLOCKED, "That approval is not a capability request.")
    if not approvals.is_granted(db, ctx, approval_id):
        return MoResult(ResultState.APPROVAL_REQUIRED, f"Approval {approval_id} is not granted (status {req.status}).")
    if req.requested_by != ctx.actor_id:
        return MoResult(ResultState.POLICY_DENIED, "Only the requester can collect the grant for their approval.")
    if db.query(CapabilityGrant).filter(CapabilityGrant.approval_id == approval_id).first():
        return MoResult(ResultState.BLOCKED, "A grant was already issued for this approval.")
    p = json.loads(req.payload_json)
    token = secrets.token_urlsafe(32)
    expires = min(datetime.utcnow() + timedelta(seconds=GRANT_TTL_SECONDS), req.expires_at or datetime.max)
    grant = CapabilityGrant(tenant_id=ctx.tenant_id, created_by=ctx.actor_id, approval_id=approval_id,
                            tool=p["tool"], action=p["action"], resource=p["resource"], args_hash=p["args_hash"],
                            token_hash=_token_hash(token), expires_at=expires)
    db.add(grant)
    db.flush()
    chain.record(db, ctx, action="grant.issued", result_state=ResultState.SUCCESS, resource_type="grant",
                 resource_id=grant.id, detail=f"{p['tool']}.{p['action']}")
    return MoResult.ok({"grant_id": grant.id, "token": token, "expires_at": expires.isoformat() + "Z",
                        "single_use": True, "note": "Shown once. Only its hash is stored."})


def consume_grant(db: Session, ctx: RequestContext, token: str, *, tool: str, action: str, resource: str,
                  args_hash: str, required_tier: Optional[str] = None) -> tuple[Optional[CapabilityGrant], Optional[str]]:
    """Atomically spend a grant. Returns (grant, None) or (None, reason). The check and the spend are one UPDATE."""
    if not token:
        return None, "MO approval required: no grant token supplied."
    row = db.query(CapabilityGrant).filter(CapabilityGrant.token_hash == _token_hash(token)).first()
    if row is None or row.tenant_id != ctx.tenant_id:
        return None, "Invalid grant."
    if row.used_at is not None:
        return None, "Grant already used."
    if row.expires_at < datetime.utcnow():
        return None, "Grant expired."
    if (row.tool, row.action, row.resource, row.args_hash) != (tool, action, resource, args_hash):
        return None, "Grant scope mismatch: it was issued for a different request or different arguments."
    if required_tier is not None:
        appr = db.get(ApprovalRequest, row.approval_id)
        if appr is None or _TIER_ORDER.get(appr.risk_tier, -1) < _TIER_ORDER[required_tier]:
            return None, f"Grant scope mismatch: this call needs a {required_tier} approval, but the grant came from a lower tier."
    spent = db.execute(update(CapabilityGrant)
                       .where(CapabilityGrant.id == row.id, CapabilityGrant.used_at.is_(None))
                       .values(used_at=datetime.utcnow())).rowcount
    if spent != 1:
        return None, "Grant already used."
    db.refresh(row)
    chain.record(db, ctx, action="grant.consumed", result_state=ResultState.SUCCESS, resource_type="grant",
                 resource_id=row.id, detail=f"{tool}.{action}")
    return row, None
