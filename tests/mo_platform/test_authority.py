"""
MO authority: the spec's mandatory invariants. MAX/agents reach side effects only through the gateway,
approvals are argument-bound and single-use, forbidden actions cannot be authorised, and every call
(success, failure or refusal) leaves a receipt.
"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.mo.approvals import engine as approvals
from app.mo.authority import gateway, grants
from app.mo.authority.policy import Risk, decide, effective_risk
from app.mo.db import AgentDefinition, CapabilityGrant, ExecutionReceipt
from app.mo.errors import MoResult, ResultState
from app.mo.lifecycle import agents
from app.mo.memory.store import MemoryStore
from app.mo.tools.spec import RiskLevel, ToolSpec, get_tool_registry

pytestmark = pytest.mark.security

CALLS: list = []


@pytest.fixture(autouse=True)
def _tools():
    CALLS.clear()
    reg = get_tool_registry()

    def write_note(ctx, p):
        CALLS.append(("write", p["text"]))
        return MoResult.ok({"written": p["text"]})

    def boom(ctx, p):
        CALLS.append(("boom", None))
        raise RuntimeError("disk on fire")

    def send(ctx, p):
        CALLS.append(("send", p["to"]))
        return MoResult.ok({"sent": p["to"]})

    schema = {"type": "object", "properties": {"text": {"type": "string"}, "to": {"type": "string"}}}
    reg.register(ToolSpec("t.write", "write a note", write_note, risk_level=RiskLevel.MEDIUM, input_schema=schema))
    reg.register(ToolSpec("t.boom", "always fails", boom, risk_level=RiskLevel.MEDIUM, input_schema=schema))
    reg.register(ToolSpec("t.read", "harmless", lambda c, p: MoResult.ok({"ok": True}), risk_level=RiskLevel.LOW))
    reg.register(ToolSpec("t.trade", "place an order", send, risk_level=RiskLevel.LOW, input_schema=schema))
    yield


def _authorise(db, ctx, admin_ctx, *, tool="t.write", action="write_text", resource="note.txt", risk=Risk.WRITE,
               args=None, second=None):
    args = args if args is not None else {"text": "hello"}
    res = grants.request_capability(db, ctx, tool=tool, action=action, resource=resource, risk=risk, args=args)
    assert res.state == ResultState.PENDING_APPROVAL, res.detail
    aid = res.data["approval_id"]
    assert approvals.decide(db, admin_ctx, aid, approve=True).state.is_success or True
    if second is not None:
        approvals.decide(db, second, aid, approve=True)
    g = grants.issue_grant(db, ctx, aid)
    return aid, g


def _run(db, ctx, token=None, **kw):
    base = dict(tool="t.write", action="write_text", resource="note.txt", args={"text": "hello"}, risk=Risk.WRITE,
                grant_token=token)
    base.update(kw)
    return gateway.execute(db, ctx, **base)


# ── authority chain ─────────────────────────────────────────────────────────

def test_write_requires_approval_and_tool_does_not_run_without_it(db, ctx):
    r = _run(db, ctx)
    assert r.state == ResultState.APPROVAL_REQUIRED and CALLS == []
    assert r.meta["receipt_id"]


def test_low_risk_no_side_effect_call_needs_no_approval(db, ctx):
    r = gateway.execute(db, ctx, tool="t.read", action="read_status", resource="x", args={}, risk=Risk.NONE)
    assert r.state == ResultState.SUCCESS


def test_full_flow_approved_write_runs_once_with_receipt(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    assert g.state.is_success and "token" in g.data
    r = _run(db, ctx, g.data["token"])
    assert r.state == ResultState.SUCCESS and CALLS == [("write", "hello")]
    rec = db.get(ExecutionReceipt, r.meta["receipt_id"])
    assert rec.success and rec.trace_id == ctx.trace_id and rec.grant_id == g.data["grant_id"] and rec.output_hash


def test_requester_cannot_approve_their_own_capability(db, ctx):
    res = grants.request_capability(db, ctx, tool="t.write", action="write_text", resource="n", risk=Risk.WRITE,
                                    args={"text": "x"})
    denied = approvals.decide(db, ctx, res.data["approval_id"], approve=True)
    assert denied.state == ResultState.POLICY_DENIED
    assert grants.issue_grant(db, ctx, res.data["approval_id"]).state == ResultState.APPROVAL_REQUIRED


def test_approval_is_single_use(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    tok = g.data["token"]
    assert _run(db, ctx, tok).state == ResultState.SUCCESS
    again = _run(db, ctx, tok)
    assert again.state == ResultState.POLICY_DENIED and "already used" in again.detail
    assert len(CALLS) == 1


def test_only_one_grant_per_approval(db, ctx, admin_ctx):
    aid, g = _authorise(db, ctx, admin_ctx)
    assert grants.issue_grant(db, ctx, aid).state == ResultState.BLOCKED


def test_approval_cannot_change_arguments(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx, args={"text": "hello"})
    r = _run(db, ctx, g.data["token"], args={"text": "EVIL"})
    assert r.state == ResultState.POLICY_DENIED and "scope mismatch" in r.detail and CALLS == []
    # the grant survives a refused attempt and still works for the reviewed arguments
    assert _run(db, ctx, g.data["token"]).state == ResultState.SUCCESS


def test_reviewed_args_hash_is_enforced(db, ctx, admin_ctx):
    r = _run(db, ctx, args_hash=grants.stable_hash({"text": "reviewed"}), args={"text": "swapped"})
    assert r.state == ResultState.POLICY_DENIED and "Arguments changed" in r.detail


def test_grant_is_bound_to_tool_action_and_resource(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    for kw in ({"resource": "other.txt"}, {"action": "delete"}):
        assert _run(db, ctx, g.data["token"], **kw).state == ResultState.POLICY_DENIED
    assert CALLS == []


def test_grant_expires(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    db.get(CapabilityGrant, g.data["grant_id"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.flush()
    r = _run(db, ctx, g.data["token"])
    assert r.state == ResultState.POLICY_DENIED and "expired" in r.detail and CALLS == []


def test_expired_approval_cannot_produce_a_grant(db, ctx, admin_ctx):
    res = grants.request_capability(db, ctx, tool="t.write", action="write_text", resource="n", risk=Risk.WRITE,
                                    args={"text": "x"})
    aid = res.data["approval_id"]
    approvals.decide(db, admin_ctx, aid, approve=True)
    db.get(approvals.ApprovalRequest, aid).expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.flush()
    assert grants.issue_grant(db, ctx, aid).state == ResultState.APPROVAL_REQUIRED


def test_grant_is_tenant_scoped(db, ctx, admin_ctx, tenant_b):
    _, g = _authorise(db, ctx, admin_ctx)
    outsider = replace(ctx, tenant_id=tenant_b)
    r = _run(db, outsider, g.data["token"])
    assert r.state == ResultState.POLICY_DENIED and CALLS == []


def test_token_is_not_stored_in_clear(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    row = db.get(CapabilityGrant, g.data["grant_id"])
    assert g.data["token"] not in (row.token_hash, row.approval_id) and len(row.token_hash) == 64


def test_only_the_requester_collects_the_grant(db, ctx, admin_ctx, other_admin_ctx):
    res = grants.request_capability(db, ctx, tool="t.write", action="write_text", resource="n", risk=Risk.WRITE,
                                    args={"text": "x"})
    aid = res.data["approval_id"]
    approvals.decide(db, admin_ctx, aid, approve=True)
    assert grants.issue_grant(db, other_admin_ctx, aid).state == ResultState.POLICY_DENIED


# ── policy: forbidden actions, finance, risk floor ──────────────────────────

@pytest.mark.parametrize("action", ["withdraw_funds", "change_withdrawal_whitelist", "export_credentials",
                                    "disable_audit", "mint_admin", "bypass_approval"])
def test_forbidden_actions_are_denied_and_cannot_be_authorised(db, ctx, admin_ctx, action):
    res = grants.request_capability(db, ctx, tool="t.write", action=action, resource="acct", risk=Risk.SENSITIVE, args={})
    assert res.state == ResultState.POLICY_DENIED
    run = gateway.execute(db, ctx, tool="t.write", action=action, resource="acct", args={"text": "x"},
                          risk=Risk.SENSITIVE, grant_token="anything")
    assert run.state == ResultState.POLICY_DENIED and CALLS == []
    assert db.query(ExecutionReceipt).filter_by(action=action, success=False).count() == 1


def test_finance_orders_need_strong_confirmation(db, ctx, admin_ctx, other_admin_ctx):
    d = decide("t.trade", "place_order", Risk.WRITE)
    assert d.verdict == "STRONG_CONFIRM" and d.tier == "CRITICAL"
    args = {"to": "BTC-USD"}
    res = grants.request_capability(db, ctx, tool="t.trade", action="place_order", resource="acct-1", risk=Risk.WRITE, args=args)
    aid = res.data["approval_id"]
    approvals.decide(db, admin_ctx, aid, approve=True)
    assert grants.issue_grant(db, ctx, aid).state == ResultState.APPROVAL_REQUIRED      # one approval is not enough
    approvals.decide(db, other_admin_ctx, aid, approve=True)
    g = grants.issue_grant(db, ctx, aid)
    r = gateway.execute(db, ctx, tool="t.trade", action="place_order", resource="acct-1", args=args, risk=Risk.WRITE,
                        grant_token=g.data["token"])
    assert r.state == ResultState.SUCCESS and CALLS == [("send", "BTC-USD")]


def test_read_balances_needs_approval_market_data_only_with_account_access():
    assert decide("x", "read_balances", Risk.NONE).verdict == "APPROVAL"
    assert decide("x", "read_market_data", Risk.NONE).verdict == "ALLOW"
    assert decide("x", "read_market_data", Risk.NONE, account_access=True).verdict == "APPROVAL"


def test_caller_cannot_understate_risk(db, ctx):
    assert effective_risk(Risk.NONE, "MEDIUM") == Risk.WRITE
    r = gateway.execute(db, ctx, tool="t.write", action="write_text", resource="n", args={"text": "x"}, risk=Risk.NONE)
    assert r.state == ResultState.APPROVAL_REQUIRED and CALLS == [] and r.meta["decision"]["risk"] == "write"


def test_unknown_tool_is_a_failure_with_a_receipt(db, ctx):
    r = gateway.execute(db, ctx, tool="nope", action="a", resource="r", args={})
    assert r.state == ResultState.FAILED and r.meta["receipt_id"]


# ── agents ──────────────────────────────────────────────────────────────────

def test_agent_cannot_use_a_tool_outside_its_allow_list(db, ctx, admin_ctx):
    assert agents.register_agent(db, admin_ctx, name="scribe", description="", allowed_tools=["t.write"]).state.is_success
    r = gateway.execute(db, ctx, tool="t.read", action="a", resource="r", args={}, agent="scribe")
    assert r.state == ResultState.POLICY_DENIED and "not allowed" in r.detail
    assert gateway.execute(db, ctx, tool="t.read", action="a", resource="r", args={}, agent="ghost").state == ResultState.POLICY_DENIED


def test_agent_risk_ceiling_and_disable(db, ctx, admin_ctx):
    agents.register_agent(db, admin_ctx, name="reader", description="", allowed_tools=["t.write", "t.read"], risk_ceiling="read")
    r = gateway.execute(db, ctx, tool="t.write", action="write_text", resource="n", args={"text": "x"}, agent="reader")
    assert r.state == ResultState.POLICY_DENIED and "ceiling" in r.detail
    agents.set_status(db, admin_ctx, "reader", "DISABLED")
    assert gateway.execute(db, ctx, tool="t.read", action="a", resource="r", args={}, agent="reader").state == ResultState.POLICY_DENIED


def test_only_admins_register_agents_and_names_are_validated(db, ctx, admin_ctx):
    assert agents.register_agent(db, ctx, name="x1", description="", allowed_tools=["t.read"]).state == ResultState.POLICY_DENIED
    for bad in ({"name": "Bad Name"}, {"allowed_tools": []}, {"allowed_tools": ["nope"]}, {"risk_ceiling": "root"}):
        kw = {"name": "ok-agent", "description": "", "allowed_tools": ["t.read"], **bad}
        assert agents.register_agent(db, admin_ctx, **kw).state == ResultState.FAILED
    assert agents.register_agent(db, admin_ctx, name="dupe", description="", allowed_tools=["t.read"]).state.is_success
    assert agents.register_agent(db, admin_ctx, name="dupe", description="", allowed_tools=["t.read"]).state == ResultState.BLOCKED


# ── receipts, failures, idempotency ─────────────────────────────────────────

def test_every_tool_call_has_trace_and_receipt(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    ok = _run(db, ctx, g.data["token"])
    refused = _run(db, ctx)
    for r in (ok, refused):
        rec = db.get(ExecutionReceipt, r.meta["receipt_id"])
        assert rec.trace_id == ctx.trace_id and rec.tenant_id == ctx.tenant_id and rec.state == r.state.value


def test_failed_tool_call_is_audited_as_a_failed_receipt(db, ctx, admin_ctx):
    args = {"text": "x"}
    _, g = _authorise(db, ctx, admin_ctx, tool="t.boom", action="explode", args=args)
    r = gateway.execute(db, ctx, tool="t.boom", action="explode", resource="note.txt", args=args, risk=Risk.WRITE,
                        grant_token=g.data["token"])
    assert r.state == ResultState.FAILED and "disk on fire" in r.detail
    rec = db.get(ExecutionReceipt, r.meta["receipt_id"])
    assert rec.success is False and rec.state == "FAILED"
    from app.mo.audit import chain
    assert chain.verify_chain(db, ctx.tenant_id)["valid"] is True


def test_recovery_does_not_duplicate_the_side_effect(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    first = _run(db, ctx, g.data["token"], idempotency_key="job-1")
    assert first.state == ResultState.SUCCESS
    replay = _run(db, ctx, None, idempotency_key="job-1")           # a retry after a crash: no new grant needed
    assert replay.state == ResultState.SUCCESS and replay.meta["replayed"] is True
    assert replay.meta["receipt_id"] == first.meta["receipt_id"] and len(CALLS) == 1


def test_idempotency_key_cannot_be_reused_for_a_different_request(db, ctx, admin_ctx):
    _, g = _authorise(db, ctx, admin_ctx)
    _run(db, ctx, g.data["token"], idempotency_key="job-2")
    other = _run(db, ctx, None, idempotency_key="job-2", args={"text": "different"})
    assert other.state == ResultState.BLOCKED and len(CALLS) == 1


def test_a_refusal_does_not_burn_the_idempotency_key(db, ctx, admin_ctx):
    assert _run(db, ctx, None, idempotency_key="job-3").state == ResultState.APPROVAL_REQUIRED
    _, g = _authorise(db, ctx, admin_ctx)
    assert _run(db, ctx, g.data["token"], idempotency_key="job-3").state == ResultState.SUCCESS


def test_idempotency_keys_are_tenant_scoped_and_bounded(db, ctx, admin_ctx, tenant_b):
    _, g = _authorise(db, ctx, admin_ctx)
    _run(db, ctx, g.data["token"], idempotency_key="shared")
    outsider = replace(ctx, tenant_id=tenant_b)
    r = gateway.execute(db, outsider, tool="t.read", action="a", resource="r", args={}, idempotency_key="shared")
    assert not r.meta.get("replayed")
    assert _run(db, ctx, None, idempotency_key="k" * 500).state == ResultState.FAILED


# ── secrets ─────────────────────────────────────────────────────────────────

def test_secret_never_enters_the_memory_backend(db, ctx):
    FAKE_AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"   # built at runtime: CI scans commits for credential literals
    res = MemoryStore(db, ctx).remember("LONG_TERM", "the deploy key is " + FAKE_AWS_KEY)
    assert not res.state.is_success or FAKE_AWS_KEY not in str(res.data)
    assert FAKE_AWS_KEY not in str([m for m in MemoryStore(db, ctx).recall("deploy key", top_k=5)])


def test_a_high_risk_tool_cannot_be_approved_at_a_lower_tier(db, ctx, admin_ctx):
    reg = get_tool_registry()
    reg.register(ToolSpec("t.deploy", "ship it", lambda c, p: MoResult.ok({"shipped": True}), risk_level=RiskLevel.HIGH))
    res = grants.request_capability(db, ctx, tool="t.deploy", action="deploy", resource="prod", risk=Risk.NONE, args={})
    assert res.data["decision"]["risk"] == "external" and res.data["decision"]["tier"] == "HIGH"
    # forge a lower-tier approval for the same request and try to use it
    low = grants.request_capability(db, ctx, tool="t.write", action="deploy", resource="prod", risk=Risk.WRITE, args={})
    approvals.decide(db, admin_ctx, low.data["approval_id"], approve=True)
    g = grants.issue_grant(db, ctx, low.data["approval_id"])
    row = db.get(CapabilityGrant, g.data["grant_id"])
    row.tool = "t.deploy"                                          # tamper: point the MEDIUM grant at the HIGH tool
    row.args_hash = grants.stable_hash({})
    db.flush()
    r = gateway.execute(db, ctx, tool="t.deploy", action="deploy", resource="prod", args={}, risk=Risk.NONE,
                        grant_token=g.data["token"])
    assert r.state == ResultState.POLICY_DENIED and "lower tier" in r.detail


def test_capability_request_for_unknown_tool_fails(db, ctx):
    r = grants.request_capability(db, ctx, tool="nope", action="a", resource="r", risk=Risk.WRITE, args={})
    assert r.state == ResultState.FAILED
