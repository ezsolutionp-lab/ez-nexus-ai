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
    assert "nothing was deployed" in result.detail and "MO_DEPLOY_ADAPTER" in result.detail


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


# ── deployment adapters ─────────────────────────────────────────────────────

import hashlib
import hmac
import json

import httpx

from app.mo.builder import deploy as deploy_mod


def _approved(db, built_project, other_admin_ctx, env="staging"):
    compiler, project = built_project
    req = compiler.request_deployment(project, env)
    approvals.decide(db, other_admin_ctx, req.meta["approval_id"], approve=True)
    return compiler, project, req.meta["deployment_id"]


def test_no_adapter_means_nothing_deploys(db, built_project, other_admin_ctx, monkeypatch):
    monkeypatch.delenv("MO_DEPLOY_ADAPTER", raising=False)
    compiler, _, dep = _approved(db, built_project, other_admin_ctx)
    assert compiler.execute_deployment(dep).state is ResultState.CREDENTIAL_REQUIRED
    assert deploy_mod.adapter_status()["active"] is None


def test_unknown_adapter_name_is_reported_not_silently_used(monkeypatch):
    monkeypatch.setenv("MO_DEPLOY_ADAPTER", "teleport")
    assert deploy_mod.selected_adapter() is None and deploy_mod.adapter_status()["misconfigured"] is True


def test_export_bundle_writes_a_checksummed_zip_and_reports_partial(db, built_project, other_admin_ctx, monkeypatch, tmp_path):
    monkeypatch.setenv("MO_DEPLOY_ADAPTER", "export-bundle")
    monkeypatch.setenv("MO_DEPLOY_ARTIFACT_DIR", str(tmp_path))
    compiler, project, dep = _approved(db, built_project, other_admin_ctx)
    res = compiler.execute_deployment(dep)
    assert res.state is ResultState.PARTIAL and res.data["launched"] is False and "Nothing was launched" in res.detail
    from pathlib import Path
    bundle = Path(res.data["bundle"])
    assert str(bundle).startswith(str(tmp_path)) and bundle.exists() and hashlib.sha256(bundle.read_bytes()).hexdigest() == res.data["sha256"]
    meta = json.loads(bundle.with_suffix(".json").read_text())
    assert meta["launched"] is False and meta["environment"] == "staging"
    from app.mo.db import BuilderDeployment
    row = db.get(BuilderDeployment, dep)
    assert row.state == "PARTIAL" and row.deployed_at is None


def test_adapter_is_not_reached_without_a_granted_approval(db, built_project, monkeypatch, tmp_path):
    monkeypatch.setenv("MO_DEPLOY_ADAPTER", "export-bundle")
    monkeypatch.setenv("MO_DEPLOY_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    compiler, project = built_project
    dep = compiler.request_deployment(project, "staging").meta["deployment_id"]
    assert compiler.execute_deployment(dep).state is ResultState.APPROVAL_REQUIRED
    assert not (tmp_path / "artifacts").exists()


def test_deploy_hook_signs_the_payload_and_never_claims_success(db, built_project, other_admin_ctx, monkeypatch):
    monkeypatch.setenv("MO_DEPLOY_ADAPTER", "deploy-hook")
    monkeypatch.setenv("MO_PROTOCOL_ALLOW_PRIVATE", "1")
    monkeypatch.setenv("MO_DEPLOY_HOOK_STAGING_URL", "http://127.0.0.1:9/hook")
    monkeypatch.setenv("MO_DEPLOY_HOOK_SECRET", "hook-secret")
    seen = []
    monkeypatch.setattr(deploy_mod, "transport", httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(202))[1]))
    compiler, project, dep = _approved(db, built_project, other_admin_ctx)
    res = compiler.execute_deployment(dep)
    assert res.state is ResultState.PARTIAL and res.data["triggered"] is True and "unconfirmed" in res.detail
    want = "sha256=" + hmac.new(b"hook-secret", seen[0].content, hashlib.sha256).hexdigest()
    assert seen[0].headers["X-MO-Signature"] == want and json.loads(seen[0].content)["environment"] == "staging"


def test_deploy_hook_failure_modes(db, built_project, other_admin_ctx, monkeypatch):
    monkeypatch.setenv("MO_DEPLOY_ADAPTER", "deploy-hook")
    monkeypatch.setenv("MO_PROTOCOL_ALLOW_PRIVATE", "1")
    compiler, project, dep = _approved(db, built_project, other_admin_ctx)
    monkeypatch.delenv("MO_DEPLOY_HOOK_STAGING_URL", raising=False)
    assert compiler.execute_deployment(dep).state is ResultState.CREDENTIAL_REQUIRED
    monkeypatch.setenv("MO_DEPLOY_HOOK_STAGING_URL", "http://127.0.0.1:9/hook")
    monkeypatch.setattr(deploy_mod, "transport", httpx.MockTransport(lambda r: httpx.Response(500)))
    assert compiler.execute_deployment(dep).state is ResultState.DEPLOYMENT_FAILED
    def boom(request):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(deploy_mod, "transport", httpx.MockTransport(boom))
    assert compiler.execute_deployment(dep).state is ResultState.TIMEOUT
    monkeypatch.delenv("MO_PROTOCOL_ALLOW_PRIVATE")
    assert compiler.execute_deployment(dep).state is ResultState.POLICY_DENIED


def test_production_hook_needs_its_own_url(db, built_project, other_admin_ctx, monkeypatch):
    monkeypatch.setenv("MO_DEPLOY_ADAPTER", "deploy-hook")
    monkeypatch.setenv("MO_DEPLOY_HOOK_STAGING_URL", "http://127.0.0.1:9/hook")
    monkeypatch.delenv("MO_DEPLOY_HOOK_PRODUCTION_URL", raising=False)
    compiler, project = built_project
    req = compiler.request_deployment(project, "production")
    approvals.decide(db, other_admin_ctx, req.meta["approval_id"], approve=True)
    from dataclasses import replace
    third = replace(other_admin_ctx, actor_id="admin-3")
    approvals.decide(db, third, req.meta["approval_id"], approve=True)
    res = compiler.execute_deployment(req.meta["deployment_id"])
    assert res.state is ResultState.CREDENTIAL_REQUIRED and "PRODUCTION" in res.detail
