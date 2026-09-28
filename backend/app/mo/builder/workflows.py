"""
MO NEXUS OMEGA — Workflow Builder.

Compiles a visual node graph (Trigger/Tool/Agent/Condition/Event/Approval/Output)
into an executable definition, then actually runs it through the durable
Workflow Engine: every Tool node goes through ToolRegistry governance, every
Event node goes through the durable Event Fabric, and an Approval node blocks
execution until a real approval is granted. There is no `# Simulate step
execution` path — a node that cannot run reports why, and the run's state
reflects that.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..approvals.engine import is_granted
from ..audit import chain
from ..context import RequestContext
from ..db import BuilderWorkflow
from ..errors import MoResult, ResultState
from ..events import fabric as event_fabric
from ..tools.spec import ToolRegistry, get_tool_registry
from . import workflow_nodes as nodes
from .catalog import WorkflowSpec

VALID_NODE_TYPES = frozenset({
    "Trigger", "API", "Agent", "Tool", "Condition", "Switch", "Loop", "Parallel",
    "Transform", "Database", "Event", "Delay", "Approval", "Human Task",
    "Webhook", "Subworkflow", "Output",
})


@dataclass
class StepResult:
    node_id: str
    node_type: str
    state: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "type": self.node_type, "state": self.state,
                "detail": self.detail, "data": self.data}


def compile_workflow(spec: WorkflowSpec) -> dict[str, Any]:
    """Validate a node graph and produce the compiled, executable definition."""
    unknown = [n["type"] for n in spec.nodes if n.get("type") not in VALID_NODE_TYPES]
    if unknown:
        raise ValueError(f"Unknown node type(s): {', '.join(sorted(set(unknown)))}")
    ids = [n.get("id") for n in spec.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate node ids in workflow definition.")
    return {
        "name": spec.name, "trigger_type": spec.trigger_type,
        "nodes": [dict(n) for n in spec.nodes],
        "compiled_at": datetime.utcnow().isoformat(),
    }


def persist_workflow(
    db: Session, ctx: RequestContext, spec: WorkflowSpec, *, project_id: str,
) -> BuilderWorkflow:
    compiled = compile_workflow(spec)
    row = BuilderWorkflow(
        tenant_id=ctx.tenant_id, created_by=ctx.actor_id, project_id=project_id,
        name=spec.name, trigger_type=spec.trigger_type,
        nodes_json=json.dumps(compiled["nodes"]),
        edges_json=json.dumps([]),
        compiled_json=json.dumps(compiled),
        status="READY",
    )
    db.add(row)
    db.flush()
    chain.record(db, ctx, action="builder.workflow.compiled", result_state=ResultState.SUCCESS,
                 resource_type="workflow", resource_id=row.id, detail=spec.name)
    return row


def _state_of(res: MoResult) -> ResultState:
    return res.state


def _exec_nodes(env: "nodes.Env", node_list: list[dict[str, Any]], steps: list[StepResult], prefix: str = "") -> Optional[ResultState]:
    """Run nodes in order. Returns the state that stopped the run, or None when every node succeeded."""
    tools = env.tools
    for node in node_list:
        env.steps += 1
        node_id, node_type = prefix + str(node.get("id", "?")), node.get("type", "?")
        if env.steps > nodes.MAX_STEPS:
            steps.append(StepResult(node_id, node_type, ResultState.FAILED.value, f"Stopped: more than {nodes.MAX_STEPS} steps."))
            return ResultState.FAILED

        def record(res: MoResult) -> Optional[ResultState]:
            steps.append(StepResult(node_id, node_type, res.state.value, res.detail, res.data if isinstance(res.data, dict) else {}))
            return None if res.state.is_success else res.state

        if node_type == "Trigger":
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Triggered by {node.get('event', env.workflow.trigger_type)}."))
        elif node_type == "Tool":
            result = tools.invoke(env.ctx, node.get("tool"), nodes.render(node.get("input", {}), env.context))
            if node.get("save_as") and result.state.is_success and isinstance(result.data, dict):
                env.context[node["save_as"]] = result.data
            if (stop := record(result)):
                return stop
        elif node_type == "Event":
            topic = node.get("topic", "workflow.event")
            event = event_fabric.publish(env.db, env.ctx, topic, env.context, source=f"workflow:{env.workflow.id}")
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value, f"Published '{topic}'.", {"event_id": event.id}))
        elif node_type == "Approval":
            if is_granted(env.db, env.ctx, env.approval_id):
                steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value, "Approval verified."))
            else:
                steps.append(StepResult(node_id, node_type, ResultState.APPROVAL_REQUIRED.value,
                                        "This step requires a granted approval before the workflow can proceed."))
                return ResultState.APPROVAL_REQUIRED
        elif node_type == "Condition":
            field_name, expected = node.get("field"), node.get("equals")
            passed = env.context.get(field_name) == expected if field_name else True
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Condition {'passed' if passed else 'failed'}: {field_name} == {expected!r}."))
            if not passed and node.get("halt_on_false", True):
                return ResultState.BLOCKED
        elif node_type == "Delay":
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Delay of {node.get('seconds', 0)}s recorded (not executed in test mode)."))
        elif node_type == "Output":
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value, "Workflow reached output."))
        elif node_type in ("API", "Webhook", "Agent", "Database", "Transform", "Human Task", "Subworkflow"):
            fn = {"API": nodes.run_api, "Webhook": nodes.run_webhook, "Agent": nodes.run_agent, "Database": nodes.run_database,
                  "Transform": nodes.run_transform, "Human Task": nodes.run_human_task, "Subworkflow": nodes.run_subworkflow}[node_type]
            result = fn(env, node)
            if node.get("save_as") and result.state.is_success and isinstance(result.data, dict):
                env.context[node["save_as"]] = result.data
            if (stop := record(result)):
                return stop
        elif node_type == "Switch":
            got = env.context.get(node.get("field"))
            branch = (node.get("cases") or {}).get(str(got), node.get("default", []))
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Switch on {node.get('field')!r}={got!r}: {'matched' if str(got) in (node.get('cases') or {}) else 'default'} branch."))
            if (stop := _exec_nodes(env, branch or [], steps, f"{node_id}.")):
                return stop
        elif node_type == "Loop":
            over = nodes.get_path(env.context, node["over"]) if node.get("over") else list(range(int(node.get("count", 0))))
            if not isinstance(over, list):
                steps.append(StepResult(node_id, node_type, ResultState.FAILED.value, "Loop 'over' must point at a list."))
                return ResultState.FAILED
            limit = min(int(node.get("max_iterations", nodes.MAX_LOOP)), nodes.MAX_LOOP)
            if len(over) > limit:
                steps.append(StepResult(node_id, node_type, ResultState.FAILED.value,
                                        f"The loop has {len(over)} items; the limit is {limit}. Nothing was run."))
                return ResultState.FAILED
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value, f"Looping over {len(over)} item(s)."))
            item_key = node.get("item_key", "item")
            for i, item in enumerate(over):
                env.context[item_key], env.context["index"] = item, i
                if (stop := _exec_nodes(env, node.get("body", []), steps, f"{node_id}[{i}].")):
                    return stop
        elif node_type == "Parallel":
            branches = node.get("branches") or []
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"{len(branches)} isolated branch(es); run one after another in this build."))
            base, merged = copy.deepcopy(env.context), {}
            for b, branch in enumerate(branches):
                env.context.clear()
                env.context.update(copy.deepcopy(base))
                stop = _exec_nodes(env, branch, steps, f"{node_id}.b{b}.")
                merged.update({k: v for k, v in env.context.items() if base.get(k, nodes._MISSING) != v})
                if stop:
                    env.context.clear(); env.context.update(base)
                    return stop
            env.context.clear(); env.context.update(base); env.context.update(merged)
        else:
            steps.append(StepResult(node_id, node_type, ResultState.BLOCKED.value,
                                    f"Node type '{node_type}' has no executor wired in this build."))
            return ResultState.BLOCKED
    return None


def _run_row(row: BuilderWorkflow, env: "nodes.Env") -> MoResult:
    """Run a nested workflow (Subworkflow node) against the parent's context and return its result."""
    steps: list[StepResult] = []
    parent_wf = env.workflow
    env.workflow = row
    try:
        stop = _exec_nodes(env, json.loads(row.nodes_json or "[]"), steps, f"{row.id[:8]}/")
    finally:
        env.workflow = parent_wf
    if stop is None:
        return MoResult.ok({"steps_run": len(steps), "workflow_id": row.id})
    failing = next((x for x in steps if x.state != ResultState.SUCCESS.value), None)
    return MoResult(stop, f"Subworkflow {row.name!r} stopped at '{failing.node_id}': {failing.detail}" if failing else "Subworkflow stopped.",
                    meta={"steps": [x.to_dict() for x in steps]})


def execute_workflow(
    db: Session,
    ctx: RequestContext,
    workflow: BuilderWorkflow,
    *,
    tools: Optional[ToolRegistry] = None,
    trigger_payload: Optional[dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    http_transport: Optional[Any] = None,
) -> MoResult:
    """
    Run every node in order (nested branches included). A node that cannot complete stops the run — the
    workflow's final state is the honest worst state among its steps, never a blanket SUCCESS.
    """
    node_list: list[dict[str, Any]] = json.loads(workflow.nodes_json or "[]")
    steps: list[StepResult] = []
    env = nodes.Env(db, ctx, tools or get_tool_registry(), workflow, dict(trigger_payload or {}), approval_id,
                    http_transport, _run_row)
    final_state = _exec_nodes(env, node_list, steps) or ResultState.SUCCESS
    chain.record(
        db, ctx, action="builder.workflow.executed", result_state=final_state,
        resource_type="workflow", resource_id=workflow.id,
        detail=f"{len(steps)} step(s) ran", payload={"steps": [s.to_dict() for s in steps]},
    )
    if final_state is ResultState.SUCCESS:
        return MoResult.ok({"steps_run": len(steps), "steps_total": len(node_list),
                            "steps": [s.to_dict() for s in steps], "context": env.context})
    failing = next((s for s in steps if s.state != ResultState.SUCCESS.value), None)
    return MoResult(
        final_state,
        f"Workflow stopped at node '{failing.node_id}' ({failing.node_type}): {failing.detail}"
        if failing else "Workflow did not complete.",
        meta={"steps_run": len(steps), "steps_total": len(node_list), "steps": [s.to_dict() for s in steps]},
    )
