"""Workflow execution is real, and source export has no lock-in."""

import json
import zipfile
import io

import pytest

from app.mo.builder import workflows as wf
from app.mo.builder.catalog import WorkflowSpec
from app.mo.builder.compiler import BuilderCompiler
from app.mo.builder.intent import BuildIntent
from app.mo.errors import ResultState

pytestmark = pytest.mark.builder


@pytest.fixture
def project(db, admin_ctx, workspace_root):
    compiler = BuilderCompiler(db, admin_ctx, workspace_root=workspace_root)
    p, _ = compiler.compile(
        BuildIntent(prompt="Build a plumbing platform with online booking and a customer portal.",
                    tenant_id=admin_ctx.tenant_id, requested_by=admin_ctx.actor_id),
        run_build=True)
    return compiler, p


# ── Workflow builder ─────────────────────────────────────────────────────────

def test_unknown_node_type_is_rejected_at_compile_time():
    spec = WorkflowSpec("Bad", "manual", ({"id": "a", "type": "Teleport"},))
    with pytest.raises(ValueError, match="Unknown node type"):
        wf.compile_workflow(spec)


def test_duplicate_node_ids_are_rejected():
    spec = WorkflowSpec("Dup", "manual",
                        ({"id": "a", "type": "Trigger"}, {"id": "a", "type": "Output"}))
    with pytest.raises(ValueError, match="Duplicate node ids"):
        wf.compile_workflow(spec)


def test_workflow_runs_its_nodes_for_real(db, admin_ctx):
    spec = WorkflowSpec("Echo flow", "manual", (
        {"id": "t", "type": "Trigger"},
        {"id": "echo", "type": "Tool", "tool": "core.echo", "input": {"message": "hello"}},
        {"id": "ev", "type": "Event", "topic": "test.topic"},
        {"id": "out", "type": "Output"},
    ))
    row = wf.persist_workflow(db, admin_ctx, spec, project_id="p1")
    result = wf.execute_workflow(db, admin_ctx, row)
    assert result.state is ResultState.SUCCESS
    steps = result.data["steps"]
    assert [s["node_id"] for s in steps] == ["t", "echo", "ev", "out"]
    assert steps[1]["data"]["echo"] == "hello"


def test_workflow_stops_and_reports_when_a_tool_lacks_credentials(db, admin_ctx):
    spec = WorkflowSpec("Notify", "event", (
        {"id": "t", "type": "Trigger"},
        {"id": "mail", "type": "Tool", "tool": "comms.send_email",
         "input": {"to": "a@b.com", "subject": "s", "body": "b"}},
        {"id": "out", "type": "Output"},
    ))
    row = wf.persist_workflow(db, admin_ctx, spec, project_id="p1")
    result = wf.execute_workflow(db, admin_ctx, row)
    assert result.state is ResultState.CREDENTIAL_REQUIRED
    assert "SMTP_PASSWORD" in result.detail
    assert result.meta["steps_run"] == 2       # stopped at the failing node
    assert result.meta["steps_total"] == 3


def test_workflow_approval_node_blocks_without_a_grant(db, admin_ctx):
    spec = WorkflowSpec("Gated", "manual", (
        {"id": "t", "type": "Trigger"},
        {"id": "gate", "type": "Approval", "action": "builder.deploy.staging"},
        {"id": "out", "type": "Output"},
    ))
    row = wf.persist_workflow(db, admin_ctx, spec, project_id="p1")
    result = wf.execute_workflow(db, admin_ctx, row)
    assert result.state is ResultState.APPROVAL_REQUIRED


def test_workflow_approval_node_passes_with_a_grant(db, admin_ctx, other_admin_ctx):
    from app.mo.approvals import engine as approvals
    approval = approvals.request_approval(db, admin_ctx, action="builder.deploy.staging")
    approvals.decide(db, other_admin_ctx, approval.id, approve=True)

    spec = WorkflowSpec("Gated", "manual", (
        {"id": "t", "type": "Trigger"},
        {"id": "gate", "type": "Approval", "action": "builder.deploy.staging"},
        {"id": "out", "type": "Output"},
    ))
    row = wf.persist_workflow(db, admin_ctx, spec, project_id="p1")
    result = wf.execute_workflow(db, admin_ctx, row, approval_id=approval.id)
    assert result.state is ResultState.SUCCESS


def test_a_node_type_outside_the_catalog_is_still_reported_blocked_not_success(db, admin_ctx):
    """The directive's rule: never claim a step ran when it did not (guards a hand-edited stored workflow)."""
    spec = WorkflowSpec("Partial", "manual", ({"id": "t", "type": "Trigger"}, {"id": "out", "type": "Output"}))
    row = wf.persist_workflow(db, admin_ctx, spec, project_id="p1")
    row.nodes_json = json.dumps([{"id": "t", "type": "Trigger"}, {"id": "x", "type": "Teleport"}, {"id": "out", "type": "Output"}])
    result = wf.execute_workflow(db, admin_ctx, row)
    assert result.state is ResultState.BLOCKED
    assert "no executor wired" in result.detail


def test_the_generated_booking_workflow_is_persisted(db, project):
    from app.mo.db import BuilderWorkflow
    _, p = project
    rows = db.query(BuilderWorkflow).filter(BuilderWorkflow.project_id == p.id).all()
    assert any(r.name == "Booking confirmation" for r in rows)
    nodes = json.loads(rows[0].nodes_json)
    assert {n["type"] for n in nodes} <= wf.VALID_NODE_TYPES


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_returns_a_real_zip_of_the_source(db, admin_ctx, project):
    from app.mo.builder import export
    _, p = project
    result = export.export_zip(db, admin_ctx, p)
    assert result.state is ResultState.SUCCESS

    archive = zipfile.ZipFile(io.BytesIO(result.meta["archive"]))
    names = archive.namelist()
    assert any(n.endswith("app/routers/bookings.py") for n in names)
    assert any(n.endswith("app/main.py") for n in names)
    assert any(n.endswith("requirements.txt") for n in names)
    assert any(n.endswith("MO_BUILD_MANIFEST.json") for n in names)

    # The exported source is the real thing, not a placeholder.
    router_name = next(n for n in names if n.endswith("app/routers/bookings.py"))
    body = archive.read(router_name).decode()
    assert "secure_router(" in body
    assert "tenant_id == ctx.tenant_id" in body

    manifest = json.loads(archive.read(next(n for n in names if n.endswith("MO_BUILD_MANIFEST.json"))))
    assert manifest["file_count"] == len(names) - 1
    assert "not locked to the visual builder" in manifest["note"]


def test_export_manifest_lists_files_with_hashes(db, admin_ctx, project):
    from app.mo.builder import export
    _, p = project
    manifest = export.export_manifest(db, admin_ctx, p)
    assert manifest["file_count"] > 30
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])
