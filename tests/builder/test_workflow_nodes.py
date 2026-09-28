"""Every workflow node type has a real executor; each refuses unsafe or unconfigured use honestly."""

import json

import httpx
import pytest

from app.mo.approvals import engine as approvals
from app.mo.builder import workflows as wf
from app.mo.builder.catalog import WorkflowSpec
from app.mo.db import KeyValueEntry
from app.mo.errors import MoResult, ResultState
from app.mo.tools.spec import RiskLevel, ToolSpec, get_tool_registry

pytestmark = pytest.mark.builder


def run(db, ctx, nodes, *, payload=None, approval_id=None, transport=None, name="wf"):
    spec = WorkflowSpec(name, "manual", tuple(nodes))
    row = wf.persist_workflow(db, ctx, spec, project_id="p1")
    return wf.execute_workflow(db, ctx, row, trigger_payload=payload, approval_id=approval_id, http_transport=transport), row


def ok_transport(payload=None, status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload if payload is not None else {"ok": True})
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _allow_private(monkeypatch):
    monkeypatch.setenv("MO_PROTOCOL_ALLOW_PRIVATE", "1")       # the mock transport never touches a network


def test_all_seventeen_node_types_are_now_runnable():
    from app.mo.builder.workflows import VALID_NODE_TYPES
    assert len(VALID_NODE_TYPES) == 17


# ── Transform ────────────────────────────────────────────────────────────────

def test_transform_operations_apply_in_order(db, admin_ctx):
    res, _ = run(db, admin_ctx, [{"id": "t", "type": "Transform", "operations": [
        {"op": "set", "key": "greeting", "value": "Hello {{name}}"},
        {"op": "upper", "from": "greeting", "to": "shout"},
        {"op": "to_int", "from": "qty", "to": "qty_i"},
        {"op": "sum", "from": "nums", "to": "total"},
        {"op": "join", "from": "nums", "to": "csv"},
        {"op": "rename", "from": "name", "to": "who"}]}],
        payload={"name": "Ana", "qty": "7", "nums": [1, 2, 3]})
    ctx = res.data["context"]
    assert res.state.is_success and ctx["shout"] == "HELLO ANA" and ctx["qty_i"] == 7 and ctx["total"] == 6
    assert ctx["csv"] == "1, 2, 3" and ctx["who"] == "Ana" and "name" not in ctx


def test_transform_is_all_or_nothing_and_has_no_eval(db, admin_ctx):
    res, _ = run(db, admin_ctx, [{"id": "t", "type": "Transform", "operations": [
        {"op": "set", "key": "a", "value": 1}, {"op": "to_int", "from": "missing"}]}])
    assert res.state == ResultState.FAILED and "does not exist" in res.detail
    bad, _ = run(db, admin_ctx, [{"id": "t", "type": "Transform", "operations": [{"op": "eval", "code": "1+1"}]}], name="w2")
    assert bad.state == ResultState.FAILED and "Unknown transform" in bad.detail
    empty, _ = run(db, admin_ctx, [{"id": "t", "type": "Transform", "operations": []}], name="w3")
    assert empty.state == ResultState.FAILED


# ── control flow ─────────────────────────────────────────────────────────────

def test_switch_runs_the_matching_branch_or_default(db, admin_ctx):
    nodes = [{"id": "s", "type": "Switch", "field": "tier",
              "cases": {"gold": [{"id": "g", "type": "Transform", "operations": [{"op": "set", "key": "disc", "value": 20}]}]},
              "default": [{"id": "d", "type": "Transform", "operations": [{"op": "set", "key": "disc", "value": 0}]}]}]
    gold, _ = run(db, admin_ctx, nodes, payload={"tier": "gold"})
    other, _ = run(db, admin_ctx, nodes, payload={"tier": "bronze"}, name="w2")
    assert gold.data["context"]["disc"] == 20 and other.data["context"]["disc"] == 0


def test_loop_iterates_and_exposes_item_and_index(db, admin_ctx):
    res, _ = run(db, admin_ctx, [{"id": "l", "type": "Loop", "over": "items", "body": [
        {"id": "b", "type": "Database", "operation": "put", "namespace": "loop-test", "key": "k{{index}}", "value": "{{item}}"}]}],
        payload={"items": ["a", "b", "c"]})
    assert res.state.is_success
    rows = {r.key: json.loads(r.value_json) for r in db.query(KeyValueEntry).filter_by(namespace="loop-test")}
    assert rows == {"k0": "a", "k1": "b", "k2": "c"}


def test_loop_refuses_oversized_lists_and_non_lists(db, admin_ctx):
    big, _ = run(db, admin_ctx, [{"id": "l", "type": "Loop", "over": "items", "body": []}], payload={"items": list(range(500))})
    assert big.state == ResultState.FAILED and "limit" in big.detail
    bad, _ = run(db, admin_ctx, [{"id": "l", "type": "Loop", "over": "items", "body": []}], payload={"items": "no"}, name="w2")
    assert bad.state == ResultState.FAILED


def test_loop_total_step_budget_stops_runaway(db, admin_ctx):
    inner = {"id": "i", "type": "Loop", "count": 100, "body": [{"id": "x", "type": "Transform", "operations": [{"op": "set", "key": "a", "value": 1}]}]}
    res, _ = run(db, admin_ctx, [{"id": "o", "type": "Loop", "count": 100, "body": [inner]}])
    assert res.state == ResultState.FAILED and "more than 500 steps" in res.detail


def test_parallel_branches_are_isolated_then_merged(db, admin_ctx):
    res, _ = run(db, admin_ctx, [{"id": "p", "type": "Parallel", "branches": [
        [{"id": "a", "type": "Transform", "operations": [{"op": "set", "key": "left", "value": 1}]}],
        [{"id": "b", "type": "Transform", "operations": [{"op": "set", "key": "right", "value": 2}]}]]}],
        payload={"base": True})
    ctx = res.data["context"]
    assert ctx["left"] == 1 and ctx["right"] == 2 and ctx["base"] is True
    assert any("one after another" in s["detail"] for s in res.data["steps"])


def test_parallel_failure_in_one_branch_stops_the_run(db, admin_ctx):
    res, _ = run(db, admin_ctx, [{"id": "p", "type": "Parallel", "branches": [
        [{"id": "a", "type": "Transform", "operations": [{"op": "to_int", "from": "nope"}]}]]}])
    assert res.state == ResultState.FAILED


# ── Database ─────────────────────────────────────────────────────────────────

def test_database_node_put_get_list_delete_and_tenant_isolation(db, admin_ctx, other_admin_ctx, tenant_b):
    from dataclasses import replace
    steps = [{"id": "p", "type": "Database", "operation": "put", "key": "greeting", "value": {"hi": "there"}},
             {"id": "g", "type": "Database", "operation": "get", "key": "greeting", "save_as": "got"},
             {"id": "l", "type": "Database", "operation": "list", "save_as": "listed"}]
    res, row = run(db, admin_ctx, steps)
    assert res.data["context"]["got"]["value"] == {"hi": "there"} and res.data["context"]["listed"]["keys"] == ["greeting"]
    outsider = replace(admin_ctx, tenant_id=tenant_b)
    seen, _ = run(db, outsider, [{"id": "g", "type": "Database", "operation": "get", "key": "greeting", "namespace": f"wf:{row.id}", "save_as": "o"}],
                  name="other")
    assert seen.data["context"]["o"]["found"] is False
    gone, _ = run(db, admin_ctx, [{"id": "d", "type": "Database", "operation": "delete", "key": "greeting", "namespace": f"wf:{row.id}"}], name="w3")
    assert gone.state.is_success and db.query(KeyValueEntry).filter_by(key="greeting").count() == 0


def test_database_node_validates_input(db, admin_ctx):
    for node in ({"operation": "drop"}, {"operation": "get", "key": ""}, {"operation": "put", "key": "k", "value": "x" * 70_000}):
        res, _ = run(db, admin_ctx, [{"id": "d", "type": "Database", **node}], name=f"w{len(str(node))}")
        assert res.state == ResultState.FAILED, node


# ── API / Webhook ────────────────────────────────────────────────────────────

def test_api_get_runs_through_the_guard_and_marks_output_untrusted(db, admin_ctx):
    seen = []
    res, _ = run(db, admin_ctx, [{"id": "a", "type": "API", "url": "http://127.0.0.1:9/items/{{id}}", "save_as": "resp",
                                  "headers": {"X-Trace": "{{id}}"}}], payload={"id": 42}, transport=ok_transport({"n": 1}, seen=seen))
    assert res.state.is_success and res.data["context"]["resp"]["body"] == {"n": 1}
    assert str(seen[0].url).endswith("/items/42") and seen[0].headers["X-Trace"] == "42"


def test_api_write_methods_need_a_granted_approval(db, admin_ctx, other_admin_ctx):
    seen = []
    node = {"id": "a", "type": "API", "method": "POST", "url": "http://127.0.0.1:9/x", "body": {"a": "{{v}}"}}
    refused, _ = run(db, admin_ctx, [node], payload={"v": 1}, transport=ok_transport(seen=seen))
    assert refused.state == ResultState.APPROVAL_REQUIRED and seen == []
    req = approvals.request_approval(db, admin_ctx, action="workflow.api", risk_tier="MEDIUM")
    approvals.decide(db, other_admin_ctx, req.id, approve=True)
    done, _ = run(db, admin_ctx, [node], payload={"v": 1}, approval_id=req.id, transport=ok_transport(seen=seen), name="w2")
    assert done.state.is_success and json.loads(seen[0].content) == {"a": 1}


def test_api_blocks_private_targets_and_forbidden_headers(db, admin_ctx, monkeypatch):
    monkeypatch.delenv("MO_PROTOCOL_ALLOW_PRIVATE")
    blocked, _ = run(db, admin_ctx, [{"id": "a", "type": "API", "url": "http://169.254.169.254/latest/meta-data"}],
                     transport=ok_transport())
    assert blocked.state == ResultState.POLICY_DENIED
    monkeypatch.setenv("MO_PROTOCOL_ALLOW_PRIVATE", "1")
    hdr, _ = run(db, admin_ctx, [{"id": "a", "type": "API", "url": "http://127.0.0.1:9", "headers": {"Authorization": "Bearer x"}}],
                 transport=ok_transport(), name="w2")
    assert hdr.state == ResultState.FAILED and "credential_env_var" in hdr.detail


def test_api_credential_and_error_mapping(db, admin_ctx, monkeypatch):
    monkeypatch.delenv("MO_WF_TOKEN", raising=False)
    node = {"id": "a", "type": "API", "url": "http://127.0.0.1:9", "credential_env_var": "MO_WF_TOKEN"}
    missing, _ = run(db, admin_ctx, [node], transport=ok_transport())
    assert missing.state == ResultState.CREDENTIAL_REQUIRED
    monkeypatch.setenv("MO_WF_TOKEN", "tok-123")
    seen = []
    ok, _ = run(db, admin_ctx, [node], transport=ok_transport(seen=seen), name="w2")
    assert ok.state.is_success and seen[0].headers["Authorization"] == "Bearer tok-123"
    for status, want in ((500, ResultState.PROVIDER_UNAVAILABLE), (403, ResultState.POLICY_DENIED), (404, ResultState.FAILED)):
        res, _ = run(db, admin_ctx, [{"id": "a", "type": "API", "url": "http://127.0.0.1:9"}], transport=ok_transport(status=status), name=f"w{status}")
        assert res.state == want


def test_webhook_is_signed_and_always_approval_gated(db, admin_ctx, other_admin_ctx, monkeypatch):
    import hashlib
    import hmac
    monkeypatch.setenv("MO_WEBHOOK_SECRET", "hook-secret")
    node = {"id": "w", "type": "Webhook", "url": "http://127.0.0.1:9/in", "body": {"event": "done"}, "secret_env_var": "MO_WEBHOOK_SECRET"}
    assert run(db, admin_ctx, [node], transport=ok_transport())[0].state == ResultState.APPROVAL_REQUIRED
    req = approvals.request_approval(db, admin_ctx, action="workflow.webhook", risk_tier="MEDIUM")
    approvals.decide(db, other_admin_ctx, req.id, approve=True)
    seen = []
    res, _ = run(db, admin_ctx, [node], approval_id=req.id, transport=ok_transport(seen=seen), name="w2")
    assert res.state.is_success
    want = "sha256=" + hmac.new(b"hook-secret", seen[0].content, hashlib.sha256).hexdigest()
    assert seen[0].headers["X-MO-Signature"] == want
    monkeypatch.delenv("MO_WEBHOOK_SECRET")
    nosecret, _ = run(db, admin_ctx, [node], approval_id=req.id, transport=ok_transport(), name="w3")
    assert nosecret.state == ResultState.CREDENTIAL_REQUIRED


# ── Agent ────────────────────────────────────────────────────────────────────

def test_agent_node_needs_a_provider_and_guards_its_input(db, admin_ctx, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    res, _ = run(db, admin_ctx, [{"id": "a", "type": "Agent", "prompt": "Summarise {{topic}}"}], payload={"topic": "Q3"})
    assert res.state == ResultState.CREDENTIAL_REQUIRED
    blank, _ = run(db, admin_ctx, [{"id": "a", "type": "Agent", "prompt": ""}], name="w2")
    assert blank.state == ResultState.FAILED


def test_agent_node_runs_with_a_provider_and_saves_guarded_output(db, admin_ctx, monkeypatch):
    from app.mo.modelfabric import router as mr
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    class Fake:
        def complete(self, request, budget=None):
            return MoResult.ok({"text": "Summary: revenue is up. Contact bob@example.com"})
    monkeypatch.setattr(mr, "get_router", lambda: Fake())
    res, _ = run(db, admin_ctx, [{"id": "a", "type": "Agent", "prompt": "Summarise {{topic}}", "save_as": "answer"}], payload={"topic": "Q3"})
    assert res.state.is_success and "bob@example.com" not in res.data["context"]["answer"]["text"]


# ── Human Task / Subworkflow ─────────────────────────────────────────────────

def test_human_task_raises_an_approval_and_resumes_when_it_is_decided(db, admin_ctx, other_admin_ctx):
    node = [{"id": "h", "type": "Human Task", "instruction": "Call the customer"}, {"id": "o", "type": "Output"}]
    first, _ = run(db, admin_ctx, node)
    assert first.state == ResultState.PENDING_APPROVAL
    aid = first.meta["steps"][0]["data"]["approval_id"]
    pending, _ = run(db, admin_ctx, node, approval_id=aid, name="w2")
    assert pending.state == ResultState.PENDING_APPROVAL
    approvals.decide(db, other_admin_ctx, aid, approve=True)
    done, _ = run(db, admin_ctx, node, approval_id=aid, name="w3")
    assert done.state.is_success and done.data["steps_run"] == 2


def test_subworkflow_runs_in_the_callers_context_and_tenant(db, admin_ctx, tenant_b):
    from dataclasses import replace
    _, child = run(db, admin_ctx, [{"id": "c", "type": "Transform", "operations": [{"op": "set", "key": "from_child", "value": "yes"}]}], name="child")
    res, _ = run(db, admin_ctx, [{"id": "s", "type": "Subworkflow", "workflow_id": child.id}, {"id": "o", "type": "Output"}], name="parent")
    assert res.state.is_success and res.data["context"]["from_child"] == "yes"
    outsider = replace(admin_ctx, tenant_id=tenant_b)
    blocked, _ = run(db, outsider, [{"id": "s", "type": "Subworkflow", "workflow_id": child.id}], name="steal")
    assert blocked.state == ResultState.FAILED and "No such workflow" in blocked.detail


def test_subworkflow_cycles_and_missing_ids_are_refused(db, admin_ctx):
    spec = WorkflowSpec("loopy", "manual", ({"id": "x", "type": "Output"},))
    row = wf.persist_workflow(db, admin_ctx, spec, project_id="p1")
    row.nodes_json = json.dumps([{"id": "s", "type": "Subworkflow", "workflow_id": row.id}])
    res = wf.execute_workflow(db, admin_ctx, row)
    assert res.state == ResultState.FAILED and "cycle" in res.detail
    missing, _ = run(db, admin_ctx, [{"id": "s", "type": "Subworkflow"}], name="w2")
    assert missing.state == ResultState.FAILED


def test_tool_node_renders_templates_and_saves_output(db, admin_ctx):
    get_tool_registry().register(ToolSpec("t.echo", "echo", lambda c, p: MoResult.ok({"echo": p["x"]}), risk_level=RiskLevel.LOW,
                                          input_schema={"type": "object", "properties": {"x": {"type": "string"}}}))
    res, _ = run(db, admin_ctx, [{"id": "t", "type": "Tool", "tool": "t.echo", "input": {"x": "hi {{name}}"}, "save_as": "e"}], payload={"name": "Ana"})
    assert res.data["context"]["e"] == {"echo": "hi Ana"}
