"""
MO NEXUS OMEGA — Agent registry.

An agent is a name, a description, an allow-list of tools and a risk ceiling. It never holds a
tool handle: to act it asks the capability gateway, which refuses any tool not on its list, any
call above its ceiling, and any call from an agent that is disabled or unregistered.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..authority.policy import Risk
from ..context import RequestContext
from ..db import AgentDefinition
from ..errors import MoResult, ResultState
from ..tools.spec import ToolRegistry, get_tool_registry

_NAME = re.compile(r"^[a-z0-9][a-z0-9._\-]{1,63}$")
MAX_TOOLS = 100


def tool_manifest_hash(tools: list[str], registry: ToolRegistry) -> str:
    items = sorted((t, registry.get(t).risk_level if registry.get(t) else "UNKNOWN") for t in tools)
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


def agent_dict(a: AgentDefinition) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "description": a.description, "allowed_tools": json.loads(a.allowed_tools_json),
            "risk_ceiling": a.risk_ceiling, "status": a.status}


def register_agent(db: Session, ctx: RequestContext, *, name: str, description: str, allowed_tools: list[str],
                   risk_ceiling: str = "write", registry: Optional[ToolRegistry] = None) -> MoResult:
    reg = registry or get_tool_registry()
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator can register an agent.")
    if not isinstance(name, str) or not _NAME.match(name):
        return MoResult(ResultState.FAILED, "Agent name must be 2-64 characters: lowercase letters, digits, . _ -")
    if not isinstance(allowed_tools, list) or not allowed_tools or len(allowed_tools) > MAX_TOOLS \
            or not all(isinstance(t, str) for t in allowed_tools):
        return MoResult(ResultState.FAILED, f"allowed_tools must be a list of 1-{MAX_TOOLS} tool names.")
    unknown = sorted(t for t in set(allowed_tools) if reg.get(t) is None)
    if unknown:
        return MoResult(ResultState.FAILED, f"Unknown tool(s): {', '.join(unknown)}.")
    try:
        ceiling = Risk(risk_ceiling.lower())
    except ValueError:
        return MoResult(ResultState.FAILED, "risk_ceiling must be one of none, read, write, external, sensitive.")
    if ceiling == Risk.SENSITIVE and not ctx.mfa_verified:
        return MoResult(ResultState.POLICY_DENIED, "A sensitive risk ceiling needs an MFA-verified session.")
    if db.query(AgentDefinition).filter(AgentDefinition.tenant_id == ctx.tenant_id, AgentDefinition.name == name).first():
        return MoResult(ResultState.BLOCKED, f"Agent '{name}' already exists.")
    row = AgentDefinition(tenant_id=ctx.tenant_id, created_by=ctx.actor_id, name=name, description=description[:2000],
                          allowed_tools_json=json.dumps(sorted(set(allowed_tools))), risk_ceiling=ceiling.value.upper())
    db.add(row)
    db.flush()
    chain.record(db, ctx, action="agent.registered", result_state=ResultState.SUCCESS, resource_type="agent",
                 resource_id=row.id, detail=name)
    return MoResult.ok(agent_dict(row))


def get_agent(db: Session, ctx: RequestContext, name: str) -> Optional[AgentDefinition]:
    return (db.query(AgentDefinition).filter(AgentDefinition.tenant_id == ctx.tenant_id, AgentDefinition.name == name).first())


def list_agents(db: Session, ctx: RequestContext) -> list[dict[str, Any]]:
    rows = db.query(AgentDefinition).filter(AgentDefinition.tenant_id == ctx.tenant_id).order_by(AgentDefinition.name).all()
    return [agent_dict(r) for r in rows]


def set_status(db: Session, ctx: RequestContext, name: str, status: str) -> MoResult:
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator can change an agent's status.")
    row = get_agent(db, ctx, name)
    if row is None:
        return MoResult(ResultState.FAILED, f"No such agent '{name}'.")
    row.status = status
    db.flush()
    chain.record(db, ctx, action=f"agent.{status.lower()}", result_state=ResultState.SUCCESS, resource_type="agent",
                 resource_id=row.id, detail=name)
    return MoResult.ok(agent_dict(row))
