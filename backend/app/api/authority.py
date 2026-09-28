"""
MO NEXUS OMEGA — authority API: capability requests, one-time grants, the execution gateway, receipts,
the validation council, agent registry, release pipeline, dependency provenance and the secrets vault.

Approvals themselves are decided at the existing /api/mo/approvals endpoints — this module never grants
one. A grant token is returned exactly once, to the person who requested the approval.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..mo.authority import gateway, grants
from ..mo.authority.policy import FINANCE_POLICY, FORBIDDEN_ACTIONS, TIER_FOR_RISK, Risk
from ..mo.compliance import provenance
from ..mo.context import RequestContext
from ..mo.council.validators import MANDATORY, VALIDATORS, run_council
from ..mo.db import ExecutionReceipt
from ..mo.errors import MoResult, ResultState
from ..mo.lifecycle import agents, releases
from ..mo.security.zero_trust import mo_router, resolve_context
from ..mo.vault import leases
from .platform import _read, _respond, _route, _write

PREFIX = "/api/mo/authority"
router = mo_router(PREFIX, ["mo-authority"], bucket="write")
read_router = mo_router(PREFIX, ["mo-authority"], bucket="read")
ALL_ROUTERS = [read_router, router]


def _risk(value: str) -> Optional[Risk]:
    try:
        return Risk(value.lower())
    except ValueError:
        return None


class CapabilityIn(BaseModel):
    tool: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=160)
    resource: str = Field(min_length=1, max_length=500)
    risk: str = Field(default="write", max_length=12)
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=1000)
    account_access: bool = False


class GrantIn(BaseModel):
    approval_id: str = Field(min_length=1, max_length=64)


class ExecuteIn(BaseModel):
    tool: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=160)
    resource: str = Field(min_length=1, max_length=500)
    risk: str = Field(default="none", max_length=12)
    args: dict[str, Any] = Field(default_factory=dict)
    args_hash: Optional[str] = Field(default=None, max_length=64)
    grant_token: Optional[str] = Field(default=None, max_length=200)
    idempotency_key: Optional[str] = Field(default=None, max_length=200)
    mission_id: Optional[str] = Field(default=None, max_length=64)
    agent: Optional[str] = Field(default=None, max_length=64)
    account_access: bool = False


class CouncilIn(BaseModel):
    risk: str = Field(default="none", max_length=12)
    output: Any = None
    acceptance: Optional[list[dict[str, Any]]] = Field(default=None, max_length=100)
    answer: Optional[str] = Field(default=None, max_length=200_000)
    evidence: Optional[list[dict[str, Any]]] = Field(default=None, max_length=200)
    code: Optional[str] = Field(default=None, max_length=200_000)
    claimed_receipts: Optional[list[Any]] = Field(default=None, max_length=100)


class AgentIn(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(default="", max_length=2000)
    allowed_tools: list[str] = Field(max_length=100)
    risk_ceiling: str = Field(default="write", max_length=12)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(ACTIVE|DISABLED)$")


class ReleaseIn(BaseModel):
    agent: str = Field(max_length=64)
    version: str = Field(max_length=64)
    manifest: dict[str, Any]


class EvalAttachIn(BaseModel):
    eval_run_id: str = Field(min_length=1, max_length=64)


class CanaryIn(BaseModel):
    metrics: dict[str, Any]
    thresholds: Optional[dict[str, Any]] = None


class RollbackIn(BaseModel):
    to_release_id: Optional[str] = Field(default=None, max_length=64)


class SbomIn(BaseModel):
    requirements: Optional[str] = Field(default=None, max_length=500_000)
    cyclonedx: Optional[dict[str, Any]] = None
    resolve_installed: bool = False


class ReviewIn(BaseModel):
    approve: bool
    notes: str = Field(default="", max_length=2000)


class LeaseIn(BaseModel):
    secret_id: str = Field(min_length=1, max_length=120)
    ttl_seconds: int = Field(default=leases.DEFAULT_TTL)


def _bad_risk() -> Any:
    return _respond(MoResult(ResultState.FAILED, "risk must be one of none, read, write, external, sensitive."))


# ── policy ──────────────────────────────────────────────────────────────────

@_route(read_router, "get", "/policy")
def get_policy(ctx: RequestContext = Depends(resolve_context)):
    _read(ctx)
    return {"forbidden_actions": sorted(FORBIDDEN_ACTIONS), "finance_policy": FINANCE_POLICY,
            "approval_tier_for_risk": {k.value: v for k, v in TIER_FOR_RISK.items()},
            "council": {"validators": list(VALIDATORS), "mandatory_by_risk": {k.value: sorted(v) for k, v in MANDATORY.items()}},
            "note": "Fixed in code. No tenant setting, agent or grant can lift the forbidden list."}


# ── capability request -> grant -> execute ──────────────────────────────────

@_route(router, "post", "/capabilities/request")
def capability_request(body: CapabilityIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    risk = _risk(body.risk)
    if risk is None:
        return _bad_risk()
    res = grants.request_capability(db, ctx, tool=body.tool, action=body.action, resource=body.resource, risk=risk,
                                    args=body.args, reason=body.reason, account_access=body.account_access)
    db.commit()
    return _respond(res)


@_route(router, "post", "/grants")
def issue_grant(body: GrantIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = grants.issue_grant(db, ctx, body.approval_id)
    db.commit()
    return _respond(res, created=True)


@_route(router, "post", "/execute")
def execute(body: ExecuteIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    risk = _risk(body.risk)
    if risk is None:
        return _bad_risk()
    res = gateway.execute(db, ctx, tool=body.tool, action=body.action, resource=body.resource, args=body.args,
                          args_hash=body.args_hash, risk=risk, grant_token=body.grant_token,
                          idempotency_key=body.idempotency_key, mission_id=body.mission_id, agent=body.agent,
                          account_access=body.account_access)
    db.commit()                      # refusals and failures are receipts too
    return _respond(res)


@_route(read_router, "get", "/receipts")
def list_receipts(tool: Optional[str] = Query(default=None, max_length=160), mission_id: Optional[str] = Query(default=None, max_length=64),
                  limit: int = Query(default=50, ge=1, le=200), ctx: RequestContext = Depends(resolve_context),
                  db: Session = Depends(get_db)):
    _read(ctx)
    q = db.query(ExecutionReceipt).filter(ExecutionReceipt.tenant_id == ctx.tenant_id)
    if tool:
        q = q.filter(ExecutionReceipt.tool == tool)
    if mission_id:
        q = q.filter(ExecutionReceipt.mission_id == mission_id)
    return {"receipts": [gateway.receipt_dict(r) for r in q.order_by(ExecutionReceipt.created_at.desc()).limit(limit).all()]}


@_route(read_router, "get", "/receipts/{receipt_id}")
def get_receipt(receipt_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    r = db.get(ExecutionReceipt, receipt_id)
    if r is None or r.tenant_id != ctx.tenant_id:
        return _respond(MoResult(ResultState.FAILED, f"No such receipt '{receipt_id}'."))
    return gateway.receipt_dict(r)


@_route(read_router, "get", "/traces/{trace_id}")
def trace_receipts(trace_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    rows = (db.query(ExecutionReceipt).filter(ExecutionReceipt.tenant_id == ctx.tenant_id,
                                              ExecutionReceipt.trace_id == trace_id)
            .order_by(ExecutionReceipt.created_at).all())
    return {"trace_id": trace_id, "receipts": [gateway.receipt_dict(r) for r in rows]}


@_route(read_router, "post", "/council/validate")
def council(body: CouncilIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    risk = _risk(body.risk)
    if risk is None:
        return _bad_risk()
    return run_council(db, ctx, risk=risk, output=body.output, acceptance=body.acceptance, answer=body.answer,
                       evidence=body.evidence, code=body.code, claimed_receipts=body.claimed_receipts)


# ── agents & releases ───────────────────────────────────────────────────────

@_route(read_router, "get", "/agents")
def list_agents(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return {"agents": agents.list_agents(db, ctx)}


@_route(router, "post", "/agents")
def register_agent(body: AgentIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = agents.register_agent(db, ctx, name=body.name, description=body.description,
                                allowed_tools=body.allowed_tools, risk_ceiling=body.risk_ceiling)
    db.commit()
    return _respond(res, created=True)


@_route(router, "post", "/agents/{name}/status")
def agent_status(name: str, body: StatusIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = agents.set_status(db, ctx, name, body.status)
    db.commit()
    return _respond(res)


@_route(router, "post", "/agents/{name}/rollback")
def rollback(name: str, body: RollbackIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = releases.rollback(db, ctx, name, body.to_release_id)
    db.commit()
    return _respond(res)


@_route(router, "post", "/releases")
def create_release(body: ReleaseIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = releases.create_release(db, ctx, agent=body.agent, version=body.version, manifest=body.manifest)
    db.commit()
    return _respond(res, created=True)


@_route(read_router, "get", "/releases")
def list_releases(agent: Optional[str] = Query(default=None, max_length=64), ctx: RequestContext = Depends(resolve_context),
                  db: Session = Depends(get_db)):
    _read(ctx)
    return {"releases": releases.list_releases(db, ctx, agent)}


@_route(read_router, "get", "/releases/{release_id}")
def get_release(release_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    r = releases.get_release(db, ctx, release_id)
    return r if r else _respond(MoResult(ResultState.FAILED, f"No such release '{release_id}'."))


def _stage(fn):
    def handler(release_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
        _write(ctx)
        res = fn(db, ctx, release_id)
        db.commit()
        return _respond(res)
    return handler


for _path, _fn in (("scan", releases.scan), ("approval", releases.request_release_approval),
                   ("promote", releases.promote)):
    _route(router, "post", f"/releases/{{release_id}}/{_path}")(_stage(_fn))


@_route(router, "post", "/releases/{release_id}/eval")
def release_eval(release_id: str, body: EvalAttachIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = releases.attach_eval(db, ctx, release_id, body.eval_run_id)
    db.commit()
    return _respond(res)


@_route(router, "post", "/releases/{release_id}/canary")
def release_canary(release_id: str, body: CanaryIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = releases.record_canary(db, ctx, release_id, body.metrics, body.thresholds)
    db.commit()
    return _respond(res)


# ── compliance ──────────────────────────────────────────────────────────────

@_route(router, "post", "/compliance/sbom")
def ingest_sbom(body: SbomIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = provenance.ingest_sbom(db, ctx, requirements=body.requirements, cyclonedx=body.cyclonedx,
                                 resolve_installed=body.resolve_installed)
    db.commit()
    return _respond(res, created=True)


@_route(read_router, "get", "/compliance/dependencies")
def list_dependencies(status: Optional[str] = Query(default=None, pattern="^(QUARANTINED|APPROVED|REJECTED)$"),
                      ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    from ..mo.db import DependencyRecord
    q = db.query(DependencyRecord).filter(DependencyRecord.tenant_id == ctx.tenant_id)
    if status:
        q = q.filter(DependencyRecord.status == status)
    return {"dependencies": [provenance.dependency_dict(r) for r in q.order_by(DependencyRecord.name).limit(1000).all()]}


@_route(read_router, "get", "/compliance/gate")
def compliance_gate(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return provenance.gate(db, ctx)


@_route(router, "post", "/compliance/dependencies/{dependency_id}/review")
def review_dependency(dependency_id: str, body: ReviewIn, ctx: RequestContext = Depends(resolve_context),
                      db: Session = Depends(get_db)):
    _write(ctx)
    res = provenance.review(db, ctx, dependency_id, approve=body.approve, notes=body.notes)
    db.commit()
    return _respond(res)


# ── vault ───────────────────────────────────────────────────────────────────

@_route(router, "post", "/vault/leases")
def vault_lease(body: LeaseIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = leases.lease(db, ctx, body.secret_id, body.ttl_seconds)
    db.commit()
    return _respond(res, created=True)


@_route(router, "delete", "/vault/leases/{lease_id}")
def vault_revoke(lease_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = leases.revoke(db, ctx, lease_id)
    db.commit()
    return _respond(res)
