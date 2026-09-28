"""
MO NEXUS OMEGA — Desktop action contract.

Defines what a desktop action must state before MO will consider it, and registers the
`desktop.act` tool (HIGH risk, so it is approval-gated by construction and only runs with a
one-time grant). There is NO OS driver in this repository: without a registered adapter the
tool answers PROVIDER_UNAVAILABLE. `dry_run` describes the action without doing anything.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..context import RequestContext
from ..errors import MoResult, ResultState
from ..tools.spec import RiskLevel, ToolRegistry, ToolSpec

REQUIRED_FIELDS = ("application", "operation", "target", "preview", "risk", "expected_effect", "rollback")
RISKS = ("write", "external", "sensitive")

_adapters: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register_adapter(application: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    _adapters[application] = fn


def clear_adapters() -> None:
    _adapters.clear()


def validate_action(action: Any) -> list[str]:
    if not isinstance(action, dict):
        return ["action must be an object"]
    problems = [f"'{f}' is required" for f in REQUIRED_FIELDS if not isinstance(action.get(f), str) or not action[f].strip()]
    if isinstance(action.get("risk"), str) and action["risk"] not in RISKS:
        problems.append(f"risk must be one of {', '.join(RISKS)}")
    if isinstance(action.get("rollback"), str) and action["rollback"].strip().lower() in ("none", "n/a", "no"):
        if action.get("risk") in ("write", "sensitive"):
            problems.append("a write or sensitive action must state how to roll it back")
    return problems


def _handler(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    action = payload.get("action")
    problems = validate_action(action)
    if problems:
        return MoResult(ResultState.FAILED, "Invalid desktop action: " + "; ".join(problems))
    if payload.get("dry_run"):
        return MoResult.ok({"dry_run": True, "would_do": {k: action[k] for k in REQUIRED_FIELDS},
                            "note": "Nothing was executed."})
    adapter: Optional[Callable] = _adapters.get(action["application"])
    if adapter is None:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE,
                        f"No desktop adapter is installed for '{action['application']}'. "
                        "MO has no OS driver; one must be added and security-reviewed.")
    return MoResult.ok(adapter(action))


def register_desktop_tool(registry: ToolRegistry) -> None:
    if registry.get("desktop.act"):
        return
    registry.register(ToolSpec(
        name="desktop.act", description="Perform an approved desktop action through an installed OS adapter.",
        handler=_handler, risk_level=RiskLevel.HIGH, required_scopes=("desktop:act",), rate_limit_per_minute=30,
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": {"action": {"type": "object"}, "dry_run": {"type": "boolean"}},
                      "required": ["action"]}))
