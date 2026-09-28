"""Autonomy levels, shadow-learning promotion, dry-run and rollback."""

import pytest

from app.mo.context import RequestContext
from app.mo.control.autonomy import ALLOW, CONFIRM, DENY, AutonomyManager
from app.mo.control.reversible import ReversibleLog, dry_run
from app.mo.errors import MoResult, ResultState
from app.mo.tools.spec import ToolSpec, get_tool_registry

pytestmark = pytest.mark.security


def admin(tenant, mfa=True, actor="admin-1"):
    return RequestContext(tenant_id=tenant, actor_id=actor, is_admin=True, mfa_verified=mfa, scopes=frozenset({"*"}))


def test_default_is_suggest_so_nothing_runs_unattended(db, ctx):
    a = AutonomyManager(db, ctx)
    assert a.decide("anything.at.all", "LOW")[0] == CONFIRM


@pytest.mark.parametrize("level,risk,expected", [
    (0, "LOW", DENY), (1, "LOW", CONFIRM), (2, "LOW", ALLOW), (2, "MEDIUM", CONFIRM),
    (3, "MEDIUM", ALLOW), (3, "HIGH", CONFIRM), (4, "HIGH", ALLOW), (4, "CRITICAL", CONFIRM),
    (5, "HIGH", ALLOW), (5, "CRITICAL", CONFIRM),
])
def test_level_matrix(db, tenant_a, level, risk, expected):
    a = AutonomyManager(db, admin(tenant_a))
    assert a.set_policy("crm", level, max_level=5).state.is_success
    assert a.decide("crm.update", risk)[0] == expected


def test_critical_never_runs_unattended_even_at_level_5(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    a.set_policy("deploy", 5, max_level=5)
    assert a.decide("deploy.production", "CRITICAL")[0] == CONFIRM


def test_only_admins_set_policy_and_high_levels_need_mfa(db, ctx, tenant_a):
    assert AutonomyManager(db, ctx).set_policy("crm", 2).state is ResultState.POLICY_DENIED
    no_mfa = AutonomyManager(db, admin(tenant_a, mfa=False))
    assert no_mfa.set_policy("crm", 4, max_level=5).state is ResultState.POLICY_DENIED    # ceiling raise needs MFA
    assert no_mfa.set_policy("crm", 3).state.is_success                                   # within default ceiling


def test_level_cannot_exceed_ceiling(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    assert a.set_policy("crm", 4).state is ResultState.POLICY_DENIED


def test_longest_prefix_wins(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    a.set_policy("crm", 3)
    a.set_policy("crm.delete", 1)
    assert a.policy_for("crm.update")[0] == 3
    assert a.policy_for("crm.delete_all")[0] == 3 or a.policy_for("crm.delete.record")[0] == 1
    assert a.policy_for("crm.delete.record")[0] == 1


def test_policy_is_tenant_scoped(db, tenant_a, tenant_b):
    AutonomyManager(db, admin(tenant_a)).set_policy("crm", 3)
    assert AutonomyManager(db, admin(tenant_b)).policy_for("crm.update")[0] == 1


def _feed(a, subject, agree, disagree):
    for i in range(agree + disagree):
        sid = a.propose(subject, "send_invoice", {"amount": i}).data["shadow_id"]
        a.record_decision(sid, {"amount": i} if i < agree else {"amount": -1})


def test_shadow_proposals_execute_nothing(db, tenant_a):
    res = AutonomyManager(db, admin(tenant_a)).propose("crm", "delete_lead", {"id": 1})
    assert res.data["executed"] is False


def test_promotion_refused_without_enough_evidence(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    a.set_policy("crm", 1)
    _feed(a, "crm", 5, 0)
    res = a.promote("crm")
    assert res.state is ResultState.BLOCKED and "more decided samples" in res.detail


def test_promotion_refused_when_humans_disagree(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    a.set_policy("crm", 1)
    _feed(a, "crm", 20, 6)
    res = a.promote("crm")
    assert res.state is ResultState.BLOCKED and "agreement" in res.detail


def test_promotion_one_level_on_strong_evidence_and_stops_at_ceiling(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    a.set_policy("crm", 2)
    _feed(a, "crm", 30, 0)
    assert a.promote("crm").data["level"] == 3
    assert a.promote("crm").state is ResultState.BLOCKED       # ceiling 3


def test_decision_can_only_be_recorded_once(db, tenant_a):
    a = AutonomyManager(db, admin(tenant_a))
    sid = a.propose("crm", "x", {"a": 1}).data["shadow_id"]
    assert a.record_decision(sid, {"a": 1}).data["agreed"] is True
    assert a.record_decision(sid, {"a": 2}).state is ResultState.BLOCKED


# ── dry-run and rollback ─────────────────────────────────────────────────────

@pytest.fixture
def tools():
    reg = get_tool_registry()
    state = {"value": "new", "undo_calls": 0}

    def change(ctx, p):
        state["value"] = p["value"]
        return MoResult.ok({"value": p["value"]})

    def undo(ctx, p):
        state["undo_calls"] += 1
        state["value"] = p["value"]
        return MoResult.ok()

    def broken_undo(ctx, p):
        return MoResult(ResultState.FAILED, "target vanished")

    reg.register(ToolSpec("t.change", "change", change, input_schema={"required": ["value"]}))
    reg.register(ToolSpec("t.undo", "undo", undo))
    reg.register(ToolSpec("t.broken_undo", "broken", broken_undo))
    reg.register(ToolSpec("t.risky_undo", "risky", undo, risk_level="HIGH"))
    return state


def test_dry_run_reports_gates_without_side_effects(db, ctx, tools):
    out = dry_run(db, ctx, "t.change", {})
    assert out["would_run"] is False and any("invalid input" in b for b in out["blockers"])
    ok = dry_run(db, ctx, "t.change", {"value": "x"})
    assert ok["would_run"] is True and ok["side_effects"] is False
    assert tools["value"] == "new"


def test_dry_run_flags_approval_and_unknown_tools(db, ctx, tools):
    assert dry_run(db, ctx, "t.risky_undo")["needs_approval"] is True
    assert dry_run(db, ctx, "nope")["would_run"] is False


def test_rollback_performs_the_real_undo(db, ctx, tools):
    log = ReversibleLog(db, ctx)
    rid = log.record("t.change", resource="cfg", undo_tool="t.undo", undo_payload={"value": "old"}).data["reversible_id"]
    tools["value"] = "new"
    assert log.rollback(rid).state.is_success
    assert tools["value"] == "old"
    assert log.rollback(rid).state is ResultState.BLOCKED       # not twice
    assert tools["undo_calls"] == 1


def test_rollback_respects_approval_gate_and_stays_retryable(db, ctx, tools):
    log = ReversibleLog(db, ctx)
    rid = log.record("t.change", undo_tool="t.risky_undo", undo_payload={"value": "old"}).data["reversible_id"]
    res = log.rollback(rid)
    assert res.state is ResultState.APPROVAL_REQUIRED and tools["value"] == "new"
    assert log.list("APPLIED")
    assert log.rollback(rid, approval_granted=True).state.is_success


def test_failed_rollback_is_reported_and_demotes_autonomy(db, tenant_a, tools):
    ad = admin(tenant_a)
    AutonomyManager(db, ad).set_policy("t.change", 3)
    log = ReversibleLog(db, ad)
    rid = log.record("t.change", undo_tool="t.broken_undo").data["reversible_id"]
    res = log.rollback(rid)
    assert res.state is ResultState.FAILED and "target vanished" in res.detail
    assert log.list("ROLLBACK_FAILED")
    assert AutonomyManager(db, ad).policy_for("t.change")[0] == 2


def test_unregistered_undo_tool_is_rejected_up_front(db, ctx, tools):
    assert ReversibleLog(db, ctx).record("x", undo_tool="ghost").state is ResultState.FAILED


def test_no_undo_recorded_means_no_rollback(db, ctx, tools):
    log = ReversibleLog(db, ctx)
    rid = log.record("t.change").data["reversible_id"]
    assert log.rollback(rid).state is ResultState.BLOCKED
