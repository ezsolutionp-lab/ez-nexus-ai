"""
The plumbing reference build (Instruction #3 §42-43).

This is the acceptance test for the whole Builder Runtime. The application is
produced BY the BuilderCompiler from a plain-English prompt — nothing in this
file hand-writes the plumbing application. The assertions check that the
prompt actually became a graph, real source files, a sandboxed build, and
generated tests that pass.
"""

import json

import pytest

from app.mo.builder.compiler import BuilderCompiler, ProjectStatus
from app.mo.builder.intent import BuildIntent
from app.mo.db import (
    BuilderAgent, BuilderApi, BuilderArchitecture, BuilderAssumption, BuilderBuild,
    BuilderDataModel, BuilderFile, BuilderGraphNode, BuilderIntegration, BuilderPage,
    BuilderRequirement, BuilderTestRun, BuilderVersion,
)
from app.mo.errors import ResultState

PLUMBING_PROMPT = (
    "Build a plumbing company platform with a public website, services pages, a contact form, "
    "a CRM with customer records and a lead pipeline, online booking, work orders, a dispatcher "
    "dashboard, a technician mobile workflow, a customer portal, invoices, payments, email "
    "notifications, maps, REST APIs, and an AI voice receptionist."
)


@pytest.fixture
def compiler(db, ctx, workspace_root):
    return BuilderCompiler(db, ctx, workspace_root=workspace_root)


@pytest.fixture
def reference_project(compiler, ctx):
    intent = BuildIntent(prompt=PLUMBING_PROMPT, tenant_id=ctx.tenant_id, requested_by=ctx.actor_id)
    project, report = compiler.compile(intent, run_build=True)
    return project, report


@pytest.mark.builder
@pytest.mark.slow
def test_prompt_becomes_a_project(reference_project):
    project, report = reference_project
    assert project.id
    assert project.name == "Plumbing Company Platform"
    assert project.slug == "plumbing-company-platform"


@pytest.mark.builder
def test_every_compiler_stage_ran(reference_project):
    from app.mo.builder.intent import CompilerStage
    _, report = reference_project
    for stage in CompilerStage.ordered():
        assert stage.value in report.stages, f"stage {stage.value} never ran"


@pytest.mark.builder
def test_requirements_were_extracted(db, reference_project):
    project, _ = reference_project
    reqs = db.query(BuilderRequirement).filter(BuilderRequirement.project_id == project.id).all()
    assert len(reqs) >= 25
    categories = {r.category for r in reqs}
    assert {"FUNCTIONAL", "NONFUNCTIONAL", "SECURITY"} <= categories
    keys = {r.key for r in reqs}
    assert "booking.create" in keys
    assert "sec.parameterised_sql" in keys


@pytest.mark.builder
def test_architecture_was_selected_with_alternatives(db, reference_project):
    project, _ = reference_project
    arch = db.query(BuilderArchitecture).filter(BuilderArchitecture.project_id == project.id).one()
    assert arch.recommended == "modular_monolith"
    alternatives = json.loads(arch.alternatives_json)
    assert len(alternatives) == 3
    assert all("why_not_chosen" in a for a in alternatives)
    scores = json.loads(arch.scores_json)
    assert "microservices" in scores


@pytest.mark.builder
def test_project_graph_was_built(db, reference_project):
    project, _ = reference_project
    nodes = db.query(BuilderGraphNode).filter(BuilderGraphNode.project_id == project.id).all()
    assert len(nodes) > 50
    types = {n.node_type for n in nodes}
    assert {"model", "api", "page", "agent", "workflow", "integration"} <= types
    booking_apis = [n for n in nodes if n.node_type == "api" and "Booking" in (n.label or "")]
    assert booking_apis, "no API nodes were derived for the Booking model"
    for api in booking_apis:
        assert "model:Booking" in json.loads(api.depends_on_json)


@pytest.mark.builder
def test_data_models_apis_and_pages_were_generated(db, reference_project):
    project, _ = reference_project
    models = db.query(BuilderDataModel).filter(BuilderDataModel.project_id == project.id).all()
    apis = db.query(BuilderApi).filter(BuilderApi.project_id == project.id).all()
    pages = db.query(BuilderPage).filter(BuilderPage.project_id == project.id).all()
    assert {m.name for m in models} >= {"Customer", "Lead", "Booking", "WorkOrder", "Technician", "Invoice"}
    assert len(apis) == len(models) * 5          # full CRUD per model
    assert all(a.requires_auth for a in apis), "a generated API was left unauthenticated"
    assert {p.route for p in pages} >= {"/", "/services", "/contact", "/book", "/app/dispatch"}


@pytest.mark.builder
def test_all_five_agents_were_compiled_into_manifests(db, reference_project):
    project, report = reference_project
    agents = db.query(BuilderAgent).filter(BuilderAgent.project_id == project.id).all()
    names = {a.name for a in agents}
    assert names == {
        "Booking Agent", "Lead Qualification Agent", "Dispatch Agent",
        "Follow-Up Agent", "Voice Receptionist Agent",
    }
    for agent in agents:
        assert agent.manifest_id, f"{agent.name} has no AgentManifest"
        canvas = json.loads(agent.canvas_json)
        node_types = {n["type"] for n in canvas["nodes"]}
        assert {"Input", "System Instructions", "Model", "Output"} <= node_types


@pytest.mark.builder
def test_agents_without_credentials_are_not_marked_ready(db, reference_project):
    """The directive's hard rule: do not mark READY unless tests pass."""
    project, report = reference_project
    agents = db.query(BuilderAgent).filter(BuilderAgent.project_id == project.id).all()
    assert all(a.status != "READY" for a in agents)
    assert report.stages["AGENT_MODEL"]["credential_blocked"] == 5
    assert report.stages["AGENT_MODEL"]["ready"] == 0


@pytest.mark.builder
def test_integrations_report_credential_required_not_fake_success(db, reference_project):
    project, report = reference_project
    integrations = db.query(BuilderIntegration).filter(
        BuilderIntegration.project_id == project.id).all()
    providers = {i.provider for i in integrations}
    assert {"payments", "smtp", "twilio", "maps"} <= providers
    assert all(i.status == "CREDENTIAL_REQUIRED" for i in integrations)
    assert len(report.stages["INTEGRATION_MODEL"]["credential_required"]) >= 4


@pytest.mark.builder
def test_real_source_files_were_generated(db, reference_project):
    project, _ = reference_project
    files = db.query(BuilderFile).filter(BuilderFile.project_id == project.id).all()
    paths = {f.path for f in files}
    assert "app/models/bookings.py" in paths
    assert "app/routers/bookings.py" in paths
    assert "app/schemas/bookings.py" in paths
    assert "tests/test_security.py" in paths
    assert len(files) >= 40
    for f in files:
        assert f.content.strip(), f"{f.path} is empty"
        assert len(f.sha256) == 64


@pytest.mark.builder
@pytest.mark.security
def test_generated_routers_are_zero_trust_and_tenant_scoped(db, reference_project):
    project, _ = reference_project
    routers = [
        f for f in db.query(BuilderFile).filter(
            BuilderFile.project_id == project.id,
            BuilderFile.path.like("app/routers/%"),
        ).all()
        if not f.path.endswith("__init__.py")
    ]
    assert routers
    for f in routers:
        assert "secure_router(" in f.content, f"{f.path} does not use the Zero Trust router"
        assert "APIRouter(" not in f.content, f"{f.path} builds a bare APIRouter"
        assert f.content.count("tenant_id == ctx.tenant_id") >= f.content.count("db.query(")
        assert "db.delete(" not in f.content, f"{f.path} performs a hard delete"


@pytest.mark.builder
@pytest.mark.slow
def test_sandbox_build_ran_and_generated_tests_passed(db, reference_project):
    project, _ = reference_project
    build = db.query(BuilderBuild).filter(BuilderBuild.project_id == project.id).one()
    stages = json.loads(build.stages_json)
    names = {s["name"]: s for s in stages}
    assert names["compile"]["state"] == "PASSED", names["compile"]
    assert names["static_analysis"]["state"] == "PASSED", names["static_analysis"]
    assert names["tests"]["state"] == "PASSED", names["tests"]
    assert build.state == ResultState.SUCCESS.value
    assert build.duration_ms > 0


@pytest.mark.builder
def test_generated_test_run_was_recorded_with_real_counts(db, reference_project):
    project, _ = reference_project
    run = db.query(BuilderTestRun).filter(BuilderTestRun.project_id == project.id).one()
    assert run.state == ResultState.SUCCESS.value
    assert run.passed >= 8
    assert run.failed == 0


@pytest.mark.builder
def test_project_reaches_tested_status(reference_project):
    project, _ = reference_project
    assert project.status == ProjectStatus.TESTED


@pytest.mark.builder
def test_a_version_was_recorded(db, reference_project):
    project, _ = reference_project
    version = db.query(BuilderVersion).filter(BuilderVersion.project_id == project.id).one()
    assert version.version == 1
    assert version.file_count >= 40
    assert json.loads(version.graph_snapshot)["nodes"]
