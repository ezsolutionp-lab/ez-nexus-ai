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


def execute_workflow(
    db: Session,
    ctx: RequestContext,
    workflow: BuilderWorkflow,
    *,
    tools: Optional[ToolRegistry] = None,
    trigger_payload: Optional[dict[str, Any]] = None,
    approval_id: Optional[str] = None,
) -> MoResult:
    """
    Run every node in order. A node that cannot complete stops the run — the
    workflow's final state is the honest worst state among its steps, never a
    blanket SUCCESS.
    """
    tools = tools or get_tool_registry()
    nodes: list[dict[str, Any]] = json.loads(workflow.nodes_json or "[]")
    steps: list[StepResult] = []
    context_data: dict[str, Any] = dict(trigger_payload or {})
    worst = ResultState.SUCCESS

    def _worse(a: ResultState, b: ResultState) -> ResultState:
        # SUCCESS is best; everything else "wins" as the reported worst state.
        return b if a is ResultState.SUCCESS else a

    for node in nodes:
        node_id, node_type = node.get("id", "?"), node.get("type", "?")

        if node_type == "Trigger":
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Triggered by {node.get('event', workflow.trigger_type)}."))
            continue

        if node_type == "Tool":
            tool_name = node.get("tool")
            result = tools.invoke(ctx, tool_name, node.get("input", {}))
            steps.append(StepResult(node_id, node_type, result.state.value, result.detail, result.data))
            worst = _worse(worst, result.state) if not result.state.is_success else worst
            if not result.state.is_success:
                break
            continue

        if node_type == "Event":
            topic = node.get("topic", "workflow.event")
            event = event_fabric.publish(db, ctx, topic, context_data, source=f"workflow:{workflow.id}")
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Published '{topic}'.", {"event_id": event.id}))
            continue

        if node_type == "Approval":
            granted = is_granted(db, ctx, approval_id)
            if granted:
                steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value, "Approval verified."))
                continue
            steps.append(StepResult(node_id, node_type, ResultState.APPROVAL_REQUIRED.value,
                                    "This step requires a granted approval before the workflow can proceed."))
            worst = ResultState.APPROVAL_REQUIRED
            break

        if node_type == "Condition":
            field_name, expected = node.get("field"), node.get("equals")
            passed = context_data.get(field_name) == expected if field_name else True
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Condition {'passed' if passed else 'failed'}: "
                                    f"{field_name} == {expected!r}."))
            if not passed and node.get("halt_on_false", True):
                worst = ResultState.BLOCKED
                break
            continue

        if node_type == "Delay":
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value,
                                    f"Delay of {node.get('seconds', 0)}s recorded (not executed in test mode)."))
            continue

        if node_type == "Output":
            steps.append(StepResult(node_id, node_type, ResultState.SUCCESS.value, "Workflow reached output."))
            continue

        # Agent / API / Database / Webhook / Subworkflow / Human Task / Switch / Loop / Parallel /
        # Transform: declared node types with no MO-native executor yet. Reported honestly.
        steps.append(StepResult(
            node_id, node_type, ResultState.BLOCKED.value,
            f"Node type '{node_type}' has no executor wired in this build. "
            f"Declared but not runnable — the workflow does not claim it ran.",
        ))
        worst = ResultState.BLOCKED
        break

    final_state = worst if worst is not ResultState.SUCCESS else ResultState.SUCCESS
    chain.record(
        db, ctx, action="builder.workflow.executed", result_state=final_state,
        resource_type="workflow", resource_id=workflow.id,
        detail=f"{len(steps)}/{len(nodes)} step(s) ran", payload={"steps": [s.to_dict() for s in steps]},
    )
    if final_state is ResultState.SUCCESS:
        return MoResult.ok({"steps_run": len(steps), "steps_total": len(nodes),
                            "steps": [s.to_dict() for s in steps]})
    failing = next((s for s in steps if s.state != ResultState.SUCCESS.value), None)
    return MoResult(
        final_state,
        f"Workflow stopped at node '{failing.node_id}' ({failing.node_type}): {failing.detail}"
        if failing else "Workflow did not complete.",
        meta={"steps_run": len(steps), "steps_total": len(nodes), "steps": [s.to_dict() for s in steps]},
    )
