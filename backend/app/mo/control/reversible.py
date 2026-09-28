"""
MO NEXUS OMEGA — Dry-run and rollback.

`dry_run` answers "what would happen if I ran this tool now?" by evaluating every
governance gate — scopes, MFA, approval, credentials, input schema, autonomy —
without invoking the handler. It never has side effects.

`ReversibleLog` records an executed action together with the governed tool call that
undoes it. `rollback` performs that call for real, through the ToolRegistry, so undo
is subject to the same approvals as any other action. A failed rollback is reported
as ROLLBACK_FAILED and demotes the subject's autonomy — it is never hidden.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import ReversibleAction
from ..errors import MoResult, ResultState
from ..tools.spec import get_tool_registry
from .autonomy import ALLOW, CONFIRM, DENY, AutonomyManager


def dry_run(db: Session, ctx: RequestContext, tool: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    registry = get_tool_registry()
    spec = registry.get(tool)
    if spec is None:
        return {"tool": tool, "would_run": False, "blockers": [f"No tool named '{tool}' is registered."]}
    payload = payload or {}
    blockers: list[str] = []
    notes: list[str] = []
    for scope in spec.required_scopes:
        if not (ctx.is_admin or scope in ctx.scopes):
            blockers.append(f"missing scope '{scope}'")
    if spec.requires_mfa and not ctx.mfa_verified:
        blockers.append("requires an MFA-verified session")
    if not spec.credential_satisfied:
        blockers.append(f"credential {spec.credential_env_var} is not set")
    problem = spec.validate_input(payload)
    if problem:
        blockers.append(f"invalid input: {problem}")
    if spec.requires_approval:
        notes.append(f"{spec.risk_level} risk: an approved request is required before it runs")
    verdict, why = AutonomyManager(db, ctx).decide(tool, spec.risk_level)
    if verdict == DENY:
        blockers.append(why)
    elif verdict == CONFIRM:
        notes.append(why)
    return {"tool": tool, "risk_level": spec.risk_level, "would_run": not blockers,
            "needs_approval": spec.requires_approval, "needs_human_confirmation": verdict == CONFIRM,
            "autonomy": verdict, "blockers": blockers, "notes": notes, "side_effects": False}


class ReversibleLog:
    def __init__(self, db: Session, ctx: RequestContext):
        self.db, self.ctx = db, ctx

    def record(self, action: str, *, resource: Optional[str] = None, undo_tool: Optional[str] = None,
               undo_payload: Optional[dict[str, Any]] = None) -> MoResult:
        if undo_tool and get_tool_registry().get(undo_tool) is None:
            return MoResult(ResultState.FAILED, f"Undo tool '{undo_tool}' is not registered; the action would not be reversible.")
        rec = ReversibleAction(tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, action=action,
                               resource=resource, undo_tool=undo_tool,
                               undo_payload_json=json.dumps(undo_payload or {}, default=str))
        self.db.add(rec)
        self.db.flush()
        return MoResult.ok({"reversible_id": rec.id, "reversible": bool(undo_tool)})

    def rollback(self, reversible_id: str, *, approval_granted: bool = False) -> MoResult:
        rec = self.db.get(ReversibleAction, reversible_id)
        if rec is None or rec.tenant_id != self.ctx.tenant_id:
            return MoResult(ResultState.FAILED, "No such reversible action.")
        if rec.status == "ROLLED_BACK":
            return MoResult(ResultState.BLOCKED, "This action was already rolled back.")
        if not rec.undo_tool:
            return MoResult(ResultState.BLOCKED, "This action recorded no undo instruction, so it cannot be rolled back.")
        result = get_tool_registry().invoke(self.ctx, rec.undo_tool, json.loads(rec.undo_payload_json),
                                            approval_granted=approval_granted)
        if result.state.is_success:
            rec.status, rec.rolled_back_at, rec.detail = "ROLLED_BACK", datetime.utcnow(), None
            outcome = MoResult.ok({"rolled_back": rec.id, "undo_tool": rec.undo_tool})
        elif result.state in (ResultState.APPROVAL_REQUIRED, ResultState.CREDENTIAL_REQUIRED,
                              ResultState.POLICY_DENIED, ResultState.RATE_LIMITED):
            # Not attempted: leave APPLIED so it can be retried once the gate is satisfied.
            outcome = MoResult(result.state, result.detail, meta=result.meta)
        else:
            rec.status, rec.detail = "ROLLBACK_FAILED", result.detail
            AutonomyManager(self.db, self.ctx).demote(rec.action, f"rollback failed: {result.detail[:120]}")
            outcome = MoResult(ResultState.FAILED, f"Rollback failed: {result.detail}")
        self.db.flush()
        chain.record(self.db, self.ctx, action="rollback", result_state=outcome.state,
                     resource_type="reversible_action", resource_id=rec.id, detail=outcome.detail,
                     payload={"undo_tool": rec.undo_tool})
        return outcome

    def list(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        q = self.db.query(ReversibleAction).filter(ReversibleAction.tenant_id == self.ctx.tenant_id)
        if status:
            q = q.filter(ReversibleAction.status == status)
        return [{"id": r.id, "action": r.action, "resource": r.resource, "undo_tool": r.undo_tool,
                 "status": r.status, "detail": r.detail} for r in q.order_by(ReversibleAction.created_at.desc()).all()]
