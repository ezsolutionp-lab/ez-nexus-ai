"""AI Agent Builder tests — real compile, real test gates, real lifecycle."""

import pytest

from app.mo.builder.agents import (
    AgentStatus, build_and_test_agent, compile_manifest, deploy_agent, disable_agent, run_agent_tests,
)
from app.mo.builder.catalog import AgentSpec
from app.mo.errors import ResultState


def _spec(**overrides) -> AgentSpec:
    base = dict(
        name="Test Booking Agent", role="scheduler",
        purpose="Turn a message into a booking proposal.",
        instructions="Extract service, urgency and time windows as JSON.",
        tools=("core.echo",), capability="extraction", approval_gates=("booking.confirm",),
    )
    base.update(overrides)
    return AgentSpec(**base)


def test_compile_persists_a_draft_manifest(db, ctx):
    manifest = compile_manifest(db, ctx, _spec())
    assert manifest.status == AgentStatus.DRAFT
    assert manifest.tenant_id == ctx.tenant_id
    assert manifest.id is not None


def test_agent_without_credentials_fails_honestly_not_silently(db, ctx):
    manifest, result = build_and_test_agent(db, ctx, _spec())
    assert manifest.status == AgentStatus.FAILED
    assert result.state is ResultState.CREDENTIAL_REQUIRED
    assert "ANTHROPIC_API_KEY" in result.detail or "OPENAI_API_KEY" in result.detail


def test_test_report_names_every_check(db, ctx):
    manifest, result = build_and_test_agent(db, ctx, _spec())
    import json
    report = json.loads(manifest.test_report_json)
    expected = {"tool_permission", "tool_execution", "approval_gate",
                "tenant_isolation", "structured_output_policy", "model_call"}
    assert expected <= set(report["checks"])


def test_unknown_tool_fails_the_tool_permission_check(db, ctx):
    manifest, result = build_and_test_agent(db, ctx, _spec(tools=("no.such.tool",)))
    import json
    report = json.loads(manifest.test_report_json)
    assert report["checks"]["tool_permission"]["passed"] is False


def test_agent_never_reaches_ready_without_passing_every_check(db, ctx):
    """The directive's rule (Instruction #3 §16): do not mark READY unless tests pass."""
    manifest, result = build_and_test_agent(db, ctx, _spec())
    assert manifest.status != AgentStatus.READY
    assert result.state is not ResultState.SUCCESS


def test_agent_reaches_ready_with_a_working_provider(db, ctx):
    from app.mo.modelfabric.router import ModelAdapter, ModelResponse, get_router

    class FakeWorking(ModelAdapter):
        name = "fake"; credential_env_var = "FAKE_KEY"
        supported_capabilities = frozenset({"general", "code", "reasoning", "extraction"})
        def is_configured(self): return True
        def complete(self, req):
            return ModelResponse(text='{"service":"leak repair"}', provider="fake",
                                 model="fake-1", input_tokens=10, output_tokens=5, cost_usd=0.001)

    router = get_router()
    router._adapters = [FakeWorking()]
    router._health = {a.name: router._health.get(a.name) for a in router._adapters}
    from app.mo.modelfabric.router import ProviderHealth
    router._health["fake"] = ProviderHealth(name="fake", configured=True)

    manifest, result = build_and_test_agent(db, ctx, _spec())
    assert manifest.status == AgentStatus.READY
    assert result.state is ResultState.SUCCESS


def test_deploy_requires_ready_status(db, ctx):
    manifest = compile_manifest(db, ctx, _spec())
    res = deploy_agent(db, ctx, manifest)
    assert res.state is ResultState.BLOCKED
    assert manifest.status == AgentStatus.DRAFT


def test_kill_switch_disables_from_any_state(db, ctx):
    manifest = compile_manifest(db, ctx, _spec())
    res = disable_agent(db, ctx, manifest, "safety stop")
    assert res.state is ResultState.SUCCESS
    assert manifest.status == AgentStatus.DISABLED
    assert manifest.kill_switch is True


@pytest.mark.security
def test_agent_test_run_detects_tenant_mismatch(db, ctx, other_admin_ctx):
    """A manifest tested under a different tenant context fails tenant_isolation."""
    manifest = compile_manifest(db, ctx, _spec())
    from app.mo.context import RequestContext
    wrong_tenant_ctx = RequestContext(tenant_id="tnt-intruder", actor_id="x", is_admin=True, mfa_verified=True)
    result = run_agent_tests(db, wrong_tenant_ctx, manifest)
    import json
    report = json.loads(manifest.test_report_json)
    assert report["checks"]["tenant_isolation"]["passed"] is False


def test_same_agent_name_in_one_tenant_gets_a_new_version(db, ctx):
    """
    Two projects in one tenant can both need a "Booking Agent". The registry
    versions the manifest rather than colliding on its unique key.
    """
    first = compile_manifest(db, ctx, _spec(), project_id="project-1")
    second = compile_manifest(db, ctx, _spec(), project_id="project-2")
    third = compile_manifest(db, ctx, _spec(), project_id="project-3")
    assert [first.version, second.version, third.version] == ["1.0.0", "1.0.1", "1.0.2"]
    assert first.id != second.id
    # The earlier manifest is preserved, not overwritten.
    assert first.project_id == "project-1"


def test_versions_are_independent_across_tenants(db, ctx, tenant_b):
    from app.mo.context import RequestContext
    compile_manifest(db, ctx, _spec())
    other = RequestContext(tenant_id=tenant_b, actor_id="u2")
    assert compile_manifest(db, other, _spec()).version == "1.0.0"
