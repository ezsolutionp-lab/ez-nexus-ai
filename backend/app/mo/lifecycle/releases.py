"""
MO NEXUS OMEGA — Agent release pipeline (also the self-improvement laboratory's promotion path).

    BUILD -> SCAN -> EVAL -> (approval) -> CANARY check -> VERIFY -> PROMOTE   |   any failed gate -> STOPPED

  BUILD    a release manifest is recorded and hashed. The tool manifest hash is computed by MO from
           the agent's allow-list; a client-supplied value that disagrees is rejected.
  SCAN     the manifest may not touch MO's authority code, must hold no secret, and the tenant's
           dependency register must be fully approved (compliance.provenance.gate).
  EVAL     a persisted, PASSED evaluation run from this tenant; its report is hashed into the release.
  APPROVAL a real MO approval (HIGH tier: multi-factor, second party) must be granted.
  CANARY   supplied canary measurements must meet the thresholds. MO does not split traffic or
           collect these numbers itself; it refuses to promote without them.
  PROMOTE  the release becomes the agent's active version. ROLLBACK re-activates a version that was
           previously promoted. This moves a registry pointer — it does not deploy anything.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..approvals import engine as approvals
from ..audit import chain
from ..compliance import provenance
from ..context import RequestContext
from ..db import AgentRelease, EvalRun
from ..errors import MoResult, ResultState
from ..guards import pii
from ..tools.spec import ToolRegistry, get_tool_registry
from . import agents

STAGES = ["BUILD", "SCAN", "EVAL", "VERIFY", "PROMOTE"]
# MAX / any candidate can never change these: they are MO's own authority.
IMMUTABLE_PREFIXES = ("app/mo/authority", "app/mo/approvals", "app/mo/audit", "app/mo/security", "app/mo/council",
                      "app/mo/lifecycle", "app/mo/compliance", "app/mo/vault", "app/mo/context.py", "app/mo/errors.py")
REQUIRED_MANIFEST = ("agent_version", "prompt_version", "model_policy_version", "skill_manifest_hash",
                     "security_policy_version")
DEFAULT_CANARY = {"min_samples": 50, "max_error_rate": 0.02, "max_p95_ms": None}


def _norm(path: str) -> str:
    p = posixpath.normpath(path.replace("\\", "/").lstrip("/"))
    for prefix in ("backend/", "./"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def touches_immutable(paths: list[str]) -> list[str]:
    hit = []
    for raw in paths:
        p = _norm(str(raw))
        if p.startswith("..") or ".." in p.split("/") or any(p == i or p.startswith(i.rstrip("/") + "/") for i in IMMUTABLE_PREFIXES):
            hit.append(str(raw))
    return hit


def release_dict(r: AgentRelease) -> dict[str, Any]:
    return {"id": r.id, "agent": r.agent_name, "version": r.version, "stage": r.stage, "status": r.status,
            "is_active": r.is_active, "manifest": json.loads(r.manifest_json), "manifest_hash": r.manifest_hash,
            "scan": json.loads(r.scan_json) if r.scan_json else None, "eval_run_id": r.eval_run_id,
            "eval_report_hash": r.eval_report_hash, "approval_id": r.approval_id,
            "canary": json.loads(r.canary_json) if r.canary_json else None,
            "previous_release_id": r.previous_release_id, "stop_reason": r.stop_reason}


def _load(db: Session, ctx: RequestContext, release_id: str) -> Optional[AgentRelease]:
    r = db.get(AgentRelease, release_id)
    return r if r is not None and r.tenant_id == ctx.tenant_id else None


def _stop(db: Session, ctx: RequestContext, r: AgentRelease, reason: str) -> MoResult:
    r.status, r.stop_reason = "STOPPED", reason
    db.flush()
    chain.record(db, ctx, action="release.stopped", result_state=ResultState.BLOCKED, resource_type="release",
                 resource_id=r.id, detail=reason[:300])
    return MoResult(ResultState.BLOCKED, f"Release stopped: {reason}", data=release_dict(r))


def _expect(r: AgentRelease, stage: str) -> Optional[MoResult]:
    if r.status != "IN_PROGRESS":
        return MoResult(ResultState.BLOCKED, f"Release is {r.status}; it cannot move further.")
    if r.stage != stage:
        return MoResult(ResultState.BLOCKED, f"Release is at stage {r.stage}; this step needs {stage}.")
    return None


def create_release(db: Session, ctx: RequestContext, *, agent: str, version: str, manifest: dict[str, Any],
                   registry: Optional[ToolRegistry] = None) -> MoResult:
    reg = registry or get_tool_registry()
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator can create a release.")
    a = agents.get_agent(db, ctx, agent)
    if a is None:
        return MoResult(ResultState.FAILED, f"No such agent '{agent}'.")
    if not isinstance(version, str) or not version.strip() or len(version) > 64:
        return MoResult(ResultState.FAILED, "version must be 1-64 characters.")
    if not isinstance(manifest, dict):
        return MoResult(ResultState.FAILED, "manifest must be an object.")
    missing = [k for k in REQUIRED_MANIFEST if not isinstance(manifest.get(k), str) or not manifest[k].strip()]
    if missing:
        return MoResult(ResultState.FAILED, f"manifest is missing: {', '.join(missing)}.")
    touches = manifest.get("touches", [])
    if not isinstance(touches, list) or not all(isinstance(t, str) for t in touches) or len(touches) > 1000:
        return MoResult(ResultState.FAILED, "manifest.touches must be a list of paths.")
    computed = agents.tool_manifest_hash(json.loads(a.allowed_tools_json), reg)
    if manifest.get("tool_manifest_hash") not in (None, computed):
        return MoResult(ResultState.FAILED, "tool_manifest_hash does not match the agent's registered tools.")
    if db.query(AgentRelease).filter(AgentRelease.tenant_id == ctx.tenant_id, AgentRelease.agent_name == agent,
                                     AgentRelease.version == version).first():
        return MoResult(ResultState.BLOCKED, f"Version {version} of '{agent}' already exists.")
    full = {**manifest, "tool_manifest_hash": computed}
    body = json.dumps(full, sort_keys=True)
    row = AgentRelease(tenant_id=ctx.tenant_id, created_by=ctx.actor_id, agent_name=agent, version=version,
                       manifest_json=body, manifest_hash=hashlib.sha256(body.encode()).hexdigest(), stage="BUILD")
    db.add(row)
    db.flush()
    chain.record(db, ctx, action="release.created", result_state=ResultState.SUCCESS, resource_type="release",
                 resource_id=row.id, detail=f"{agent}@{version}")
    return MoResult.ok(release_dict(row))


def scan(db: Session, ctx: RequestContext, release_id: str) -> MoResult:
    r = _load(db, ctx, release_id)
    if r is None:
        return MoResult(ResultState.FAILED, f"No such release '{release_id}'.")
    if (bad := _expect(r, "BUILD")):
        return bad
    manifest = json.loads(r.manifest_json)
    checks: dict[str, Any] = {}
    hit = touches_immutable(manifest.get("touches", []))
    checks["immutable_paths"] = {"passed": not hit, "touched": hit}
    secrets = pii.scan(r.manifest_json)
    checks["secrets"] = {"passed": not secrets, "kinds": sorted({f.kind for f in secrets})}
    deps = provenance.gate(db, ctx)
    checks["dependencies"] = deps
    r.scan_json = json.dumps(checks)
    failed = [k for k, v in checks.items() if not v["passed"]]
    if failed:
        return _stop(db, ctx, r, "scan failed: " + ", ".join(failed))
    r.stage = "SCAN"
    db.flush()
    chain.record(db, ctx, action="release.scanned", result_state=ResultState.SUCCESS, resource_type="release", resource_id=r.id)
    return MoResult.ok(release_dict(r))


def attach_eval(db: Session, ctx: RequestContext, release_id: str, eval_run_id: str) -> MoResult:
    r = _load(db, ctx, release_id)
    if r is None:
        return MoResult(ResultState.FAILED, f"No such release '{release_id}'.")
    if (bad := _expect(r, "SCAN")):
        return bad
    ev = db.get(EvalRun, eval_run_id)
    if ev is None or ev.tenant_id != ctx.tenant_id:
        return MoResult(ResultState.FAILED, f"No such evaluation run '{eval_run_id}'.")
    if ev.created_at and r.created_at and ev.created_at < r.created_at:
        return MoResult(ResultState.BLOCKED, "That evaluation ran before this release was built; run it again.")
    r.eval_run_id, r.eval_report_hash = ev.id, hashlib.sha256(ev.results_json.encode()).hexdigest()
    if not ev.passed:
        return _stop(db, ctx, r, f"evaluation '{ev.suite}' scored {ev.score:.0%}, below its {ev.threshold:.0%} threshold")
    r.stage = "EVAL"
    db.flush()
    chain.record(db, ctx, action="release.evaluated", result_state=ResultState.SUCCESS, resource_type="release",
                 resource_id=r.id, detail=ev.suite)
    return MoResult.ok(release_dict(r))


def request_release_approval(db: Session, ctx: RequestContext, release_id: str) -> MoResult:
    r = _load(db, ctx, release_id)
    if r is None:
        return MoResult(ResultState.FAILED, f"No such release '{release_id}'.")
    if (bad := _expect(r, "EVAL")):
        return bad
    if r.approval_id:
        return MoResult(ResultState.BLOCKED, "An approval was already requested for this release.")
    req = approvals.request_approval(db, ctx, action="release.promote", resource_type="release", resource_id=r.id,
                                     reason=f"Promote {r.agent_name}@{r.version}", risk_tier="HIGH",
                                     payload={"manifest_hash": r.manifest_hash, "eval_report_hash": r.eval_report_hash})
    r.approval_id = req.id
    db.flush()
    return MoResult(ResultState.PENDING_APPROVAL, "Waiting for a second party to approve this release.",
                    data={"approval_id": req.id}, meta={"approval_id": req.id})


def record_canary(db: Session, ctx: RequestContext, release_id: str, metrics: dict[str, Any],
                  thresholds: Optional[dict[str, Any]] = None) -> MoResult:
    r = _load(db, ctx, release_id)
    if r is None:
        return MoResult(ResultState.FAILED, f"No such release '{release_id}'.")
    if (bad := _expect(r, "EVAL")):
        return bad
    if not r.approval_id or not approvals.is_granted(db, ctx, r.approval_id):
        return MoResult(ResultState.APPROVAL_REQUIRED, "The release approval has not been granted.")
    limits = {**DEFAULT_CANARY, **(thresholds or {})}
    try:
        samples, err = int(metrics["samples"]), float(metrics["error_rate"])
        p95 = float(metrics["p95_ms"]) if metrics.get("p95_ms") is not None else None
    except (KeyError, TypeError, ValueError):
        return MoResult(ResultState.FAILED, "metrics needs numeric 'samples' and 'error_rate' (and optionally 'p95_ms').")
    if samples < 0 or not 0.0 <= err <= 1.0:
        return MoResult(ResultState.FAILED, "samples must be >= 0 and error_rate between 0 and 1.")
    problems = []
    if samples < limits["min_samples"]:
        problems.append(f"only {samples} samples (need {limits['min_samples']})")
    if err > limits["max_error_rate"]:
        problems.append(f"error rate {err:.2%} exceeds {limits['max_error_rate']:.2%}")
    if limits["max_p95_ms"] is not None and (p95 is None or p95 > limits["max_p95_ms"]):
        problems.append(f"p95 latency {p95} ms exceeds {limits['max_p95_ms']} ms")
    r.canary_json = json.dumps({"metrics": {"samples": samples, "error_rate": err, "p95_ms": p95}, "thresholds": limits,
                                "passed": not problems, "problems": problems,
                                "source": "caller-supplied; MO does not measure canary traffic"})
    if problems:
        return _stop(db, ctx, r, "canary failed: " + "; ".join(problems))
    r.stage = "VERIFY"
    db.flush()
    chain.record(db, ctx, action="release.canary_verified", result_state=ResultState.SUCCESS, resource_type="release", resource_id=r.id)
    return MoResult.ok(release_dict(r))


def promote(db: Session, ctx: RequestContext, release_id: str) -> MoResult:
    r = _load(db, ctx, release_id)
    if r is None:
        return MoResult(ResultState.FAILED, f"No such release '{release_id}'.")
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator can promote a release.")
    if (bad := _expect(r, "VERIFY")):
        return bad
    if not (r.eval_run_id and r.eval_report_hash and r.approval_id and approvals.is_granted(db, ctx, r.approval_id)):
        return _stop(db, ctx, r, "promotion gates are incomplete (evaluation or approval missing)")
    current = (db.query(AgentRelease).filter(AgentRelease.tenant_id == ctx.tenant_id, AgentRelease.agent_name == r.agent_name,
                                             AgentRelease.is_active.is_(True)).first())
    if current is not None:
        current.is_active = False
        r.previous_release_id = current.id
    r.is_active, r.stage, r.status = True, "PROMOTE", "PROMOTED"
    db.flush()
    chain.record(db, ctx, action="release.promoted", result_state=ResultState.SUCCESS, resource_type="release",
                 resource_id=r.id, detail=f"{r.agent_name}@{r.version}")
    return MoResult.ok(release_dict(r))


def rollback(db: Session, ctx: RequestContext, agent: str, to_release_id: Optional[str] = None) -> MoResult:
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator can roll back a release.")
    current = (db.query(AgentRelease).filter(AgentRelease.tenant_id == ctx.tenant_id, AgentRelease.agent_name == agent,
                                             AgentRelease.is_active.is_(True)).first())
    target_id = to_release_id or (current.previous_release_id if current else None)
    target = _load(db, ctx, target_id) if target_id else None
    if target is None or target.agent_name != agent:
        return MoResult(ResultState.FAILED, "No such earlier release to roll back to.")
    if target.stage != "PROMOTE":
        return MoResult(ResultState.BLOCKED, "Only a release that was promoted before can be restored as known-good.")
    if current is not None:
        if current.id == target.id:
            return MoResult(ResultState.BLOCKED, "That release is already active.")
        current.is_active, current.status = False, "ROLLED_BACK"
    target.is_active, target.status = True, "PROMOTED"
    db.flush()
    chain.record(db, ctx, action="release.rolled_back", result_state=ResultState.SUCCESS, resource_type="release",
                 resource_id=target.id, detail=f"{agent}: restored {target.version}")
    return MoResult.ok(release_dict(target))


def list_releases(db: Session, ctx: RequestContext, agent: Optional[str] = None) -> list[dict[str, Any]]:
    q = db.query(AgentRelease).filter(AgentRelease.tenant_id == ctx.tenant_id)
    if agent:
        q = q.filter(AgentRelease.agent_name == agent)
    return [release_dict(r) for r in q.order_by(AgentRelease.created_at.desc()).limit(200).all()]


def get_release(db: Session, ctx: RequestContext, release_id: str) -> Optional[dict[str, Any]]:
    r = _load(db, ctx, release_id)
    return release_dict(r) if r else None
