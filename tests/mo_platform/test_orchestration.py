"""Orchestration DAG: validation, ordering, retries, approvals, resume, budget, isolation."""

import threading
import time

import pytest

from app.mo.approvals import engine as approvals
from app.mo.context import RequestContext
from app.mo.control.autonomy import AutonomyManager
from app.mo.errors import MoResult, ResultState
from app.mo.orchestration.runner import Orchestrator
from app.mo.orchestration.spec import validate_plan
from app.mo.tools.spec import ToolSpec, get_tool_registry

pytestmark = pytest.mark.builder


def admin(tenant, actor="admin-1"):
    return RequestContext(tenant_id=tenant, actor_id=actor, is_admin=True, mfa_verified=True, scopes=frozenset({"*"}))


@pytest.fixture
def tools():
    reg = get_tool_registry()
    calls: list = []
    state = {"flaky": 0, "cost": 0.0}

    def add(ctx, p):
        calls.append(("add", p))
        return MoResult.ok({"sum": p["a"] + p["b"]})

    def echo(ctx, p):
        calls.append(("echo", p))
        return MoResult.ok({"got": p})

    def boom(ctx, p):
        calls.append(("boom", p))
        raise RuntimeError("kaput")

    def flaky(ctx, p):
        calls.append(("flaky", p))
        state["flaky"] += 1
        if state["flaky"] < 3:
            return MoResult(ResultState.TIMEOUT, "upstream slow")
        return MoResult.ok({"attempt": state["flaky"]})

    def slow(ctx, p):
        time.sleep(0.6)
        return MoResult.ok({})

    def paid(ctx, p):
        calls.append(("paid", p))
        return MoResult.ok({}, cost_usd=0.6)

    def risky(ctx, p):
        calls.append(("risky", p))
        return MoResult.ok({"done": True})

    schema = {"properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}
    for spec in (
        ToolSpec("t.add", "add", add, input_schema=schema),
        ToolSpec("t.echo", "echo", echo),
        ToolSpec("t.boom", "boom", boom),
        ToolSpec("t.flaky", "flaky", flaky),
        ToolSpec("t.slow", "slow", slow),
        ToolSpec("t.paid", "paid", paid),
        ToolSpec("t.risky", "risky", risky, risk_level="HIGH"),
        ToolSpec("domain.x.calc", "domain tool", echo),
    ):
        reg.register(spec, replace=True)
    return calls, state


@pytest.fixture
def orch(db, ctx, tenant_a, tools):
    AutonomyManager(db, admin(tenant_a)).set_policy("t", 3)
    AutonomyManager(db, admin(tenant_a)).set_policy("domain", 3)
    return Orchestrator(db, ctx, sleep=lambda s: None)


def plan(*steps, **kw):
    return {"name": "p", "steps": list(steps), **kw}


def test_validation_rejects_bad_plans(tools):
    bad = [
        ({"name": "x"}, "at least one step"),
        (plan({"key": "a", "target": "nope"}), "no tool named"),
        (plan({"key": "a", "target": "t.echo"}, {"key": "a", "target": "t.echo"}), "Duplicate"),
        (plan({"key": "a", "target": "t.echo", "depends_on": ["z"]}), "unknown step"),
        (plan({"key": "a", "target": "t.echo", "depends_on": ["b"]}, {"key": "b", "target": "t.echo", "depends_on": ["a"]}), "cycle"),
        (plan({"key": "a", "target": "t.echo", "depends_on": ["a"]}), "itself"),
        (plan({"key": "a", "target": "t.add", "input": {"a": 1}}), "missing required"),
        (plan({"key": "a", "target": "t.echo", "input": {"v": "${b.x}"}}, {"key": "b", "target": "t.echo"}), "does not list"),
        (plan({"key": "a", "target": "t.echo", "retries": 9}), "retries"),
        (plan({"key": "a", "target": "t.echo", "kind": "agent"}), "kind"),
        (plan({"key": "a", "target": "t.echo", "kind": "domain"}), "domain.*"),
    ]
    for p, needle in bad:
        assert needle in (validate_plan(p) or ""), (needle, validate_plan(p))


def test_valid_plan_and_create_is_not_executed(orch, tools):
    calls, _ = tools
    r = orch.create(plan({"key": "a", "target": "t.add", "input": {"a": 1, "b": 2}}))
    assert r.state.is_success and not calls
    assert orch.describe(r.data["run_id"])["status"] == "PENDING"


def test_dag_runs_in_order_and_passes_outputs(orch, tools):
    calls, _ = tools
    rid = orch.create(plan(
        {"key": "a", "target": "t.add", "input": {"a": 1, "b": 2}},
        {"key": "b", "target": "t.add", "input": {"a": "${a.sum}", "b": 10}, "depends_on": ["a"]},
        {"key": "c", "target": "t.echo", "input": {"msg": "total=${b.sum}"}, "depends_on": ["b"]},
    )).data["run_id"]
    out = orch.execute(rid)
    assert out.state.is_success, out
    steps = {s["key"]: s for s in out.data["steps"]}
    assert steps["b"]["output"]["sum"] == 13
    assert steps["c"]["output"]["got"]["msg"] == "total=13"
    assert [c[0] for c in calls] == ["add", "add", "echo"]
    # an unresolved template becomes a step failure, not a silent None
    rid2 = orch.create(plan(
        {"key": "a", "target": "t.echo"},
        {"key": "b", "target": "t.echo", "input": {"v": "${a.missing}"}, "depends_on": ["a"]})).data["run_id"]
    res = orch.execute(rid2)
    assert res.state is ResultState.PARTIAL
    assert "Could not resolve" in {s["key"]: s for s in res.data["steps"]}["b"]["detail"]


def test_failure_skips_dependents_but_independent_branch_finishes(orch, tools):
    rid = orch.create(plan(
        {"key": "bad", "target": "t.boom"},
        {"key": "after", "target": "t.echo", "depends_on": ["bad"]},
        {"key": "side", "target": "t.echo"})).data["run_id"]
    res = orch.execute(rid)
    assert res.state is ResultState.PARTIAL
    s = {x["key"]: x for x in res.data["steps"]}
    assert s["bad"]["status"] == "FAILED" and "kaput" in s["bad"]["detail"]
    assert s["after"]["status"] == "SKIPPED" and "bad" in s["after"]["detail"]
    assert s["side"]["status"] == "SUCCEEDED"


def test_all_failed_is_failed_not_partial(orch, tools):
    rid = orch.create(plan({"key": "bad", "target": "t.boom"})).data["run_id"]
    assert orch.execute(rid).state is ResultState.FAILED


def test_on_failure_abort_cancels_the_rest(orch, tools):
    calls, _ = tools
    rid = orch.create(plan(
        {"key": "bad", "target": "t.boom", "on_failure": "abort"},
        {"key": "later", "target": "t.echo", "depends_on": ["bad"]})).data["run_id"]
    res = orch.execute(rid)
    assert res.state is ResultState.FAILED and ("echo", {}) not in calls


def test_transient_failures_retry_but_permanent_ones_do_not(orch, tools):
    calls, state = tools
    rid = orch.create(plan({"key": "f", "target": "t.flaky", "retries": 2})).data["run_id"]
    res = orch.execute(rid)
    assert res.state.is_success and res.data["steps"][0]["attempts"] == 3
    calls.clear()
    rid = orch.create(plan({"key": "b", "target": "t.boom", "retries": 3})).data["run_id"]
    orch.execute(rid)
    assert len([c for c in calls if c[0] == "boom"]) == 1


def test_step_timeout_is_reported_as_timeout(orch, tools):
    rid = orch.create(plan({"key": "s", "target": "t.slow", "timeout_s": 0.05})).data["run_id"]
    res = orch.execute(rid)
    step = res.data["steps"][0]
    assert step["status"] == "FAILED" and step["result_state"] == "TIMEOUT"


def test_parallel_level_runs_concurrently(orch, tools):
    seen = {"max": 0, "now": 0}
    lock = threading.Lock()

    def work(ctx, p):
        with lock:
            seen["now"] += 1
            seen["max"] = max(seen["max"], seen["now"])
        time.sleep(0.15)
        with lock:
            seen["now"] -= 1
        return MoResult.ok({})

    get_tool_registry().register(ToolSpec("t.work", "w", work), replace=True)
    rid = orch.create(plan(*[{"key": f"w{i}", "target": "t.work"} for i in range(4)])).data["run_id"]
    assert orch.execute(rid, parallelism=4).state.is_success
    assert seen["max"] >= 2


def test_high_risk_step_parks_for_approval_then_resumes_without_rerunning(db, ctx, tenant_a, orch, tools):
    calls, _ = tools
    rid = orch.create(plan(
        {"key": "a", "target": "t.echo"},
        {"key": "r", "target": "t.risky", "depends_on": ["a"]},
        {"key": "z", "target": "t.echo", "depends_on": ["r"]})).data["run_id"]
    res = orch.execute(rid)
    assert res.state is ResultState.PENDING_APPROVAL
    steps = {s["key"]: s for s in res.data["steps"]}
    assert steps["r"]["status"] == "AWAITING_APPROVAL" and steps["z"]["status"] == "PENDING"
    assert not any(c[0] == "risky" for c in calls)
    approval_id = steps["r"]["approval_id"]
    # the requester cannot approve their own step
    assert approvals.decide(db, ctx, approval_id, approve=True).state is not ResultState.SUCCESS
    assert approvals.decide(db, admin(tenant_a), approval_id, approve=True).state.is_success
    calls.clear()
    res = orch.execute(rid)
    assert res.state.is_success, res
    assert [c[0] for c in calls] == ["risky", "echo"]        # step "a" was not run again


def test_rejected_approval_fails_the_step(db, ctx, tenant_a, orch, tools):
    rid = orch.create(plan({"key": "r", "target": "t.risky"})).data["run_id"]
    res = orch.execute(rid)
    aid = res.data["steps"][0]["approval_id"]
    approvals.decide(db, admin(tenant_a), aid, approve=False)
    res = orch.execute(rid)
    assert res.state is ResultState.FAILED and res.data["steps"][0]["result_state"] == "POLICY_DENIED"


def test_default_autonomy_level_confirms_even_low_risk(db, ctx, tools, tenant_b):
    # tenant_b has no policy: level 1 (SUGGEST) means a human confirms every step.
    calls, _ = tools
    other = RequestContext(tenant_id=tenant_b, actor_id="u", scopes=frozenset({"builder:write"}))
    o = Orchestrator(db, other)
    rid = o.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    res = o.execute(rid)
    assert res.state is ResultState.PENDING_APPROVAL and not calls


def test_observe_level_denies(db, tenant_a, ctx, tools):
    AutonomyManager(db, admin(tenant_a)).set_policy("t.echo", 0)
    o = Orchestrator(db, ctx)
    rid = o.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    res = o.execute(rid)
    assert res.state is ResultState.FAILED and res.data["steps"][0]["result_state"] == "POLICY_DENIED"


def test_gate_blocks_until_human_approves(db, ctx, tenant_a, orch, tools):
    calls, _ = tools
    rid = orch.create(plan(
        {"key": "g", "kind": "gate", "reason": "ship it?"},
        {"key": "e", "target": "t.echo", "depends_on": ["g"]})).data["run_id"]
    res = orch.execute(rid)
    assert res.state is ResultState.PENDING_APPROVAL and not calls
    approvals.decide(db, admin(tenant_a), res.data["steps"][0]["approval_id"], approve=True)
    assert orch.execute(rid).state.is_success and len(calls) == 1


def test_budget_stops_further_spend(orch, tools):
    calls, _ = tools
    rid = orch.create(plan(
        {"key": "p1", "target": "t.paid"},
        {"key": "p2", "target": "t.paid", "depends_on": ["p1"]},
        {"key": "p3", "target": "t.paid", "depends_on": ["p2"]}, budget_usd=1.0)).data["run_id"]
    res = orch.execute(rid)
    assert res.state is ResultState.PARTIAL
    assert len([c for c in calls if c[0] == "paid"]) == 2               # 0.6 + 0.6 crosses 1.0, third blocked
    s = {x["key"]: x for x in res.data["steps"]}
    assert s["p3"]["status"] == "SKIPPED" and "budget" in s["p3"]["detail"].lower()
    assert res.data["spent_usd"] == pytest.approx(1.2)


def test_interrupted_step_is_not_silently_rerun(db, orch, tools):
    calls, _ = tools
    from app.mo.db import OrchestrationStep
    rid = orch.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    st = db.query(OrchestrationStep).filter_by(run_id=rid).one()
    st.status = "RUNNING"
    db.flush()
    res = orch.execute(rid)
    assert res.state is ResultState.FAILED and not calls
    assert "Interrupted" in res.data["steps"][0]["detail"]
    assert orch.execute(rid, retry_failed=True).state.is_success and len(calls) == 1


def test_cancel(orch, tools):
    calls, _ = tools
    rid = orch.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    assert orch.cancel(rid).state is ResultState.CANCELLED
    assert orch.execute(rid).state is ResultState.BLOCKED and not calls
    assert orch.cancel(rid).state is ResultState.BLOCKED


def test_caller_scopes_still_apply(db, tenant_a, tools):
    reg = get_tool_registry()
    reg.register(ToolSpec("t.scoped", "s", lambda c, p: MoResult.ok({}), required_scopes=("crm:write",)), replace=True)
    AutonomyManager(db, admin(tenant_a)).set_policy("t", 3)
    weak = RequestContext(tenant_id=tenant_a, actor_id="w", scopes=frozenset({"builder:read"}))
    o = Orchestrator(db, weak)
    rid = o.create(plan({"key": "a", "target": "t.scoped"})).data["run_id"]
    res = o.execute(rid)
    assert res.state is ResultState.FAILED and res.data["steps"][0]["result_state"] == "POLICY_DENIED"


def test_tenant_isolation(db, tenant_a, tenant_b, orch, tools):
    rid = orch.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    other = Orchestrator(db, RequestContext(tenant_id=tenant_b, actor_id="x", is_admin=True, scopes=frozenset({"*"})))
    assert other.describe(rid) == {}
    assert other.execute(rid).state is ResultState.FAILED
    assert other.cancel(rid).state is ResultState.FAILED
    assert other.list_runs() == []


def test_safe_mode_blocks_execution(db, ctx, tenant_a, orch, tools):
    from app.mo.db import Tenant
    rid = orch.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    db.add(Tenant(id=tenant_a, slug=tenant_a, name="A", safe_mode=True))
    db.flush()
    assert orch.execute(rid).state is ResultState.BLOCKED


def test_step_failure_demotes_autonomy(db, tenant_a, ctx, orch, tools):
    rid = orch.create(plan({"key": "a", "target": "t.boom"})).data["run_id"]
    orch.execute(rid)
    assert AutonomyManager(db, ctx).policy_for("t.boom")[0] == 2      # 3 -> 2


def test_audit_chain_and_metrics(db, tenant_a, orch, tools):
    from app.mo.audit import chain
    from app.mo.observability.metrics import metrics
    rid = orch.create(plan({"key": "a", "target": "t.echo"})).data["run_id"]
    orch.execute(rid)
    assert chain.verify_chain(db, tenant_a)["valid"] is True
    assert metrics.counter_value("mo_run_steps_total", kind="tool", state="SUCCEEDED") >= 1
