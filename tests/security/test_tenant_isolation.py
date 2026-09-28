"""
Cross-tenant attack tests (Instruction #1 §36, Instruction #3 §21).

Every one of these asserts that tenant A cannot see, change or act on tenant B's
data through the MO surface.
"""

import pytest

from app.mo.builder.compiler import BuilderCompiler
from app.mo.builder.intent import BuildIntent
from app.mo.context import RequestContext
from app.mo.db import BuilderFile, BuilderProject
from app.mo.errors import MoError, ResultState

pytestmark = pytest.mark.security


@pytest.fixture
def two_tenant_projects(db, tenant_a, tenant_b, workspace_root):
    def ctx_for(tenant):
        return RequestContext(tenant_id=tenant, actor_id=f"user-{tenant}",
                              is_admin=True, mfa_verified=True, scopes=frozenset({"*"}))

    ctx_a, ctx_b = ctx_for(tenant_a), ctx_for(tenant_b)
    project_a, _ = BuilderCompiler(db, ctx_a, workspace_root=workspace_root).compile(
        BuildIntent(prompt="Build a plumbing website with a contact form.",
                    tenant_id=tenant_a, requested_by=ctx_a.actor_id),
        run_build=False)
    project_b, _ = BuilderCompiler(db, ctx_b, workspace_root=workspace_root).compile(
        BuildIntent(prompt="Build a dental clinic website with online booking.",
                    tenant_id=tenant_b, requested_by=ctx_b.actor_id),
        run_build=False)
    return (ctx_a, project_a), (ctx_b, project_b)


def test_a_project_cannot_be_read_across_tenants(two_tenant_projects):
    (ctx_a, _), (_, project_b) = two_tenant_projects
    with pytest.raises(MoError) as exc:
        ctx_a.require_same_tenant(project_b.tenant_id, f"Project {project_b.id}")
    assert exc.value.state is ResultState.POLICY_DENIED


def test_compiler_refuses_to_build_into_another_tenant(db, tenant_a, tenant_b, workspace_root):
    ctx = RequestContext(tenant_id=tenant_a, actor_id="u1", is_admin=True, scopes=frozenset({"*"}))
    intent = BuildIntent(prompt="Build a site.", tenant_id=tenant_b, requested_by="u1")
    with pytest.raises(MoError) as exc:
        BuilderCompiler(db, ctx, workspace_root=workspace_root).create_project(intent)
    assert exc.value.state is ResultState.POLICY_DENIED


def test_intent_from_request_pins_tenant_to_the_caller(tenant_a, tenant_b):
    """A client cannot smuggle another tenant in through the request body."""
    ctx = RequestContext(tenant_id=tenant_a, actor_id="u1")
    intent = BuildIntent.from_request(ctx, {
        "prompt": "Build a site.",
        "tenant_id": tenant_b,          # attacker-supplied — must be ignored
        "requested_by": "someone-else",
    })
    assert intent.tenant_id == tenant_a
    assert intent.requested_by == "u1"


def test_build_refuses_a_foreign_project(db, two_tenant_projects, workspace_root):
    (ctx_a, _), (_, project_b) = two_tenant_projects
    with pytest.raises(MoError) as exc:
        BuilderCompiler(db, ctx_a, workspace_root=workspace_root).build(project_b)
    assert exc.value.state is ResultState.POLICY_DENIED


def test_export_refuses_a_foreign_project(db, two_tenant_projects):
    from app.mo.builder import export
    (ctx_a, _), (_, project_b) = two_tenant_projects
    with pytest.raises(MoError):
        export.export_zip(db, ctx_a, project_b)


def test_every_generated_row_carries_the_owning_tenant(db, two_tenant_projects):
    (ctx_a, project_a), (ctx_b, project_b) = two_tenant_projects
    for project, tenant in ((project_a, ctx_a.tenant_id), (project_b, ctx_b.tenant_id)):
        files = db.query(BuilderFile).filter(BuilderFile.project_id == project.id).all()
        assert files
        assert all(f.tenant_id == tenant for f in files)


def test_a_tenant_scoped_query_returns_only_its_own_projects(db, two_tenant_projects):
    (ctx_a, project_a), (ctx_b, project_b) = two_tenant_projects
    visible = db.query(BuilderProject).filter(
        BuilderProject.tenant_id == ctx_a.tenant_id).all()
    ids = {p.id for p in visible}
    assert project_a.id in ids
    assert project_b.id not in ids


def test_approval_cannot_be_decided_across_tenants(db, two_tenant_projects, tenant_b):
    from app.mo.approvals import engine as approvals
    (ctx_a, project_a), _ = two_tenant_projects
    approval = approvals.request_approval(
        db, ctx_a, action="builder.deploy.staging",
        resource_type="project", resource_id=project_a.id)
    intruder = RequestContext(tenant_id=tenant_b, actor_id="intruder",
                              is_admin=True, mfa_verified=True, scopes=frozenset({"*"}))
    with pytest.raises(MoError) as exc:
        approvals.decide(db, intruder, approval.id, approve=True)
    assert exc.value.state is ResultState.POLICY_DENIED
