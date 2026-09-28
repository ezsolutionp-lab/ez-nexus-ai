"""
MO NEXUS OMEGA — Approval engine.

One gate for every high-impact action. Risk tier decides how many approvals are
needed and whether the approver must hold a multi-factor session. A requester
cannot approve their own request, and an expired or revoked approval does not
grant anything.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import ApprovalRequest
from ..errors import MoError, MoResult, ResultState


class RiskTier(str):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Required approvals, MFA requirement and validity window per tier.
TIER_POLICY: dict[str, dict[str, Any]] = {
    RiskTier.LOW:      {"approvals": 0, "mfa": False, "ttl_minutes": 60},
    RiskTier.MEDIUM:   {"approvals": 1, "mfa": False, "ttl_minutes": 240},
    RiskTier.HIGH:     {"approvals": 1, "mfa": True,  "ttl_minutes": 120},
    RiskTier.CRITICAL: {"approvals": 2, "mfa": True,  "ttl_minutes": 60},
}

# Actions the directive names as requiring approval (Instruction #1 §27).
ACTION_RISK: dict[str, str] = {
    "builder.deploy.production": RiskTier.CRITICAL,
    "builder.deploy.staging": RiskTier.HIGH,
    "builder.schema.destructive_migration": RiskTier.CRITICAL,
    "builder.agent.publish": RiskTier.MEDIUM,
    "builder.architecture.approve": RiskTier.MEDIUM,
    "data.delete.customer": RiskTier.CRITICAL,
    "comms.mass_send": RiskTier.HIGH,
    "security.policy.modify": RiskTier.CRITICAL,
    "identity.privilege_escalation": RiskTier.CRITICAL,
}


def risk_for(action: str) -> str:
    return ACTION_RISK.get(action, RiskTier.MEDIUM)


def request_approval(
    db: Session,
    ctx: RequestContext,
    *,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    reason: str = "",
    payload: Optional[dict[str, Any]] = None,
    risk_tier: Optional[str] = None,
) -> ApprovalRequest:
    tier = risk_tier or risk_for(action)
    policy = TIER_POLICY[tier]
    req = ApprovalRequest(
        tenant_id=ctx.tenant_id,
        created_by=ctx.actor_id,
        action=action,
        risk_tier=tier,
        resource_type=resource_type,
        resource_id=resource_id,
        requested_by=ctx.actor_id,
        reason=reason or None,
        payload_json=json.dumps(chain.redact(payload)) if payload else None,
        required_approvals=policy["approvals"],
        approvals_json="[]",
        status="PENDING" if policy["approvals"] else "APPROVED",
        expires_at=datetime.utcnow() + timedelta(minutes=policy["ttl_minutes"]),
        decided_at=None if policy["approvals"] else datetime.utcnow(),
    )
    db.add(req)
    db.flush()
    chain.record(
        db, ctx, action="approval.requested", result_state=ResultState.PENDING_APPROVAL,
        resource_type="approval", resource_id=req.id,
        detail=f"{action} ({tier})", payload={"action": action, "risk_tier": tier},
    )
    return req


def decide(
    db: Session,
    ctx: RequestContext,
    approval_id: str,
    *,
    approve: bool,
    note: str = "",
) -> MoResult:
    req = db.get(ApprovalRequest, approval_id)
    if req is None:
        return MoResult(ResultState.FAILED, f"Approval {approval_id} does not exist.")
    ctx.require_same_tenant(req.tenant_id, f"Approval {approval_id}")

    if req.status in {"APPROVED", "REJECTED", "REVOKED"}:
        return MoResult(ResultState.BLOCKED, f"Approval {approval_id} is already {req.status}.")
    if req.expires_at and datetime.utcnow() > req.expires_at:
        req.status = "EXPIRED"
        db.flush()
        return MoResult(ResultState.BLOCKED, f"Approval {approval_id} expired at {req.expires_at.isoformat()}Z.")

    policy = TIER_POLICY[req.risk_tier]
    if policy["mfa"] and not ctx.mfa_verified:
        return MoResult(
            ResultState.POLICY_DENIED,
            f"{req.risk_tier} approvals require a multi-factor verified session.",
        )
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator may decide an approval.")
    if ctx.actor_id == req.requested_by:
        return MoResult(
            ResultState.POLICY_DENIED,
            "The requester of an approval cannot approve it. A second party must decide.",
        )

    decisions: list[dict[str, Any]] = json.loads(req.approvals_json or "[]")
    if any(d["actor_id"] == ctx.actor_id for d in decisions):
        return MoResult(ResultState.BLOCKED, "You have already decided this approval.")

    if not approve:
        req.status = "REJECTED"
        req.decided_at = datetime.utcnow()
        decisions.append({"actor_id": ctx.actor_id, "approve": False, "note": note,
                          "at": datetime.utcnow().isoformat()})
        req.approvals_json = json.dumps(decisions)
        db.flush()
        chain.record(db, ctx, action="approval.rejected", result_state=ResultState.POLICY_DENIED,
                     resource_type="approval", resource_id=req.id, detail=note or req.action)
        return MoResult(ResultState.POLICY_DENIED, f"Approval for '{req.action}' was rejected.")

    decisions.append({"actor_id": ctx.actor_id, "approve": True, "note": note,
                      "at": datetime.utcnow().isoformat()})
    req.approvals_json = json.dumps(decisions)
    granted = sum(1 for d in decisions if d["approve"])
    if granted >= req.required_approvals:
        req.status = "APPROVED"
        req.decided_at = datetime.utcnow()
        db.flush()
        chain.record(db, ctx, action="approval.granted", result_state=ResultState.SUCCESS,
                     resource_type="approval", resource_id=req.id, detail=req.action)
        return MoResult.ok({"approval_id": req.id, "status": "APPROVED"})

    db.flush()
    remaining = req.required_approvals - granted
    return MoResult(
        ResultState.PENDING_APPROVAL,
        f"Recorded. {remaining} further approval(s) required for this {req.risk_tier} action.",
        meta={"approval_id": req.id, "granted": granted, "required": req.required_approvals},
    )


def revoke(db: Session, ctx: RequestContext, approval_id: str, reason: str = "") -> MoResult:
    req = db.get(ApprovalRequest, approval_id)
    if req is None:
        return MoResult(ResultState.FAILED, f"Approval {approval_id} does not exist.")
    ctx.require_same_tenant(req.tenant_id, f"Approval {approval_id}")
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator may revoke an approval.")
    req.status = "REVOKED"
    req.decided_at = datetime.utcnow()
    db.flush()
    chain.record(db, ctx, action="approval.revoked", result_state=ResultState.CANCELLED,
                 resource_type="approval", resource_id=req.id, detail=reason or "revoked")
    return MoResult.ok({"approval_id": req.id, "status": "REVOKED"})


def is_granted(db: Session, ctx: RequestContext, approval_id: Optional[str]) -> bool:
    """True only for an approval that is APPROVED, unexpired and same-tenant."""
    if not approval_id:
        return False
    req = db.get(ApprovalRequest, approval_id)
    if req is None or req.tenant_id != ctx.tenant_id:
        return False
    if req.status != "APPROVED":
        return False
    if req.expires_at and datetime.utcnow() > req.expires_at:
        return False
    return True


def require_granted(db: Session, ctx: RequestContext, approval_id: Optional[str], action: str) -> None:
    if not is_granted(db, ctx, approval_id):
        raise MoError(
            ResultState.APPROVAL_REQUIRED,
            f"'{action}' requires a valid, unexpired approval from a second party.",
            action=action,
        )
