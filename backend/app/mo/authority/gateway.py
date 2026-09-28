"""
MO NEXUS OMEGA — Capability gateway.

The single door through which an agent's side effect runs. Order of checks:

  1. the arguments still hash to what was reviewed
  2. the caller-declared risk is raised to the tool's own floor (an agent cannot understate risk)
  3. the agent, when named, may use this tool at all (allow-list)
  4. MO policy: forbidden actions are refused, finance actions get strong confirmation
  5. idempotency: a repeated key returns the stored receipt and never runs the tool again
  6. a one-time grant bound to this exact request is spent (atomically)
  7. the ToolRegistry runs its own scope / MFA / rate-limit / schema checks and the handler

Every outcome — success, failure, refusal — leaves a receipt and an audit record.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import AgentDefinition, ExecutionReceipt
from ..errors import MoResult, ResultState
from ..tools.spec import ToolRegistry, get_tool_registry
from .grants import consume_grant, request_hash, stable_hash
from .policy import ALLOW, DENY, Risk, _RISK_ORDER, decide, effective_risk

MAX_IDEMPOTENCY_KEY = 200


def _receipt(db: Session, ctx: RequestContext, *, tool: str, action: str, resource: str, rhash: str,
             result: MoResult, mission_id: Optional[str], key: Optional[str], grant_id: Optional[str]) -> ExecutionReceipt:
    r = ExecutionReceipt(
        tenant_id=ctx.tenant_id, created_by=ctx.actor_id, trace_id=ctx.trace_id, mission_id=mission_id, tool=tool,
        action=action, resource=resource[:500], request_hash=rhash, idempotency_key=key, grant_id=grant_id,
        state=result.state.value, success=result.state.is_success,
        output_hash=stable_hash(chain.redact(result.data) if result.data is not None else result.detail),
        detail=(result.detail or "")[:1000])
    db.add(r)
    db.flush()
    chain.record(db, ctx, action="capability.executed" if r.success else "capability.refused_or_failed",
                 result_state=result.state, resource_type="receipt", resource_id=r.id,
                 detail=f"{tool}.{action}: {result.detail or result.state.value}"[:400],
                 payload={"tool": tool, "action": action, "trace_id": ctx.trace_id, "mission_id": mission_id})
    return r


_NOT_RUN_STATES = {ResultState.POLICY_DENIED, ResultState.APPROVAL_REQUIRED, ResultState.CREDENTIAL_REQUIRED,
                   ResultState.RATE_LIMITED}


def _reached_handler(result: MoResult) -> bool:
    if result.state in _NOT_RUN_STATES:
        return False
    return not (result.state == ResultState.FAILED and result.detail.startswith(("Invalid input", "No tool named")))


def receipt_dict(r: ExecutionReceipt) -> dict[str, Any]:
    return {"receipt_id": r.id, "trace_id": r.trace_id, "mission_id": r.mission_id, "tool": r.tool, "action": r.action,
            "resource": r.resource, "state": r.state, "success": r.success, "output_hash": r.output_hash,
            "idempotency_key": r.idempotency_key, "grant_id": r.grant_id, "detail": r.detail,
            "at": r.created_at.isoformat() + "Z" if r.created_at else None}


def execute(db: Session, ctx: RequestContext, *, tool: str, action: str, resource: str, args: dict[str, Any],
            args_hash: Optional[str] = None, risk: Risk = Risk.NONE, grant_token: Optional[str] = None,
            idempotency_key: Optional[str] = None, mission_id: Optional[str] = None, agent: Optional[str] = None,
            account_access: bool = False, registry: Optional[ToolRegistry] = None) -> MoResult:
    reg = registry or get_tool_registry()
    args = args or {}
    rhash_args = stable_hash(args)
    rhash = request_hash(tool, action, resource, rhash_args)

    def finish(result: MoResult, grant_id: Optional[str] = None, *, ran: bool = False) -> MoResult:
        # Only a call that reached the handler claims the idempotency key; a refusal leaves it free to retry.
        r = _receipt(db, ctx, tool=tool, action=action, resource=resource, rhash=rhash, result=result,
                     mission_id=mission_id, key=idempotency_key if ran else None, grant_id=grant_id)
        result.meta["receipt_id"] = r.id
        result.meta["trace_id"] = ctx.trace_id
        return result

    if idempotency_key is not None:
        if not idempotency_key or len(idempotency_key) > MAX_IDEMPOTENCY_KEY:
            return MoResult(ResultState.FAILED, f"idempotency_key must be 1-{MAX_IDEMPOTENCY_KEY} characters.")
        prior = (db.query(ExecutionReceipt).filter(ExecutionReceipt.tenant_id == ctx.tenant_id,
                                                   ExecutionReceipt.idempotency_key == idempotency_key).first())
        if prior is not None:
            if prior.request_hash != rhash:
                return MoResult(ResultState.BLOCKED, "That idempotency key was already used for a different request.")
            return MoResult(ResultState.SUCCESS if prior.success else ResultState(prior.state),
                            f"Replayed from receipt {prior.id}; the tool was not run again.",
                            data={"replayed": True, "output_hash": prior.output_hash},
                            meta={"receipt_id": prior.id, "replayed": True, "trace_id": prior.trace_id})

    if args_hash is not None and args_hash != rhash_args:
        return finish(MoResult(ResultState.POLICY_DENIED, "Arguments changed after review."))

    spec = reg.get(tool)
    if spec is None:
        return finish(MoResult(ResultState.FAILED, f"No tool named '{tool}' is registered."))

    if agent is not None:
        row = (db.query(AgentDefinition).filter(AgentDefinition.tenant_id == ctx.tenant_id,
                                                AgentDefinition.name == agent).first())
        if row is None or row.status != "ACTIVE":
            return finish(MoResult(ResultState.POLICY_DENIED, f"Agent '{agent}' is not registered and active."))
        if tool not in json.loads(row.allowed_tools_json):
            return finish(MoResult(ResultState.POLICY_DENIED, f"Agent '{agent}' is not allowed to use '{tool}'."))
        if _RISK_ORDER[effective_risk(risk, spec.risk_level)] > _RISK_ORDER[Risk(row.risk_ceiling.lower())]:
            return finish(MoResult(ResultState.POLICY_DENIED,
                                   f"This call exceeds agent '{agent}' risk ceiling of {row.risk_ceiling}."))

    eff = effective_risk(risk, spec.risk_level)
    decision = decide(tool, action, eff, account_access=account_access)
    if decision.verdict == DENY:
        return finish(MoResult(ResultState.POLICY_DENIED, decision.reason, meta={"decision": decision.to_dict()}))

    grant_id = None
    if decision.verdict != ALLOW:
        grant, why = consume_grant(db, ctx, grant_token or "", tool=tool, action=action, resource=resource,
                                   args_hash=rhash_args, required_tier=decision.tier)
        if grant is None:
            state = ResultState.APPROVAL_REQUIRED if not grant_token else ResultState.POLICY_DENIED
            return finish(MoResult(state, why or "MO approval required.", meta={"decision": decision.to_dict()}))
        grant_id = grant.id

    result = reg.invoke(ctx, tool, args, approval_granted=grant_id is not None)
    result.meta["risk"] = eff.value
    try:
        return finish(result, grant_id, ran=_reached_handler(result))
    except IntegrityError:                   # a concurrent call won the idempotency key
        db.rollback()
        return MoResult(ResultState.BLOCKED, "A concurrent call with this idempotency key is in progress.")
