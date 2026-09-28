"""Foundation tests: result states, context, audit chain, model fabric, tools, sandbox."""

import pytest

from app.mo.context import RequestContext, system_context
from app.mo.errors import MoError, MoResult, ResultState


# ── Result envelope ──────────────────────────────────────────────────────────

def test_non_success_result_requires_a_reason():
    with pytest.raises(ValueError):
        MoResult(ResultState.FAILED)
    assert MoResult(ResultState.FAILED, "disk full").detail == "disk full"


def test_success_result_reports_ok():
    r = MoResult.ok({"x": 1})
    assert r.to_dict() == {"state": "SUCCESS", "ok": True, "data": {"x": 1}}


def test_credential_required_names_the_env_var():
    r = MoResult.credential_required("Twilio", "TWILIO_AUTH_TOKEN")
    assert r.state is ResultState.CREDENTIAL_REQUIRED
    assert "TWILIO_AUTH_TOKEN" in r.detail
    assert r.state.is_success is False


# ── Context / Zero Trust primitives ──────────────────────────────────────────

def test_missing_scope_is_denied(ctx):
    ctx.require_scope("builder:read")
    with pytest.raises(MoError) as exc:
        ctx.require_scope("builder:deploy")
    assert exc.value.state is ResultState.POLICY_DENIED


@pytest.mark.security
def test_cross_tenant_access_is_denied(ctx, tenant_b):
    with pytest.raises(MoError) as exc:
        ctx.require_same_tenant(tenant_b, "Project X")
    assert exc.value.state is ResultState.POLICY_DENIED


@pytest.mark.security
def test_resource_without_tenant_is_denied(ctx):
    with pytest.raises(MoError):
        ctx.require_same_tenant(None, "Orphan row")


@pytest.mark.security
def test_derived_agent_context_cannot_inherit_admin(admin_ctx):
    child = admin_ctx.child(actor_type="agent", actor_label="Booking", source_channel="AGENT")
    assert child.is_admin is False
    assert child.tenant_id == admin_ctx.tenant_id
    assert child.trace_id == admin_ctx.trace_id


def test_mfa_step_up_required(ctx):
    with pytest.raises(MoError) as exc:
        ctx.require_mfa("builder.deploy")
    assert "multi-factor" in exc.value.detail


def test_system_context_is_not_request_reachable():
    sc = system_context()
    assert sc.actor_type == "system" and sc.source_channel == "SYSTEM"


# ── Audit chain ──────────────────────────────────────────────────────────────

def test_audit_chain_validates_and_detects_tampering(db, ctx):
    from sqlalchemy import text
    from app.mo.audit import chain

    for i in range(5):
        chain.record(db, ctx, action="test.action", result_state=ResultState.SUCCESS,
                     resource_type="thing", resource_id=str(i))
    db.flush()
    assert chain.verify_chain(db, ctx.tenant_id)["valid"] is True

    db.execute(text("UPDATE mo_audit_events SET action='tampered' WHERE tenant_id=:t AND seq=3"),
               {"t": ctx.tenant_id})
    db.flush()
    report = chain.verify_chain(db, ctx.tenant_id)
    assert report["valid"] is False
    assert report["broken_at_seq"] == 3


def test_audit_redacts_secrets_at_every_depth(db, ctx):
    from app.mo.audit import chain
    ev = chain.record(
        db, ctx, action="test.secret", result_state=ResultState.SUCCESS,
        payload={"api_key": "sk-live-1", "nested": {"password": "hunter2", "keep": "visible"}},
    )
    assert "sk-live-1" not in ev.payload_json
    assert "hunter2" not in ev.payload_json
    assert "visible" in ev.payload_json


@pytest.mark.security
def test_audit_chains_are_isolated_per_tenant(db, ctx, tenant_b):
    from app.mo.audit import chain
    other = RequestContext(tenant_id=tenant_b, actor_id="u9")
    chain.record(db, ctx, action="a", result_state=ResultState.SUCCESS)
    chain.record(db, other, action="b", result_state=ResultState.SUCCESS)
    db.flush()
    assert chain.tenant_event_count(db, ctx.tenant_id) == 1
    assert chain.tenant_event_count(db, tenant_b) == 1
    assert chain.verify_chain(db, tenant_b)["valid"] is True


# ── Model fabric ─────────────────────────────────────────────────────────────

def test_router_reports_credential_required_when_unconfigured():
    from app.mo.modelfabric.router import ModelRequest, ModelRouter
    r = ModelRouter().complete(ModelRequest(prompt="hi"))
    assert r.state is ResultState.CREDENTIAL_REQUIRED
    assert "ANTHROPIC_API_KEY" in r.detail


def _adapters():
    from app.mo.modelfabric.router import ModelAdapter, ModelResponse

    class Failing(ModelAdapter):
        name = "failing"; credential_env_var = "F_KEY"
        supported_capabilities = frozenset({"general"})
        def is_configured(self): return True
        def complete(self, req): raise RuntimeError("upstream 503")

    class Working(ModelAdapter):
        name = "working"; credential_env_var = "W_KEY"
        supported_capabilities = frozenset({"general"})
        def is_configured(self): return True
        def complete(self, req):
            return ModelResponse(text="real", provider="working", model="m",
                                 input_tokens=8, output_tokens=4, cost_usd=0.002)
    return Failing, Working


def test_router_falls_back_to_a_healthy_provider():
    from app.mo.modelfabric.router import ModelRequest, ModelRouter
    Failing, Working = _adapters()
    res = ModelRouter([Failing(), Working()]).complete(ModelRequest(prompt="x"))
    assert res.state is ResultState.SUCCESS
    assert res.meta["provider"] == "working"


def test_router_opens_circuit_after_repeated_failures():
    from app.mo.modelfabric.router import ModelRequest, ModelRouter
    Failing, _ = _adapters()
    r = ModelRouter([Failing()])
    for _ in range(3):
        assert r.complete(ModelRequest(prompt="x")).state is ResultState.PROVIDER_UNAVAILABLE
    assert r._health["failing"].circuit_open is True


def test_router_blocks_when_budget_exhausted():
    from app.mo.modelfabric.router import Budget, ModelRequest, ModelRouter
    _, Working = _adapters()
    r, b = ModelRouter([Working()]), Budget(limit_usd=0.001)
    assert r.complete(ModelRequest(prompt="x"), b).state is ResultState.SUCCESS
    assert r.complete(ModelRequest(prompt="x"), b).state is ResultState.BLOCKED


@pytest.mark.security
def test_router_refuses_restricted_data_on_unapproved_provider():
    from app.mo.modelfabric.router import ModelRequest, ModelRouter
    _, Working = _adapters()
    res = ModelRouter([Working()]).complete(
        ModelRequest(prompt="x", data_classification="RESTRICTED"))
    assert res.state is ResultState.POLICY_DENIED


# ── Tool governance ──────────────────────────────────────────────────────────

def test_tool_runs_and_returns_real_output(ctx):
    from app.mo.tools.spec import get_tool_registry
    res = get_tool_registry().invoke(ctx, "core.echo", {"message": "ping"})
    assert res.state is ResultState.SUCCESS
    assert res.data["echo"] == "ping"


def test_unknown_tool_fails_rather_than_returning_success(ctx):
    from app.mo.tools.spec import get_tool_registry
    assert get_tool_registry().invoke(ctx, "no.such.tool").state is ResultState.FAILED


def test_tool_input_schema_is_enforced(ctx):
    from app.mo.tools.spec import get_tool_registry
    reg = get_tool_registry()
    assert reg.invoke(ctx, "core.echo", {}).state is ResultState.FAILED
    assert reg.invoke(ctx, "text.slugify", {"text": 42}).state is ResultState.FAILED


@pytest.mark.security
def test_tool_requires_declared_scope(ctx):
    from app.mo.tools.spec import get_tool_registry
    res = get_tool_registry().invoke(ctx, "net.http_fetch", {"url": "https://example.test"})
    assert res.state is ResultState.POLICY_DENIED
    assert "tool:net" in res.detail


@pytest.mark.security
def test_high_risk_tool_is_approval_gated(admin_ctx):
    from app.mo.tools.spec import get_tool_registry
    res = get_tool_registry().invoke(admin_ctx, "payments.charge",
                                     {"amount_cents": 100, "currency": "usd"})
    assert res.state is ResultState.APPROVAL_REQUIRED


@pytest.mark.security
def test_critical_tool_requires_mfa(tenant_a):
    from app.mo.tools.spec import get_tool_registry
    no_mfa = RequestContext(tenant_id=tenant_a, actor_id="a", is_admin=True, mfa_verified=False)
    res = get_tool_registry().invoke(no_mfa, "payments.charge",
                                     {"amount_cents": 1, "currency": "usd"}, approval_granted=True)
    assert res.state is ResultState.POLICY_DENIED


def test_tool_without_credentials_never_claims_success(admin_ctx):
    from app.mo.tools.spec import get_tool_registry
    res = get_tool_registry().invoke(
        admin_ctx, "comms.send_email", {"to": "a@b.com", "subject": "s", "body": "b"})
    assert res.state is ResultState.CREDENTIAL_REQUIRED
    assert "SMTP_PASSWORD" in res.detail


def test_tool_rate_limit_is_enforced(admin_ctx):
    from app.mo.tools.spec import get_tool_registry
    reg = get_tool_registry()
    states = [reg.invoke(admin_ctx, "core.echo", {"message": "x"}).state for _ in range(62)]
    assert ResultState.RATE_LIMITED in states


def test_tool_exception_becomes_failure_not_success(ctx):
    from app.mo.tools.spec import RiskLevel, ToolSpec, get_tool_registry
    reg = get_tool_registry()

    def boom(_ctx, _payload):
        raise ValueError("handler exploded")

    reg.register(ToolSpec(name="test.boom", description="raises", handler=boom,
                          risk_level=RiskLevel.LOW), replace=True)
    res = reg.invoke(ctx, "test.boom", {})
    assert res.state is ResultState.FAILED
    assert "handler exploded" in res.detail


def test_tool_returning_wrong_type_is_rejected(ctx):
    from app.mo.tools.spec import ToolSpec, get_tool_registry
    reg = get_tool_registry()
    reg.register(ToolSpec(name="test.bad", description="returns a dict",
                          handler=lambda c, p: {"looks": "fine"}), replace=True)
    assert reg.invoke(ctx, "test.bad", {}).state is ResultState.FAILED


# ── Sandbox ──────────────────────────────────────────────────────────────────

@pytest.mark.security
def test_sandbox_does_not_expose_host_secrets(workspace_root, monkeypatch):
    from app.mo.sandbox import runner
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@host/db")
    res = runner.run(
        [runner.python_executable(), "-c",
         "import os;print(os.getenv('ANTHROPIC_API_KEY'),os.getenv('DATABASE_URL'))"],
        workspace_root,
    )
    assert res.exit_code == 0
    assert "sk-should-not-leak" not in res.stdout
    assert "secret@host" not in res.stdout


def test_sandbox_reports_failure_honestly(workspace_root):
    from app.mo.sandbox import runner
    res = runner.run([runner.python_executable(), "-c", "raise SystemExit(7)"], workspace_root)
    assert res.ok is False
    assert res.as_result("build").state is ResultState.BUILD_FAILED


def test_sandbox_kills_a_hanging_command(workspace_root):
    from app.mo.sandbox import runner
    res = runner.run([runner.python_executable(), "-c", "import time;time.sleep(30)"],
                     workspace_root, runner.SandboxProfile(wall_timeout_seconds=2))
    assert res.timed_out is True
    assert res.as_result("build").state is ResultState.TIMEOUT


def test_sandbox_enforces_memory_ceiling(workspace_root):
    from app.mo.sandbox import runner
    res = runner.run(
        [runner.python_executable(), "-c", "x=bytearray(400*1024*1024);print('allocated')"],
        workspace_root, runner.SandboxProfile(memory_mb=64, wall_timeout_seconds=30),
    )
    assert res.exit_code != 0
    assert "allocated" not in res.stdout


def test_sandbox_reports_missing_executable(workspace_root):
    from app.mo.sandbox import runner
    res = runner.run(["mo-not-a-real-binary"], workspace_root)
    assert res.exit_code == 127
