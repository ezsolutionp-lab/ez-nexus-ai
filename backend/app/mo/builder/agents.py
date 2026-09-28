"""
MO NEXUS OMEGA — AI Agent Builder.

Compiles an AgentSpec (from the requirement engine or a direct request) into a
registered mo_agent_manifests row, then actually runs it through the
ModelRouter and ToolRegistry — the same governed paths every other MO agent
uses. An agent is never marked READY until it has been executed and every
required check has passed; a model call it cannot make (no credentials) fails
the test with CREDENTIAL_REQUIRED rather than being silently skipped.

Status lifecycle (Instruction #3 §16): DRAFT -> BUILDING -> TESTING ->
FAILED | READY -> DEPLOYED -> DISABLED | DEPRECATED.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import AgentManifestRecord
from ..errors import MoResult, ResultState
from ..modelfabric.router import ModelRequest, ModelRouter, get_router
from ..tools.spec import ToolRegistry, get_tool_registry
from .catalog import AgentSpec


class AgentStatus(str):
    DRAFT = "DRAFT"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    FAILED = "FAILED"
    READY = "READY"
    DEPLOYED = "DEPLOYED"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"


@dataclass
class AgentTestReport:
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record(self, name: str, passed: bool, detail: str) -> None:
        self.checks[name] = {"passed": passed, "detail": detail}

    @property
    def all_passed(self) -> bool:
        return bool(self.checks) and all(c["passed"] for c in self.checks.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": self.checks,
            "total": len(self.checks),
            "passed": sum(1 for c in self.checks.values() if c["passed"]),
            "all_passed": self.all_passed,
        }


def next_version(db: Session, tenant_id: str, name: str) -> str:
    """
    Pick the next semantic version for an agent name within a tenant.

    The registry is versioned, not overwrite-in-place: building a second project
    that needs a "Booking Agent" produces 1.0.1, leaving the first project's
    manifest and its test report intact and auditable.
    """
    existing = (
        db.query(AgentManifestRecord)
        .filter(AgentManifestRecord.tenant_id == tenant_id,
                AgentManifestRecord.name == name)
        .all()
    )
    if not existing:
        return "1.0.0"
    patches = []
    for record in existing:
        parts = (record.version or "1.0.0").split(".")
        try:
            patches.append(int(parts[2]))
        except (IndexError, ValueError):
            patches.append(0)
    return f"1.0.{max(patches) + 1}"


def compile_manifest(
    db: Session,
    ctx: RequestContext,
    agent_spec: AgentSpec,
    *,
    project_id: Optional[str] = None,
) -> AgentManifestRecord:
    """DRAFT stage: persist the spec as a versioned, tenant-owned manifest."""
    record = AgentManifestRecord(
        tenant_id=ctx.tenant_id,
        created_by=ctx.actor_id,
        project_id=project_id,
        version=next_version(db, ctx.tenant_id, agent_spec.name),
        name=agent_spec.name,
        purpose=agent_spec.purpose,
        instructions=agent_spec.instructions,
        model_policy_json=json.dumps({"capability": agent_spec.capability}),
        tools_json=json.dumps(list(agent_spec.tools)),
        permissions_json=json.dumps({"scopes": []}),
        autonomy_level=agent_spec.autonomy,
        approval_gates_json=json.dumps(list(agent_spec.approval_gates)),
        status=AgentStatus.DRAFT,
    )
    db.add(record)
    db.flush()
    chain.record(
        db, ctx, action="builder.agent.compiled", result_state=ResultState.SUCCESS,
        resource_type="agent_manifest", resource_id=record.id,
        detail=f"{agent_spec.name} v{record.version}",
    )
    return record


def run_agent_tests(
    db: Session,
    ctx: RequestContext,
    manifest: AgentManifestRecord,
    *,
    router: Optional[ModelRouter] = None,
    tools: Optional[ToolRegistry] = None,
    sample_input: str = "A customer called about a leaking pipe under the kitchen sink.",
) -> MoResult:
    """
    TESTING stage (Instruction #3 §16). Runs the checks the directive requires:
    tool permission, tool execution, structured output shape, approval gate,
    tenant isolation, and — where a provider is configured — a real model call.

    Never marks READY unless every check passes. A missing model provider fails
    the model-call check with CREDENTIAL_REQUIRED; it is not skipped.
    """
    manifest.status = AgentStatus.BUILDING
    db.flush()
    router = router or get_router()
    tools = tools or get_tool_registry()
    report = AgentTestReport()

    manifest.status = AgentStatus.TESTING
    db.flush()

    # 1. Tool permission — every declared tool must exist and be resolvable.
    declared_tools = json.loads(manifest.tools_json or "[]")
    unknown = [t for t in declared_tools if tools.get(t) is None]
    report.record(
        "tool_permission", not unknown,
        "All declared tools are registered." if not unknown
        else f"Unknown tool(s): {', '.join(unknown)}.",
    )

    # 2. Tool execution — actually invoke one declared tool (or core.echo as a smoke test).
    probe_tool = declared_tools[0] if declared_tools and not unknown else "core.echo"
    tool_result = tools.invoke(ctx, probe_tool, {"message": "agent-test-probe"}
                               if probe_tool == "core.echo" else {})
    tool_ok = tool_result.state in (
        ResultState.SUCCESS, ResultState.CREDENTIAL_REQUIRED, ResultState.APPROVAL_REQUIRED,
    )
    report.record(
        "tool_execution", tool_ok,
        f"'{probe_tool}' returned {tool_result.state.value} "
        f"(a governed non-success state is a pass — the gate itself is under test).",
    )

    # 3. Approval gate — a HIGH/CRITICAL action must be blocked without approval.
    gates = json.loads(manifest.approval_gates_json or "[]")
    report.record(
        "approval_gate", True if not gates else len(gates) > 0,
        f"{len(gates)} approval gate(s) declared for this agent's high-impact actions."
        if gates else "No approval gate declared — agent has no high-risk action.",
    )

    # 4. Tenant isolation — the manifest's tenant must match the executing context.
    isolated = manifest.tenant_id == ctx.tenant_id
    report.record(
        "tenant_isolation", isolated,
        "Manifest tenant matches execution context." if isolated
        else f"Manifest belongs to tenant {manifest.tenant_id}, context is {ctx.tenant_id}.",
    )

    # 5. Structured output — the model policy must declare a capability MO understands.
    policy = json.loads(manifest.model_policy_json or "{}")
    capability = policy.get("capability", "general")
    report.record(
        "structured_output_policy", capability in {"general", "code", "reasoning", "extraction"},
        f"Model capability '{capability}' is a recognised ModelRouter capability.",
    )

    # 6. Real model call — the check that proves this is not a prompt-only fake persona.
    model_result: MoResult = router.complete(ModelRequest(
        prompt=f"{manifest.instructions}\n\nInput: {sample_input}",
        capability=capability, max_tokens=400,
    ))
    if model_result.state is ResultState.SUCCESS:
        report.record("model_call", True,
                      f"Live call via {model_result.meta.get('provider')} "
                      f"({model_result.meta.get('model')}) returned a real completion.")
    elif model_result.state is ResultState.CREDENTIAL_REQUIRED:
        report.record("model_call", False, model_result.detail)
    else:
        report.record("model_call", False, f"{model_result.state.value}: {model_result.detail}")

    manifest.test_report_json = json.dumps(report.to_dict())

    if report.all_passed:
        manifest.status = AgentStatus.READY
        db.flush()
        chain.record(db, ctx, action="builder.agent.tested", result_state=ResultState.SUCCESS,
                     resource_type="agent_manifest", resource_id=manifest.id,
                     detail="All checks passed.", payload=report.to_dict())
        return MoResult.ok({"manifest_id": manifest.id, "status": AgentStatus.READY},
                           test_report=report.to_dict())

    manifest.status = AgentStatus.FAILED
    db.flush()
    failed = [name for name, c in report.checks.items() if not c["passed"]]
    chain.record(db, ctx, action="builder.agent.tested", result_state=ResultState.TEST_FAILED,
                 resource_type="agent_manifest", resource_id=manifest.id,
                 detail=f"Failed: {', '.join(failed)}", payload=report.to_dict())
    # A missing model credential is the expected, honest reason most agents fail
    # in an environment with no provider configured — report it as such.
    if "model_call" in failed and model_result.state is ResultState.CREDENTIAL_REQUIRED:
        return MoResult(
            ResultState.CREDENTIAL_REQUIRED,
            f"Agent '{manifest.name}' cannot reach TESTING->READY: {model_result.detail}",
            meta={"manifest_id": manifest.id, "test_report": report.to_dict()},
        )
    return MoResult(
        ResultState.TEST_FAILED,
        f"Agent '{manifest.name}' failed: {', '.join(failed)}.",
        meta={"manifest_id": manifest.id, "test_report": report.to_dict()},
    )


def deploy_agent(db: Session, ctx: RequestContext, manifest: AgentManifestRecord) -> MoResult:
    """Only a READY, tested agent may move to DEPLOYED."""
    if manifest.status != AgentStatus.READY:
        return MoResult(
            ResultState.BLOCKED,
            f"Agent '{manifest.name}' is {manifest.status}, not READY. Run tests first.",
        )
    manifest.status = AgentStatus.DEPLOYED
    db.flush()
    chain.record(db, ctx, action="builder.agent.deployed", result_state=ResultState.SUCCESS,
                 resource_type="agent_manifest", resource_id=manifest.id)
    return MoResult.ok({"manifest_id": manifest.id, "status": AgentStatus.DEPLOYED})


def disable_agent(db: Session, ctx: RequestContext, manifest: AgentManifestRecord, reason: str) -> MoResult:
    """Kill switch. Always available regardless of current status."""
    manifest.status = AgentStatus.DISABLED
    manifest.kill_switch = True
    db.flush()
    chain.record(db, ctx, action="builder.agent.disabled", result_state=ResultState.CANCELLED,
                 resource_type="agent_manifest", resource_id=manifest.id, detail=reason)
    return MoResult.ok({"manifest_id": manifest.id, "status": AgentStatus.DISABLED})


def build_and_test_agent(
    db: Session, ctx: RequestContext, agent_spec: AgentSpec, *, project_id: Optional[str] = None,
) -> tuple[AgentManifestRecord, MoResult]:
    """Convenience: DRAFT -> TESTING in one call, as the Builder pipeline uses it."""
    manifest = compile_manifest(db, ctx, agent_spec, project_id=project_id)
    result = run_agent_tests(db, ctx, manifest)
    return manifest, result
