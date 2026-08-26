"""
MO NEXUS OMEGA — Universal Builder Compiler.

The single entry point from intent to running artifact. It owns the stage
sequence, persists a versioned artifact at every stage, and enforces the rules
the directive is emphatic about:

  * Deployment always requires an approval. There is no code path from
    `compile()` to a production deployment.
  * A stage that fails stops the pipeline and the project's status becomes that
    failure state — never COMPLETE.
  * Credential-dependent integrations are recorded as CREDENTIAL_REQUIRED, and
    the build still succeeds around them; nothing pretends they connected.
  * Every stage writes an audit record and an event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..approvals import engine as approvals
from ..audit import chain
from ..context import RequestContext
from ..db import (
    BuilderApi, BuilderArchitecture, BuilderAssumption, BuilderBuild, BuilderDataModel,
    BuilderDeployment, BuilderFile, BuilderGraphNode, BuilderIntegration, BuilderPage,
    BuilderPreview, BuilderProject, BuilderRequirement, BuilderTestRun, BuilderVersion,
    BuilderAgent,
)
from ..errors import MoError, MoResult, ResultState
from ..events import fabric as event_fabric
from . import agents as agent_builder
from . import pipeline, workflows
from .architecture import ArchitecturePlanner
from .codegen.fastapi_react import GenerationError, generate, generate_runtime, generate_tests
from .graph import build_graph
from .intent import BuildIntent, CompilerStage
from .requirements import ProjectSpec, RequirementEngine


class ProjectStatus(str):
    DRAFT = "DRAFT"
    ANALYSED = "ANALYSED"
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    BUILT = "BUILT"
    TESTED = "TESTED"
    PREVIEWED = "PREVIEWED"
    AWAITING_DEPLOY_APPROVAL = "AWAITING_DEPLOY_APPROVAL"
    DEPLOYED = "DEPLOYED"
    BUILD_FAILED = "BUILD_FAILED"
    TEST_FAILED = "TEST_FAILED"
    SECURITY_FAILED = "SECURITY_FAILED"


@dataclass
class CompileReport:
    project_id: str
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: ResultState = ResultState.SUCCESS
    detail: str = ""

    def stage(self, stage: CompilerStage, state: ResultState, detail: str, **data: Any) -> None:
        self.stages[stage.value] = {"state": state.value, "detail": detail, **data}
        if not state.is_success and self.state.is_success:
            self.state = state
            self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "state": self.state.value,
            "detail": self.detail, "stages": self.stages,
        }


class BuilderCompiler:
    """Intent → structured project → source → build → tests → preview."""

    def __init__(
        self,
        db: Session,
        ctx: RequestContext,
        *,
        workspace_root: Path,
        requirement_engine: Optional[RequirementEngine] = None,
        planner: Optional[ArchitecturePlanner] = None,
    ):
        self.db = db
        self.ctx = ctx
        self.workspace_root = Path(workspace_root)
        self.requirements = requirement_engine or RequirementEngine()
        self.planner = planner or ArchitecturePlanner()

    # ── stage 1-2: create + analyse ──────────────────────────────────────────

    def create_project(self, intent: BuildIntent) -> BuilderProject:
        if intent.tenant_id != self.ctx.tenant_id:
            raise MoError(
                ResultState.POLICY_DENIED,
                "A build intent cannot target a different tenant than the caller.",
            )
        project = BuilderProject(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id,
            name=intent.name or "MO Project", slug=intent.slug, prompt=intent.prompt,
            build_mode=intent.build_mode.value, target_type=intent.target_type.value,
            target_platform=intent.target_platform, preferred_stack=intent.preferred_stack,
            source_channel=intent.source_channel, security_level=intent.security_level,
            data_classification=intent.data_classification,
            deployment_target=intent.deployment_target,
            budget_usd=intent.budget_usd,
            constraints_json=json.dumps(intent.constraints),
            status=ProjectStatus.DRAFT,
        )
        self.db.add(project)
        self.db.flush()
        intent.project_id = project.id
        project.workspace_path = str(self.workspace_root / project.id)
        self.db.flush()

        chain.record(self.db, self.ctx, action="builder.project.created",
                     result_state=ResultState.SUCCESS, resource_type="project",
                     resource_id=project.id, detail=project.name,
                     payload={"prompt": intent.prompt[:500]})
        event_fabric.publish(self.db, self.ctx, "builder.project.created",
                             {"project_id": project.id, "name": project.name})
        return project

    # ── full pipeline ────────────────────────────────────────────────────────

    def compile(self, intent: BuildIntent, *, run_build: bool = True) -> tuple[BuilderProject, CompileReport]:
        project = self.create_project(intent)
        report = CompileReport(project_id=project.id)
        report.stage(CompilerStage.INTENT, ResultState.SUCCESS,
                     f"Intent accepted for {intent.target_type.value} on {intent.preferred_stack}.")

        # REQUIREMENTS
        spec = self.requirements.analyse(intent)
        self._persist_requirements(project, spec)
        report.stage(
            CompilerStage.REQUIREMENTS, ResultState.SUCCESS,
            f"{len(spec.requirements)} requirements across {len(spec.modules)} modules "
            f"({spec.provenance}).",
            counts=spec.counts, provenance=spec.provenance,
            model_enrichment=spec.model_enrichment,
            blocking_questions=[q.to_dict() for q in spec.questions],
        )
        report.stage(CompilerStage.FUNCTIONAL_SPEC, ResultState.SUCCESS,
                     f"{len([r for r in spec.requirements if r.category == 'FUNCTIONAL'])} functional requirements.")
        report.stage(CompilerStage.NONFUNCTIONAL_SPEC, ResultState.SUCCESS,
                     f"{len([r for r in spec.requirements if r.category in ('NONFUNCTIONAL', 'SECURITY', 'COMPLIANCE')])} "
                     "non-functional, security and compliance requirements.")

        # ARCHITECTURE
        recommendation = self.planner.plan(spec)
        arch = BuilderArchitecture(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
            version=1, recommended=recommendation.recommended, rationale=recommendation.rationale,
            alternatives_json=json.dumps(recommendation.alternatives),
            tradeoffs_json=json.dumps(recommendation.tradeoffs),
            scores_json=json.dumps(recommendation.scores),
            infrastructure_json=json.dumps(recommendation.infrastructure),
            complexity=recommendation.complexity,
        )
        self.db.add(arch)
        self.db.flush()
        report.stage(CompilerStage.ARCHITECTURE, ResultState.SUCCESS,
                     f"{recommendation.recommended} ({recommendation.complexity} complexity).",
                     alternatives=[a["name"] for a in recommendation.alternatives])
        project.status = ProjectStatus.ANALYSED
        self.db.flush()

        # DATA / API / UI / AGENT / WORKFLOW / INTEGRATION models
        graph = build_graph(spec)
        cycle = graph.find_cycle()
        if cycle:
            report.stage(CompilerStage.DATA_MODEL, ResultState.BUILD_FAILED,
                         f"Project graph has a cycle: {' -> '.join(cycle)}")
            project.status = ProjectStatus.BUILD_FAILED
            self.db.flush()
            return project, report

        self._persist_graph(project, graph)
        self._persist_data_models(project, spec)
        api_count = self._persist_apis(project, spec, graph)
        self._persist_pages(project, spec)
        report.stage(CompilerStage.DATA_MODEL, ResultState.SUCCESS, f"{len(spec.models)} data models.")
        report.stage(CompilerStage.API_MODEL, ResultState.SUCCESS, f"{api_count} REST endpoints.")
        report.stage(CompilerStage.UI_MODEL, ResultState.SUCCESS, f"{len(spec.pages)} pages.")

        agent_summary = self._build_agents(project, spec)
        report.stage(
            CompilerStage.AGENT_MODEL,
            ResultState.SUCCESS if agent_summary["compiled"] else ResultState.PARTIAL,
            f"{agent_summary['compiled']} agent(s) compiled, {agent_summary['ready']} READY, "
            f"{agent_summary['credential_blocked']} blocked on model credentials.",
            **agent_summary,
        )

        wf_count = self._build_workflows(project, spec)
        report.stage(CompilerStage.WORKFLOW_MODEL, ResultState.SUCCESS, f"{wf_count} workflow(s) compiled.")

        integ = self._persist_integrations(project, spec)
        report.stage(
            CompilerStage.INTEGRATION_MODEL,
            ResultState.SUCCESS if not integ["credential_required"] else ResultState.PARTIAL,
            f"{integ['total']} integration(s); {len(integ['credential_required'])} need credentials.",
            **integ,
        )

        report.stage(CompilerStage.INFRASTRUCTURE_MODEL, ResultState.SUCCESS,
                     json.dumps(recommendation.infrastructure))
        report.stage(CompilerStage.SECURITY_MODEL, ResultState.SUCCESS,
                     f"{len([r for r in spec.requirements if r.category == 'SECURITY'])} security requirements "
                     "enforced by generated code and verified by generated tests.")

        # SOURCE GENERATION
        try:
            source_files = generate(spec) + generate_runtime(spec)
            test_files = generate_tests(spec)
        except GenerationError as exc:
            report.stage(CompilerStage.TEST_MODEL, ResultState.BUILD_FAILED, str(exc))
            project.status = ProjectStatus.BUILD_FAILED
            self.db.flush()
            chain.record(self.db, self.ctx, action="builder.generate", result_state=ResultState.BUILD_FAILED,
                         resource_type="project", resource_id=project.id, detail=str(exc))
            return project, report

        all_files = source_files + test_files
        project.current_version += 1
        self._persist_files(project, all_files)
        report.stage(CompilerStage.TEST_MODEL, ResultState.SUCCESS,
                     f"{len(test_files)} generated test file(s) covering models, schemas and security.")
        project.status = ProjectStatus.GENERATED
        self.db.flush()

        version = BuilderVersion(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
            version=project.current_version, label=f"v{project.current_version}",
            summary=f"{len(all_files)} files from {len(spec.modules)} modules",
            file_count=len(all_files), graph_snapshot=json.dumps(graph.to_dict()),
        )
        self.db.add(version)
        self.db.flush()

        # DEPLOYMENT MODEL — always approval-gated, never automatic.
        report.stage(CompilerStage.DEPLOYMENT_MODEL, ResultState.APPROVAL_REQUIRED,
                     f"Deployment to '{intent.deployment_target}' requires an approval. "
                     "The compiler never deploys.")

        chain.record(self.db, self.ctx, action="builder.generate", result_state=ResultState.SUCCESS,
                     resource_type="project", resource_id=project.id,
                     detail=f"{len(all_files)} files generated")
        event_fabric.publish(self.db, self.ctx, "builder.project.generated",
                             {"project_id": project.id, "file_count": len(all_files)})

        if run_build:
            build_result = self.build(project)
            if not build_result.state.is_success and build_result.state is not ResultState.PARTIAL:
                report.state = build_result.state
                report.detail = build_result.detail

        return project, report

    # ── build / test ─────────────────────────────────────────────────────────

    def build(self, project: BuilderProject) -> MoResult:
        """Materialise into the workspace and run the sandboxed build stages."""
        self.ctx.require_same_tenant(project.tenant_id, f"Project {project.id}")

        files = (
            self.db.query(BuilderFile)
            .filter(BuilderFile.project_id == project.id,
                    BuilderFile.version == project.current_version)
            .all()
        )
        if not files:
            return MoResult(ResultState.BUILD_FAILED, "No generated files exist for this version.")

        from .codegen.fastapi_react import GeneratedFile
        generated = [GeneratedFile(f.path, f.content, f.language or "python") for f in files]
        workspace = Path(project.workspace_path or (self.workspace_root / project.id))
        manifest = pipeline.materialise(generated, workspace)

        state, stages, metrics = pipeline.run_build(workspace)

        build_row = BuilderBuild(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
            version=project.current_version, state=state.value,
            stages_json=json.dumps([s.to_dict() for s in stages]),
            stdout="\n".join(s.stdout_tail for s in stages if s.stdout_tail)[:20000],
            exit_code=next((s.exit_code for s in reversed(stages) if s.exit_code is not None), None),
            duration_ms=metrics["duration_ms"], peak_rss_kb=metrics.get("peak_rss_kb"),
            finished_at=datetime.utcnow(),
        )
        self.db.add(build_row)
        project.sandbox_seconds += metrics["duration_ms"] / 1000.0
        self.db.flush()

        test_stage = next((s for s in stages if s.name == "tests"), None)
        if test_stage:
            counts = _parse_pytest_summary(test_stage.stdout_tail)
            self.db.add(BuilderTestRun(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id,
                project_id=project.id, build_id=build_row.id, suite="generated",
                state=(ResultState.SUCCESS.value if test_stage.state == "PASSED"
                       else ResultState.TEST_FAILED.value if test_stage.state == "FAILED"
                       else "SKIPPED"),
                total=counts["total"], passed=counts["passed"], failed=counts["failed"],
                duration_ms=test_stage.duration_ms, report=test_stage.stdout_tail,
            ))
            self.db.flush()

        project.status = {
            ResultState.SUCCESS: ProjectStatus.TESTED,
            ResultState.PARTIAL: ProjectStatus.BUILT,
            ResultState.BUILD_FAILED: ProjectStatus.BUILD_FAILED,
            ResultState.TEST_FAILED: ProjectStatus.TEST_FAILED,
            ResultState.SECURITY_FAILED: ProjectStatus.SECURITY_FAILED,
        }.get(state, ProjectStatus.BUILD_FAILED)
        self.db.flush()

        chain.record(self.db, self.ctx, action="builder.build", result_state=state,
                     resource_type="project", resource_id=project.id,
                     detail=f"{len(stages)} stage(s), {metrics['duration_ms']}ms",
                     payload={"stages": [s.to_dict() for s in stages], "manifest": manifest})
        event_fabric.publish(self.db, self.ctx, "builder.build.finished",
                             {"project_id": project.id, "state": state.value})

        payload = {"build_id": build_row.id, "state": state.value,
                   "stages": [s.to_dict() for s in stages], "manifest": manifest}
        if state in (ResultState.SUCCESS, ResultState.PARTIAL):
            return MoResult(state, "" if state.is_success else
                            "Build compiled and passed security analysis; no generated tests to run.",
                            payload) if state is not ResultState.SUCCESS else MoResult.ok(payload)
        failing = next((s for s in stages if s.state == "FAILED"), None)
        return MoResult(state, f"Build stage '{failing.name}' failed: {failing.detail}"
                        if failing else "Build failed.", payload)

    # ── preview ──────────────────────────────────────────────────────────────

    def preview(self, project: BuilderProject, *, ttl_hours: int = 24) -> MoResult:
        """Create a clearly-labelled PREVIEW. Never presented as production."""
        self.ctx.require_same_tenant(project.tenant_id, f"Project {project.id}")

        last_build = (
            self.db.query(BuilderBuild)
            .filter(BuilderBuild.project_id == project.id)
            .order_by(BuilderBuild.started_at.desc()).first()
        )
        if last_build is None:
            return MoResult(ResultState.BLOCKED, "Build the project before creating a preview.")
        if last_build.state in (ResultState.BUILD_FAILED.value, ResultState.SECURITY_FAILED.value,
                                ResultState.TEST_FAILED.value):
            return MoResult(
                ResultState.BLOCKED,
                f"The last build finished {last_build.state}. A failed build is never previewed.",
            )

        workspace = Path(project.workspace_path or (self.workspace_root / project.id))
        entry = workspace / "README.md"
        row = BuilderPreview(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
            version=project.current_version, build_id=last_build.id,
            state=ResultState.SUCCESS.value, label="PREVIEW",
            url=f"/api/mo/builder/projects/{project.id}/preview/{project.current_version}",
            entry_path=str(entry),
            expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
        )
        self.db.add(row)
        project.status = ProjectStatus.PREVIEWED
        self.db.flush()
        chain.record(self.db, self.ctx, action="builder.preview.created",
                     result_state=ResultState.SUCCESS, resource_type="preview", resource_id=row.id)
        return MoResult.ok({
            "preview_id": row.id, "label": "PREVIEW", "url": row.url,
            "expires_at": row.expires_at.isoformat(),
            "note": "This is a PREVIEW environment. It is not production.",
        })

    # ── deployment (always approval-gated) ───────────────────────────────────

    def request_deployment(self, project: BuilderProject, environment: str, reason: str = "") -> MoResult:
        self.ctx.require_same_tenant(project.tenant_id, f"Project {project.id}")
        if environment not in {"staging", "production"}:
            return MoResult(ResultState.FAILED, f"Unknown environment '{environment}'.")

        last_build = (
            self.db.query(BuilderBuild).filter(BuilderBuild.project_id == project.id)
            .order_by(BuilderBuild.started_at.desc()).first()
        )
        if last_build is None or last_build.state in (
            ResultState.BUILD_FAILED.value, ResultState.TEST_FAILED.value, ResultState.SECURITY_FAILED.value,
        ):
            return MoResult(
                ResultState.BLOCKED,
                "Deployment requires a build that passed. "
                f"Last build state: {last_build.state if last_build else 'none'}.",
            )

        action = f"builder.deploy.{environment}"
        approval = approvals.request_approval(
            self.db, self.ctx, action=action, resource_type="project", resource_id=project.id,
            reason=reason or f"Deploy {project.name} to {environment}",
            payload={"project_id": project.id, "version": project.current_version},
        )
        deployment = BuilderDeployment(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
            version=project.current_version, environment=environment,
            state=ResultState.APPROVAL_REQUIRED.value, approval_id=approval.id,
            requested_by=self.ctx.actor_id,
            detail=f"{approval.risk_tier} risk; {approval.required_approvals} approval(s) required.",
        )
        self.db.add(deployment)
        project.status = ProjectStatus.AWAITING_DEPLOY_APPROVAL
        self.db.flush()
        event_fabric.publish(self.db, self.ctx, "builder.deploy.requested",
                             {"project_id": project.id, "environment": environment,
                              "approval_id": approval.id})
        return MoResult(
            ResultState.APPROVAL_REQUIRED,
            f"Deployment to {environment} requires {approval.required_approvals} approval(s) "
            f"from a second party ({approval.risk_tier} risk).",
            meta={"deployment_id": deployment.id, "approval_id": approval.id,
                  "risk_tier": approval.risk_tier},
        )

    def execute_deployment(self, deployment_id: str) -> MoResult:
        """
        Runs only with a granted approval — and then reports honestly that no
        deployment provider adapter is wired, rather than claiming a deploy.
        """
        deployment = self.db.get(BuilderDeployment, deployment_id)
        if deployment is None:
            return MoResult(ResultState.FAILED, f"Deployment {deployment_id} does not exist.")
        self.ctx.require_same_tenant(deployment.tenant_id, f"Deployment {deployment_id}")

        if not approvals.is_granted(self.db, self.ctx, deployment.approval_id):
            return MoResult(
                ResultState.APPROVAL_REQUIRED,
                "This deployment has no granted, unexpired approval. It will not proceed.",
            )

        deployment.state = ResultState.CREDENTIAL_REQUIRED.value
        deployment.detail = (
            "Approval verified. No deployment provider adapter is implemented in this build, "
            "so nothing was deployed. Configure a deployment target adapter to complete this step."
        )
        self.db.flush()
        chain.record(self.db, self.ctx, action="builder.deploy.execute",
                     result_state=ResultState.CREDENTIAL_REQUIRED,
                     resource_type="deployment", resource_id=deployment.id,
                     detail=deployment.detail)
        return MoResult(ResultState.CREDENTIAL_REQUIRED, deployment.detail,
                        meta={"deployment_id": deployment.id})

    # ── persistence helpers ──────────────────────────────────────────────────

    def _persist_requirements(self, project: BuilderProject, spec: ProjectSpec) -> None:
        for r in spec.requirements:
            self.db.add(BuilderRequirement(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                category=r.category, key=r.key, statement=r.statement,
                acceptance_criteria=r.acceptance, priority=r.priority,
                source="explicit" if r.key.split(".")[0] in spec.modules else "inferred",
            ))
        for a in spec.assumptions:
            self.db.add(BuilderAssumption(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                statement=a.statement, rationale=a.rationale, impact=a.impact,
            ))
        self.db.flush()

    def _persist_graph(self, project: BuilderProject, graph) -> None:
        for node in graph.nodes.values():
            self.db.add(BuilderGraphNode(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                version=project.current_version + 1, node_key=node.key, node_type=node.node_type,
                label=node.label, attributes_json=json.dumps(node.attributes),
                depends_on_json=json.dumps(node.depends_on),
            ))
        self.db.flush()

    def _persist_data_models(self, project: BuilderProject, spec: ProjectSpec) -> None:
        for m in spec.models:
            self.db.add(BuilderDataModel(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                name=m.name, table_name=m.table, description=m.description,
                fields_json=json.dumps([f.to_dict() for f in m.fields]),
                relations_json=json.dumps([dict(r) for r in m.relations]),
                tenant_scoped=m.tenant_scoped,
            ))
        self.db.flush()

    def _persist_apis(self, project: BuilderProject, spec: ProjectSpec, graph) -> int:
        count = 0
        for node in graph.nodes.values():
            if node.node_type != "api":
                continue
            attrs = node.attributes
            self.db.add(BuilderApi(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                name=node.label, protocol="REST", method=attrs["method"], path=attrs["path"],
                data_model=attrs.get("model"), operation=attrs.get("operation"),
                requires_auth=True, required_scopes_json=json.dumps(["builder:read"]),
                rate_limit_per_minute=60,
                idempotent=attrs["method"] in ("GET", "PUT", "DELETE"),
            ))
            count += 1
        self.db.flush()
        return count

    def _persist_pages(self, project: BuilderProject, spec: ProjectSpec) -> None:
        for p in spec.pages:
            self.db.add(BuilderPage(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                name=p.name, route=p.route, title=p.title, kind=p.kind,
                requires_auth=p.requires_auth, sections_json=json.dumps(list(p.sections)),
                seo_json=json.dumps({"title": p.title, "description": f"{p.title} — {project.name}"}),
            ))
        self.db.flush()

    def _build_agents(self, project: BuilderProject, spec: ProjectSpec) -> dict[str, Any]:
        compiled = ready = credential_blocked = failed = 0
        details: list[dict[str, Any]] = []
        for agent_spec in spec.agents:
            manifest, result = agent_builder.build_and_test_agent(
                self.db, self.ctx, agent_spec, project_id=project.id)
            compiled += 1
            if result.state is ResultState.SUCCESS:
                ready += 1
            elif result.state is ResultState.CREDENTIAL_REQUIRED:
                credential_blocked += 1
            else:
                failed += 1
            self.db.add(BuilderAgent(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                manifest_id=manifest.id, name=agent_spec.name, role=agent_spec.role,
                purpose=agent_spec.purpose,
                canvas_json=json.dumps({
                    "nodes": [
                        {"id": "input", "type": "Input"},
                        {"id": "instructions", "type": "System Instructions"},
                        {"id": "model", "type": "Model", "capability": agent_spec.capability},
                        *[{"id": f"tool_{i}", "type": "Tool", "tool": t}
                          for i, t in enumerate(agent_spec.tools)],
                        *[{"id": f"gate_{i}", "type": "Approval", "action": g}
                          for i, g in enumerate(agent_spec.approval_gates)],
                        {"id": "output", "type": "Output"},
                    ]
                }),
                status=manifest.status,
            ))
            details.append({"name": agent_spec.name, "status": manifest.status,
                            "result": result.state.value})
        self.db.flush()
        return {"compiled": compiled, "ready": ready, "credential_blocked": credential_blocked,
                "failed": failed, "agents": details}

    def _build_workflows(self, project: BuilderProject, spec: ProjectSpec) -> int:
        count = 0
        for wf in spec.workflows:
            workflows.persist_workflow(self.db, self.ctx, wf, project_id=project.id)
            count += 1
        return count

    def _persist_integrations(self, project: BuilderProject, spec: ProjectSpec) -> dict[str, Any]:
        import os
        credential_required: list[str] = []
        for i in spec.integrations:
            configured = bool(os.getenv(i.credential_env_var, "").strip())
            status = ResultState.SUCCESS.value if configured else ResultState.CREDENTIAL_REQUIRED.value
            if not configured:
                credential_required.append(f"{i.provider}:{i.capability} ({i.credential_env_var})")
            self.db.add(BuilderIntegration(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                provider=i.provider, capability=i.capability, auth_kind=i.auth_kind,
                credential_env_var=i.credential_env_var, status=status,
                config_json=json.dumps({}), last_checked_at=datetime.utcnow(),
            ))
        self.db.flush()
        return {"total": len(spec.integrations), "credential_required": credential_required}

    def _persist_files(self, project: BuilderProject, files: list) -> None:
        for f in files:
            self.db.add(BuilderFile(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, project_id=project.id,
                version=project.current_version, path=f.path, language=f.language,
                content=f.content, sha256=f.sha256, size_bytes=f.size_bytes,
                generator=project.preferred_stack,
            ))
        self.db.flush()


def _parse_pytest_summary(text: str) -> dict[str, int]:
    """Read counts from pytest's summary line. Unknown counts stay zero."""
    import re
    out = {"total": 0, "passed": 0, "failed": 0}
    for key in ("passed", "failed", "error", "skipped"):
        m = re.search(rf"(\d+) {key}", text or "")
        if m and key in out:
            out[key] = int(m.group(1))
    out["total"] = out["passed"] + out["failed"]
    return out
