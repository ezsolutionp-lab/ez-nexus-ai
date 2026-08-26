"""Deployment is never automatic (Instruction #3 §38, Instruction #1 §27)."""

import pytest

from app.mo.approvals import engine as approvals
from app.mo.builder.compiler import BuilderCompiler, ProjectStatus
from app.mo.builder.intent import BuildIntent
from app.mo.context import RequestContext
from app.mo.db import BuilderDeployment
from app.mo.errors import ResultState

pytestmark = pytest.mark.builder


@pytest.fixture
def built_project(db, admin_ctx, workspace_root):
    compiler = BuilderCompiler(db, admin_ctx, workspace_root=workspace_root)
    project, _ = compiler.compile(
        BuildIntent(prompt="Build a plumbing website with a contact form and online booking.",
                    tenant_id=admin_ctx.tenant_id, requested_by=admin_ctx.actor_id),
        run_build=True)
    return compiler, project


def test_compile_never_deploys(built_project):
    _, project = built_project
    assert project.status != ProjectStatus.DEPLOYED


def test_deploy_request_returns_approval_required(built_project):
    compiler, project = built_project
    result = compiler.request_deployment(project, "staging")
    assert result.state is ResultState.APPROVAL_REQUIRED
    assert project.status == ProjectStatus.AWAITING_DEPLOY_APPROVAL


def test_production_is_critical_risk_needing_two_approvals(built_project):
    compiler, project = built_project
    result = compiler.request_deployment(project, "production")
    assert result.meta["risk_tier"] == "CRITICAL"


def test_execution_without_approval_is_refused(db, built_project):
    compiler, project = built_project
    request = compiler.request_deployment(project, "staging")
    deployment_id = request.meta["deployment_id"]
    result = compiler.execute_deployment(deployment_id)
    assert result.state is ResultState.APPROVAL_REQUIRED


def test_requester_cannot_approve_their_own_deployment(db, built_project, admin_ctx):
    compiler, project = built_project
    request = compiler.request_deployment(project, "staging")
    decision = approvals.decide(db, admin_ctx, request.meta["approval_id"], approve=True)
    assert decision.state is ResultState.POLICY_DENIED
    assert "cannot approve" in decision.detail


def test_second_party_approval_unblocks_execution(db, built_project, other_admin_ctx):
    compiler, project = built_project
    request = compiler.request_deployment(project, "staging")
    decision = approvals.decide(db, other_admin_ctx, request.meta["approval_id"], approve=True)
    assert decision.state is ResultState.SUCCESS

    result = compiler.execute_deployment(request.meta["deployment_id"])
    # Approval verified — and the honest answer is that no deploy adapter exists.
    assert result.state is ResultState.CREDENTIAL_REQUIRED
    assert "nothing was deployed" in result.detail


def test_production_still_blocked_after_only_one_approval(db, built_project, other_admin_ctx):
    compiler, project = built_project
    request = compiler.request_deployment(project, "production")
    decision = approvals.decide(db, other_admin_ctx, request.meta["approval_id"], approve=True)
    assert decision.state is ResultState.PENDING_APPROVAL
    assert "1 further approval" in decision.detail
    assert compiler.execute_deployment(
        request.meta["deployment_id"]).state is ResultState.APPROVAL_REQUIRED


def test_high_risk_approval_requires_mfa(db, built_project, tenant_a):
    compiler, project = built_project
    request = compiler.request_deployment(project, "staging")
    no_mfa = RequestContext(tenant_id=tenant_a, actor_id="admin-no-mfa",
                            is_admin=True, mfa_verified=False, scopes=frozenset({"*"}))
    decision = approvals.decide(db, no_mfa, request.meta["approval_id"], approve=True)
    assert decision.state is ResultState.POLICY_DENIED
    assert "multi-factor" in decision.detail


def test_rejected_approval_blocks_deployment(db, built_project, other_admin_ctx):
    compiler, project = built_project
    request = compiler.request_deployment(project, "staging")
    approvals.decide(db, other_admin_ctx, request.meta["approval_id"], approve=False,
                     note="not ready")
    assert compiler.execute_deployment(
        request.meta["deployment_id"]).state is ResultState.APPROVAL_REQUIRED


def test_revoked_approval_stops_a_previously_granted_deployment(db, built_project, other_admin_ctx):
    compiler, project = built_project
    request = compiler.request_deployment(project, "staging")
    approvals.decide(db, other_admin_ctx, request.meta["approval_id"], approve=True)
    approvals.revoke(db, other_admin_ctx, request.meta["approval_id"], "rolled back")
    assert compiler.execute_deployment(
        request.meta["deployment_id"]).state is ResultState.APPROVAL_REQUIRED


def test_a_failed_build_cannot_be_deployed(db, admin_ctx, workspace_root):
    compiler = BuilderCompiler(db, admin_ctx, workspace_root=workspace_root)
    project, _ = compiler.compile(
        BuildIntent(prompt="Build a plumbing website.", tenant_id=admin_ctx.tenant_id,
                    requested_by=admin_ctx.actor_id),
        run_build=False)
    result = compiler.request_deployment(project, "staging")
    assert result.state is ResultState.BLOCKED
    assert "requires a build that passed" in result.detail


def test_a_failed_build_cannot_be_previewed(db, admin_ctx, workspace_root):
    compiler = BuilderCompiler(db, admin_ctx, workspace_root=workspace_root)
    project, _ = compiler.compile(
        BuildIntent(prompt="Build a plumbing website.", tenant_id=admin_ctx.tenant_id,
                    requested_by=admin_ctx.actor_id),
        run_build=False)
    assert compiler.preview(project).state is ResultState.BLOCKED


def test_preview_is_labelled_preview_not_production(built_project):
    compiler, project = built_project
    result = compiler.preview(project)
    assert result.state is ResultState.SUCCESS
    assert result.data["label"] == "PREVIEW"
    assert "not production" in result.data["note"]
