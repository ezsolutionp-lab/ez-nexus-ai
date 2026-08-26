"""
MO NEXUS OMEGA — Builder Studio HTTP API (Instruction #3 §39).

Every route here is built through `mo_router()`, so it is authenticated and
tenant-scoped by construction. `tests/security/test_zero_trust_coverage.py`
walks the live app and fails the build if any MO route is reachable anonymously.

Non-success results are returned with the HTTP status that matches their MoResult
state (424 for CREDENTIAL_REQUIRED, 202 for APPROVAL_REQUIRED, 422 for
TEST_FAILED, and so on) rather than a blanket 200 with an error body.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..mo.approvals import engine as approvals
from ..mo.audit import chain
from ..mo.builder import export as export_mod
from ..mo.builder import workflows as workflow_mod
from ..mo.builder.compiler import BuilderCompiler
from ..mo.builder.intent import IMPLEMENTED_STACKS, PLANNED_STACKS, BuildIntent
from ..mo.context import RequestContext
from ..mo.db import (
    AgentManifestRecord, BuilderAgent, BuilderApi, BuilderArchitecture, BuilderAssumption,
    BuilderBuild, BuilderDataModel, BuilderDeployment, BuilderFile, BuilderGraphNode,
    BuilderIntegration, BuilderPage, BuilderPreview, BuilderProject, BuilderRequirement,
    BuilderTestRun, BuilderWorkflow,
)
from ..mo.errors import MoError, MoResult, ResultState
from ..mo.modelfabric.router import get_router as get_model_router
from ..mo.security.zero_trust import mo_router, raise_for, require_admin, resolve_context
from ..mo.tools.spec import get_tool_registry

WORKSPACE_ROOT = Path(os.getenv("MO_BUILDER_WORKSPACE", "./mo_workspaces")).resolve()

router = mo_router("/api/mo/builder", ["mo-builder"], bucket="read")
build_router = mo_router("/api/mo/builder", ["mo-builder-build"], bucket="build")


def _compiler(db: Session, ctx: RequestContext) -> BuilderCompiler:
    return BuilderCompiler(db, ctx, workspace_root=WORKSPACE_ROOT)


def _project_or_404(db: Session, ctx: RequestContext, project_id: str) -> BuilderProject:
    project = db.get(BuilderProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.")
    try:
        ctx.require_same_tenant(project.tenant_id, f"Project {project_id}")
    except MoError as exc:
        # Do not disclose that a project exists in another tenant.
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found.") from exc
    return project


# ── Projects ─────────────────────────────────────────────────────────────────

@router.get("/stacks")
def list_stacks() -> dict[str, Any]:
    """Which stacks actually have a generator, and which are only planned."""
    return {
        "implemented": sorted(IMPLEMENTED_STACKS),
        "planned": sorted(PLANNED_STACKS),
        "note": "Only implemented stacks can be built. Requesting a planned stack "
                "returns BLOCKED rather than generating something that does not work.",
    }


@build_router.post("/projects", status_code=201)
def create_project(
    payload: dict = Body(...),
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compile a plain-English prompt into a project. Runs the full pipeline."""
    ctx.require_scope("builder:write")
    try:
        intent = BuildIntent.from_request(ctx, payload)
    except MoError as exc:
        raise raise_for_error(exc)

    run_build = bool(payload.get("run_build", True))
    project, report = _compiler(db, ctx).compile(intent, run_build=run_build)
    db.commit()
    return {"project": _project_dict(project), "report": report.to_dict()}


@router.get("/projects")
def list_projects(
    skip: int = 0, limit: int = 50,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(BuilderProject)
        .filter(BuilderProject.tenant_id == ctx.tenant_id)
        .order_by(BuilderProject.created_at.desc())
        .offset(skip).limit(min(limit, 200)).all()
    )
    return [_project_dict(p) for p in rows]


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, ctx, project_id)
    return _project_dict(project, detailed=True, db=db)


@router.get("/projects/{project_id}/requirements")
def get_requirements(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, ctx, project_id)
    reqs = db.query(BuilderRequirement).filter(
        BuilderRequirement.project_id == project.id).all()
    assumptions = db.query(BuilderAssumption).filter(
        BuilderAssumption.project_id == project.id).all()
    return {
        "requirements": [
            {"category": r.category, "key": r.key, "statement": r.statement,
             "acceptance_criteria": r.acceptance_criteria, "priority": r.priority,
             "source": r.source}
            for r in reqs
        ],
        "assumptions": [
            {"statement": a.statement, "rationale": a.rationale, "impact": a.impact,
             "confirmed_by": a.confirmed_by}
            for a in assumptions
        ],
    }


@router.get("/projects/{project_id}/architecture")
def get_architecture(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, ctx, project_id)
    arch = (db.query(BuilderArchitecture)
            .filter(BuilderArchitecture.project_id == project.id)
            .order_by(BuilderArchitecture.version.desc()).first())
    if arch is None:
        raise HTTPException(status_code=404, detail="No architecture has been planned yet.")
    return {
        "recommended": arch.recommended, "rationale": arch.rationale,
        "complexity": arch.complexity,
        "alternatives": json.loads(arch.alternatives_json),
        "tradeoffs": json.loads(arch.tradeoffs_json),
        "scores": json.loads(arch.scores_json),
        "infrastructure": json.loads(arch.infrastructure_json),
        "approved_by": arch.approved_by,
    }


@router.get("/projects/{project_id}/graph")
def get_graph(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, ctx, project_id)
    nodes = db.query(BuilderGraphNode).filter(
        BuilderGraphNode.project_id == project.id).all()
    return {
        "project_id": project.id,
        "node_count": len(nodes),
        "nodes": [
            {"key": n.node_key, "type": n.node_type, "label": n.label,
             "attributes": json.loads(n.attributes_json),
             "depends_on": json.loads(n.depends_on_json)}
            for n in nodes
        ],
    }


@router.get("/projects/{project_id}/files")
def list_files(
    project_id: str,
    path: Optional[str] = None,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List the generated files, or return one file's contents with `?path=`."""
    project = _project_or_404(db, ctx, project_id)
    if path:
        row = (db.query(BuilderFile)
               .filter(BuilderFile.project_id == project.id,
                       BuilderFile.version == project.current_version,
                       BuilderFile.path == path).first())
        if row is None:
            raise HTTPException(status_code=404, detail=f"No file '{path}' at this version.")
        return {"path": row.path, "language": row.language, "sha256": row.sha256,
                "content": row.content}
    return export_mod.export_manifest(db, ctx, project)


@router.get("/projects/{project_id}/apis")
def list_apis(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = db.query(BuilderApi).filter(BuilderApi.project_id == project.id).all()
    return [
        {"name": a.name, "protocol": a.protocol, "method": a.method, "path": a.path,
         "operation": a.operation, "data_model": a.data_model, "requires_auth": a.requires_auth,
         "rate_limit_per_minute": a.rate_limit_per_minute, "idempotent": a.idempotent,
         "version": a.version}
        for a in rows
    ]


@router.get("/projects/{project_id}/openapi")
def generated_openapi(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """An OpenAPI 3.1 description of the generated project's API surface."""
    project = _project_or_404(db, ctx, project_id)
    apis = db.query(BuilderApi).filter(BuilderApi.project_id == project.id).all()
    models = db.query(BuilderDataModel).filter(BuilderDataModel.project_id == project.id).all()

    paths: dict[str, dict[str, Any]] = {}
    for a in apis:
        entry = paths.setdefault(a.path, {})
        entry[a.method.lower()] = {
            "summary": a.name,
            "operationId": f"{a.operation}_{a.data_model}".lower(),
            "tags": [a.data_model or "default"],
            "security": [{"bearerAuth": []}] if a.requires_auth else [],
            "responses": {
                "200": {"description": "Success"},
                "401": {"description": "Authentication required"},
                "404": {"description": "Not found"},
                "429": {"description": "Rate limited"},
            },
        }
    schemas: dict[str, Any] = {}
    type_map = {"string": "string", "text": "string", "integer": "integer", "float": "number",
                "boolean": "boolean", "datetime": "string", "date": "string",
                "json": "object", "enum": "string"}
    for m in models:
        fields = json.loads(m.fields_json)
        schemas[m.name] = {
            "type": "object",
            "required": [f["name"] for f in fields if f.get("required")],
            "properties": {f["name"]: {"type": type_map.get(f["type"], "string")} for f in fields},
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": project.name, "version": f"1.0.{project.current_version}"},
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer",
                                               "bearerFormat": "JWT"}},
        },
    }


@router.get("/projects/{project_id}/agents")
def list_agents(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = db.query(BuilderAgent).filter(BuilderAgent.project_id == project.id).all()
    out = []
    for a in rows:
        manifest = db.get(AgentManifestRecord, a.manifest_id) if a.manifest_id else None
        out.append({
            "name": a.name, "role": a.role, "purpose": a.purpose, "status": a.status,
            "manifest_id": a.manifest_id,
            "canvas": json.loads(a.canvas_json),
            "tools": json.loads(manifest.tools_json) if manifest else [],
            "approval_gates": json.loads(manifest.approval_gates_json) if manifest else [],
            "test_report": json.loads(manifest.test_report_json)
            if manifest and manifest.test_report_json else None,
        })
    return out


@router.get("/projects/{project_id}/workflows")
def list_workflows(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = db.query(BuilderWorkflow).filter(BuilderWorkflow.project_id == project.id).all()
    return [
        {"id": w.id, "name": w.name, "trigger_type": w.trigger_type, "status": w.status,
         "nodes": json.loads(w.nodes_json)}
        for w in rows
    ]


@build_router.post("/workflows/{workflow_id}/run")
def run_workflow(
    workflow_id: str,
    payload: dict = Body(default={}),
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute a workflow for real. A node that cannot run reports why."""
    ctx.require_scope("builder:write")
    workflow = db.get(BuilderWorkflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found.")
    ctx.require_same_tenant(workflow.tenant_id, f"Workflow {workflow_id}")
    result = workflow_mod.execute_workflow(
        db, ctx, workflow,
        trigger_payload=payload.get("trigger_data"),
        approval_id=payload.get("approval_id"),
    )
    db.commit()
    if not result.state.is_success:
        raise raise_for_result(result)
    return result.to_dict()


@router.get("/projects/{project_id}/integrations")
def list_integrations(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = db.query(BuilderIntegration).filter(
        BuilderIntegration.project_id == project.id).all()
    return [
        {"provider": i.provider, "capability": i.capability, "auth_kind": i.auth_kind,
         "credential_env_var": i.credential_env_var, "status": i.status}
        for i in rows
    ]


# ── Build / test / preview ───────────────────────────────────────────────────

@build_router.post("/projects/{project_id}/build")
def build_project(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ctx.require_scope("builder:write")
    project = _project_or_404(db, ctx, project_id)
    result = _compiler(db, ctx).build(project)
    db.commit()
    if result.state in (ResultState.BUILD_FAILED, ResultState.TEST_FAILED,
                        ResultState.SECURITY_FAILED, ResultState.TIMEOUT):
        raise raise_for_result(result)
    return result.to_dict()


@router.get("/projects/{project_id}/builds")
def list_builds(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = (db.query(BuilderBuild).filter(BuilderBuild.project_id == project.id)
            .order_by(BuilderBuild.started_at.desc()).all())
    return [
        {"id": b.id, "version": b.version, "state": b.state,
         "stages": json.loads(b.stages_json), "duration_ms": b.duration_ms,
         "peak_rss_kb": b.peak_rss_kb, "exit_code": b.exit_code,
         "started_at": b.started_at.isoformat()}
        for b in rows
    ]


@router.get("/projects/{project_id}/tests")
def list_test_runs(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = db.query(BuilderTestRun).filter(BuilderTestRun.project_id == project.id).all()
    return [
        {"id": t.id, "suite": t.suite, "state": t.state, "total": t.total,
         "passed": t.passed, "failed": t.failed, "duration_ms": t.duration_ms,
         "report": t.report}
        for t in rows
    ]


@build_router.post("/projects/{project_id}/preview")
def create_preview(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ctx.require_scope("builder:write")
    project = _project_or_404(db, ctx, project_id)
    result = _compiler(db, ctx).preview(project)
    db.commit()
    if not result.state.is_success:
        raise raise_for_result(result)
    return result.to_dict()


# ── Deployment (always approval-gated) ───────────────────────────────────────

@build_router.post("/projects/{project_id}/deploy/request")
def request_deploy(
    project_id: str,
    payload: dict = Body(default={}),
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ctx.require_scope("builder:write")
    project = _project_or_404(db, ctx, project_id)
    result = _compiler(db, ctx).request_deployment(
        project, payload.get("environment", "staging"), payload.get("reason", ""))
    db.commit()
    # APPROVAL_REQUIRED is the expected outcome here — return it as 202, not an error.
    return result.to_dict()


@build_router.post("/projects/{project_id}/deploy/approve")
def approve_deploy(
    project_id: str,
    payload: dict = Body(...),
    ctx: RequestContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve a pending deployment. The requester cannot approve their own."""
    project = _project_or_404(db, ctx, project_id)
    approval_id = payload.get("approval_id")
    if not approval_id:
        raise HTTPException(status_code=422, detail="approval_id is required.")
    result = approvals.decide(db, ctx, approval_id, approve=bool(payload.get("approve", True)),
                              note=payload.get("note", ""))
    db.commit()
    if result.state in (ResultState.POLICY_DENIED, ResultState.BLOCKED, ResultState.FAILED):
        raise raise_for_result(result)
    return result.to_dict()


@build_router.post("/projects/{project_id}/deploy/execute")
def execute_deploy(
    project_id: str,
    payload: dict = Body(...),
    ctx: RequestContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, ctx, project_id)
    deployment_id = payload.get("deployment_id")
    if not deployment_id:
        raise HTTPException(status_code=422, detail="deployment_id is required.")
    result = _compiler(db, ctx).execute_deployment(deployment_id)
    db.commit()
    return result.to_dict()


@router.get("/projects/{project_id}/deployments")
def list_deployments(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = _project_or_404(db, ctx, project_id)
    rows = db.query(BuilderDeployment).filter(
        BuilderDeployment.project_id == project.id).all()
    return [
        {"id": d.id, "environment": d.environment, "state": d.state,
         "approval_id": d.approval_id, "requested_by": d.requested_by,
         "approved_by": d.approved_by, "detail": d.detail, "version": d.version}
        for d in rows
    ]


# ── Export ───────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/export")
def export_project(
    project_id: str,
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
):
    """Download the complete generated source as a ZIP. No builder lock-in."""
    project = _project_or_404(db, ctx, project_id)
    result = export_mod.export_zip(db, ctx, project)
    if not result.state.is_success:
        raise raise_for_result(result)
    chain.record(db, ctx, action="builder.export", result_state=ResultState.SUCCESS,
                 resource_type="project", resource_id=project.id,
                 detail=f"{result.meta['file_count']} files")
    db.commit()
    return Response(
        content=result.meta["archive"],
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{result.data["filename"]}"'},
    )


# ── Platform status ──────────────────────────────────────────────────────────

@router.get("/status")
def builder_status(
    ctx: RequestContext = Depends(resolve_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """What the Builder can actually do right now, given current credentials."""
    model_health = get_model_router().health()
    tools = get_tool_registry().list()
    return {
        "tenant_id": ctx.tenant_id,
        "stacks": {"implemented": sorted(IMPLEMENTED_STACKS), "planned": sorted(PLANNED_STACKS)},
        "model_fabric": model_health,
        "requirement_engine": (
            "MODEL_ASSISTED" if model_health["any_configured"] else "RULE_BASED"
        ),
        "requirement_engine_note": (
            "A model provider is configured; requirements are rule-based plus model enrichment."
            if model_health["any_configured"] else
            "No model provider is configured. Requirements are produced deterministically from "
            "the module catalogue — complete, but without project-specific model enrichment."
        ),
        "tools": [
            {"name": t.name, "risk_level": t.risk_level,
             "credential_satisfied": t.credential_satisfied,
             "requires_approval": t.requires_approval}
            for t in tools
        ],
        "deployment": {
            "adapters_implemented": [],
            "note": "No deployment provider adapter is implemented. Deploy requests are "
                    "approval-gated and then report CREDENTIAL_REQUIRED.",
        },
        "project_count": db.query(BuilderProject).filter(
            BuilderProject.tenant_id == ctx.tenant_id).count(),
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def _project_dict(project: BuilderProject, *, detailed: bool = False,
                  db: Optional[Session] = None) -> dict[str, Any]:
    data = {
        "id": project.id, "name": project.name, "slug": project.slug,
        "prompt": project.prompt, "status": project.status,
        "build_mode": project.build_mode, "target_type": project.target_type,
        "preferred_stack": project.preferred_stack,
        "deployment_target": project.deployment_target,
        "current_version": project.current_version,
        "created_at": project.created_at.isoformat(),
        "cost": {"model_usd": project.cost_model_usd, "tokens": project.cost_tokens,
                 "sandbox_seconds": round(project.sandbox_seconds, 2)},
    }
    if detailed and db is not None:
        data["counts"] = {
            "requirements": db.query(BuilderRequirement).filter(
                BuilderRequirement.project_id == project.id).count(),
            "data_models": db.query(BuilderDataModel).filter(
                BuilderDataModel.project_id == project.id).count(),
            "apis": db.query(BuilderApi).filter(BuilderApi.project_id == project.id).count(),
            "pages": db.query(BuilderPage).filter(BuilderPage.project_id == project.id).count(),
            "agents": db.query(BuilderAgent).filter(BuilderAgent.project_id == project.id).count(),
            "workflows": db.query(BuilderWorkflow).filter(
                BuilderWorkflow.project_id == project.id).count(),
            "files": db.query(BuilderFile).filter(
                BuilderFile.project_id == project.id,
                BuilderFile.version == project.current_version).count(),
        }
    return data


def raise_for_result(result: MoResult) -> HTTPException:
    from ..mo.errors import HTTP_STATUS_FOR_STATE
    return HTTPException(
        status_code=HTTP_STATUS_FOR_STATE.get(result.state, 400),
        detail={"state": result.state.value, "detail": result.detail, "meta": result.meta},
    )


def raise_for_error(exc: MoError) -> HTTPException:
    from ..mo.errors import HTTP_STATUS_FOR_STATE
    return HTTPException(
        status_code=HTTP_STATUS_FOR_STATE.get(exc.state, 400),
        detail={"state": exc.state.value, "detail": exc.detail, "meta": exc.meta},
    )


ALL_ROUTERS = [router, build_router]
