"""
MO NEXUS OMEGA — core control-plane routes and the JARVIS voice bridge.

The voice bridge exists to answer one question the directive is emphatic about
(§34): does a spoken command get the same treatment as an HTTP one? It does —
`/api/mo/voice/command` resolves the same RequestContext, calls the same
BuilderCompiler, and hits the same approval gates. There is no voice-only path
that skips policy.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..mo.approvals import engine as approvals
from ..mo.audit import chain
from ..mo.context import RequestContext, SourceChannel
from ..mo.db import ApprovalRequest, AuditEvent, BuilderProject
from ..mo.errors import MoError, ResultState
from ..mo.events import fabric as event_fabric
from ..mo.modelfabric.router import get_router as get_model_router
from ..mo.security.zero_trust import (
    PUBLIC_ROUTE_ALLOWLIST, audit_route_coverage, mo_router, rate_limit,
    require_admin, resolve_context,
)
from ..mo.tools.spec import get_tool_registry

public_router = APIRouter(prefix="/api/mo", tags=["mo-core"])
router = mo_router("/api/mo", ["mo-core"], bucket="read")
voice_router = mo_router("/api/mo/voice", ["mo-voice"], bucket="build")


@public_router.get("/health")
def mo_health() -> dict[str, Any]:
    """Unauthenticated liveness probe — the only open MO route besides the schema."""
    return {"status": "ok", "component": "mo-control-plane"}


@router.get("/status")
def mo_status(
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    model_health = get_model_router().health()
    tools = get_tool_registry().list()
    return {
        "tenant_id": ctx.tenant_id,
        "actor": {"id": ctx.actor_id, "label": ctx.actor_label,
                  "is_admin": ctx.is_admin, "mfa_verified": ctx.mfa_verified},
        "model_fabric": model_health,
        "tool_registry": {
            "count": len(tools),
            "credential_blocked": [t.name for t in tools if not t.credential_satisfied],
            "approval_gated": [t.name for t in tools if t.requires_approval],
        },
        "audit_events": db.query(AuditEvent).filter(
            AuditEvent.tenant_id == ctx.tenant_id).count(),
    }


@router.get("/audit/verify")
def verify_audit(
    ctx: RequestContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recompute the tenant's audit hash chain and report any break."""
    return chain.verify_chain(db, ctx.tenant_id)


@router.get("/audit/events")
def list_audit_events(
    limit: int = 100,
    ctx: RequestContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (db.query(AuditEvent)
            .filter(AuditEvent.tenant_id == ctx.tenant_id)
            .order_by(AuditEvent.seq.desc()).limit(min(limit, 500)).all())
    return [
        {"seq": r.seq, "occurred_at": r.occurred_at.isoformat(), "actor": r.actor_label or r.actor_id,
         "action": r.action, "resource": f"{r.resource_type}:{r.resource_id}" if r.resource_type else None,
         "result_state": r.result_state, "detail": r.detail, "source_channel": r.source_channel,
         "entry_hash": r.entry_hash[:16]}
        for r in rows
    ]


@router.get("/approvals")
def list_approvals(
    status: Optional[str] = None,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = db.query(ApprovalRequest).filter(ApprovalRequest.tenant_id == ctx.tenant_id)
    if status:
        q = q.filter(ApprovalRequest.status == status.upper())
    rows = q.order_by(ApprovalRequest.created_at.desc()).limit(200).all()
    return [
        {"id": a.id, "action": a.action, "risk_tier": a.risk_tier, "status": a.status,
         "resource": f"{a.resource_type}:{a.resource_id}" if a.resource_type else None,
         "requested_by": a.requested_by, "required_approvals": a.required_approvals,
         "expires_at": a.expires_at.isoformat() if a.expires_at else None,
         "reason": a.reason}
        for a in rows
    ]


@router.post("/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    payload: dict = Body(...),
    ctx: RequestContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = approvals.decide(db, ctx, approval_id, approve=bool(payload.get("approve", True)),
                              note=payload.get("note", ""))
    db.commit()
    if result.state in (ResultState.POLICY_DENIED, ResultState.BLOCKED, ResultState.FAILED):
        from .builder import raise_for_result
        raise raise_for_result(result)
    return result.to_dict()


@router.get("/security/route-coverage")
def route_coverage(
    request_scope: None = None,
    ctx: RequestContext = Depends(require_admin),
) -> dict[str, Any]:
    """Report any MO route reachable without authentication."""
    from ..main import app
    return audit_route_coverage(app)


@router.get("/events")
def list_events(
    topic: Optional[str] = None,
    limit: int = 100,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return event_fabric.replay(db, ctx.tenant_id, topic=topic, limit=min(limit, 500))


# ── JARVIS voice bridge (§34) ────────────────────────────────────────────────

# Spoken forms MO recognises, mapped to the same operations the HTTP API exposes.
VOICE_INTENTS: list[tuple[str, str]] = [
    (r"\b(build|create|make)\b.+", "builder.create_project"),
    (r"\b(show|open)\b.*\bpreview\b", "builder.preview"),
    (r"\brun\b.*\btests?\b", "builder.build"),
    (r"\bdeploy\b.*\bproduction\b", "builder.deploy.production"),
    (r"\bdeploy\b.*\b(staging|stage)\b", "builder.deploy.staging"),
    (r"\b(stop|halt|cancel)\b.*\bdeploy", "builder.deploy.cancel"),
    (r"\b(check|show)\b.*\b(health|status)\b", "mo.status"),
]


def classify_voice_intent(transcript: str) -> Optional[str]:
    text = (transcript or "").strip().lower()
    for pattern, intent in VOICE_INTENTS:
        if re.search(pattern, text):
            return intent
    return None


@voice_router.post("/command")
def voice_command(
    payload: dict = Body(...),
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Route a spoken command through the standard MO stack.

    The context is marked VOICE, but it is the *same* context type, resolved by
    the same dependency, carrying the same scopes and MFA state. A voice command
    to deploy hits the identical approval gate an HTTP request would.
    """
    transcript = (payload.get("transcript") or "").strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="transcript is required.")

    voice_ctx = RequestContext(
        tenant_id=ctx.tenant_id, actor_id=ctx.actor_id, actor_type=ctx.actor_type,
        actor_label=ctx.actor_label, is_admin=ctx.is_admin, scopes=ctx.scopes,
        source_channel=SourceChannel.VOICE, mfa_verified=ctx.mfa_verified,
        data_classification=ctx.data_classification, trace_id=ctx.trace_id,
        ip_address=ctx.ip_address,
    )

    intent = classify_voice_intent(transcript)
    chain.record(db, voice_ctx, action="voice.command",
                 result_state=ResultState.SUCCESS if intent else ResultState.FAILED,
                 detail=intent or "unrecognised", payload={"transcript": transcript[:300]})

    if intent is None:
        db.commit()
        return {"state": ResultState.FAILED.value, "intent": None,
                "detail": "I did not recognise that command.",
                "recognised_examples": [
                    "MO, build a plumbing business website.",
                    "MO, run the tests.",
                    "MO, show me the preview.",
                    "MO, deploy staging.",
                    "MO, check production health.",
                ]}

    if intent == "mo.status":
        db.commit()
        return {"state": ResultState.SUCCESS.value, "intent": intent,
                "result": mo_status(voice_ctx, db)}

    if intent == "builder.create_project":
        from .builder import WORKSPACE_ROOT
        from ..mo.builder.compiler import BuilderCompiler
        from ..mo.builder.intent import BuildIntent
        try:
            build_intent = BuildIntent(
                prompt=transcript, tenant_id=voice_ctx.tenant_id,
                requested_by=voice_ctx.actor_id, source_channel=SourceChannel.VOICE,
            )
        except MoError as exc:
            db.commit()
            from .builder import raise_for_error
            raise raise_for_error(exc)
        voice_ctx.require_scope("builder:write")
        compiler = BuilderCompiler(db, voice_ctx, workspace_root=WORKSPACE_ROOT)
        project, report = compiler.compile(build_intent, run_build=bool(payload.get("run_build", False)))
        db.commit()
        return {"state": report.state.value, "intent": intent,
                "project_id": project.id, "project_name": project.name,
                "spoken_response": (
                    f"I created {project.name} with "
                    f"{report.stages['REQUIREMENTS'].get('counts', {}).get('modules', 0)} modules and "
                    f"{report.stages['DATA_MODEL']['detail']}. "
                    "Deployment still needs your approval."
                ),
                "report": report.to_dict()}

    if intent.startswith("builder.deploy."):
        environment = intent.rsplit(".", 1)[1]
        project_id = payload.get("project_id")
        if not project_id:
            db.commit()
            return {"state": ResultState.FAILED.value, "intent": intent,
                    "detail": "Which project should I deploy? Say the project or pass project_id."}
        project = db.get(BuilderProject, project_id)
        if project is None or project.tenant_id != voice_ctx.tenant_id:
            db.commit()
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
        if environment == "cancel":
            db.commit()
            return {"state": ResultState.CANCELLED.value, "intent": intent,
                    "detail": "Deployment request cancelled."}
        from .builder import WORKSPACE_ROOT
        from ..mo.builder.compiler import BuilderCompiler
        compiler = BuilderCompiler(db, voice_ctx, workspace_root=WORKSPACE_ROOT)
        result = compiler.request_deployment(project, environment, "Requested by voice command")
        db.commit()
        return {"state": result.state.value, "intent": intent,
                "detail": result.detail, "meta": result.meta,
                "spoken_response": (
                    "That needs approval before it can go out. "
                    f"I've raised a {result.meta.get('risk_tier', 'MEDIUM')} risk approval request."
                )}

    db.commit()
    return {"state": ResultState.BLOCKED.value, "intent": intent,
            "detail": f"Intent '{intent}' is recognised but has no voice handler wired yet. "
                      "Use the corresponding HTTP endpoint."}


ALL_ROUTERS = [public_router, router, voice_router]
