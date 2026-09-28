"""
MO NEXUS OMEGA — Tool governance.

A tool is only callable through the registry, and the registry checks scope,
risk tier, approval, rate limit and credentials before the handler runs. A tool
that needs a credential it does not have reports CREDENTIAL_REQUIRED; it does
not return a plausible-looking answer.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..context import RequestContext
from ..errors import MoResult, ResultState


class RiskLevel(str):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


@dataclass
class ToolSpec:
    """Declarative contract for one tool."""

    name: str
    description: str
    handler: Callable[[RequestContext, dict[str, Any]], MoResult]
    version: str = "1.0.0"
    kind: str = "builtin"                     # builtin | http | mcp | a2a
    risk_level: str = RiskLevel.LOW
    required_scopes: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30
    rate_limit_per_minute: int = 60
    requires_approval: bool = False
    credential_env_var: Optional[str] = None
    requires_mfa: bool = False

    def __post_init__(self) -> None:
        if self.risk_level not in _RISK_ORDER:
            raise ValueError(f"unknown risk level {self.risk_level!r}")
        # HIGH and CRITICAL tools are approval-gated by construction, not by convention.
        if _RISK_ORDER[self.risk_level] >= _RISK_ORDER[RiskLevel.HIGH]:
            self.requires_approval = True
        if self.risk_level == RiskLevel.CRITICAL:
            self.requires_mfa = True

    @property
    def credential_satisfied(self) -> bool:
        if not self.credential_env_var:
            return True
        return bool(os.getenv(self.credential_env_var, "").strip())

    def validate_input(self, payload: dict[str, Any]) -> Optional[str]:
        """Minimal structural validation against the declared schema."""
        props = self.input_schema.get("properties", {})
        for key in self.input_schema.get("required", []):
            if key not in payload:
                return f"missing required field '{key}'"
        for key, value in payload.items():
            declared = props.get(key)
            if not declared:
                if self.input_schema.get("additionalProperties") is False:
                    return f"unexpected field '{key}'"
                continue
            expected = declared.get("type")
            py_type = {
                "string": str, "integer": int, "number": (int, float),
                "boolean": bool, "array": list, "object": dict,
            }.get(expected)
            if py_type and not isinstance(value, py_type):
                return f"field '{key}' must be {expected}"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "description": self.description,
            "kind": self.kind, "risk_level": self.risk_level,
            "required_scopes": list(self.required_scopes),
            "input_schema": self.input_schema, "output_schema": self.output_schema,
            "timeout_seconds": self.timeout_seconds,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "requires_approval": self.requires_approval,
            "requires_mfa": self.requires_mfa,
            "credential_env_var": self.credential_env_var,
            "credential_satisfied": self.credential_satisfied,
        }


class _RateLimiter:
    """Sliding-window limiter keyed by (tool, tenant, actor)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)

    def check(self, key: tuple[str, str, str], limit_per_minute: int) -> bool:
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= limit_per_minute:
            return False
        window.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


class ToolRegistry:
    """The only way to invoke a tool. Governance runs before every handler."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._limiter = _RateLimiter()

    def register(self, spec: ToolSpec, *, replace: bool = False) -> ToolSpec:
        if spec.name in self._tools and not replace:
            raise ValueError(f"tool '{spec.name}' is already registered")
        self._tools[spec.name] = spec
        return spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list(self, *, kind: Optional[str] = None) -> list[ToolSpec]:
        out = list(self._tools.values())
        if kind:
            out = [t for t in out if t.kind == kind]
        return sorted(out, key=lambda t: t.name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def invoke(
        self,
        ctx: RequestContext,
        name: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        approval_granted: bool = False,
    ) -> MoResult:
        """Run governance, then the handler, and record the outcome as a span and metrics."""
        from ..observability.metrics import metrics
        from ..observability.tracing import tracer

        started = time.perf_counter()
        with tracer.span(f"tool:{name}", ctx, tool=name) as sp:
            result = self._invoke(ctx, name, payload, approval_granted=approval_granted)
            sp.state = result.state.value
        metrics.inc("mo_tool_invocations_total", tool=name if self.get(name) else "unknown",
                    state=result.state.value)
        metrics.observe("mo_tool_duration_ms", (time.perf_counter() - started) * 1000,
                        tool=name if self.get(name) else "unknown")
        return result

    def _invoke(
        self,
        ctx: RequestContext,
        name: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        approval_granted: bool = False,
    ) -> MoResult:
        """Run governance, then the handler. Every rejection names its reason."""
        payload = payload or {}
        spec = self._tools.get(name)
        if spec is None:
            return MoResult(ResultState.FAILED, f"No tool named '{name}' is registered.")

        # 1. Authorisation
        for scope in spec.required_scopes:
            if not (ctx.is_admin or scope in ctx.scopes):
                return MoResult(
                    ResultState.POLICY_DENIED,
                    f"Tool '{name}' requires scope '{scope}'.",
                    meta={"required_scope": scope, "tool": name},
                )
        if spec.requires_mfa and not ctx.mfa_verified:
            return MoResult(
                ResultState.POLICY_DENIED,
                f"Tool '{name}' is {spec.risk_level} risk and requires a multi-factor verified session.",
                meta={"tool": name, "risk_level": spec.risk_level},
            )

        # 2. Approval gate
        if spec.requires_approval and not approval_granted:
            return MoResult(
                ResultState.APPROVAL_REQUIRED,
                f"Tool '{name}' is {spec.risk_level} risk and requires approval before it runs.",
                meta={"tool": name, "risk_level": spec.risk_level},
            )

        # 3. Credentials — checked before the handler so nothing half-runs
        if not spec.credential_satisfied:
            return MoResult.credential_required(spec.name, spec.credential_env_var or "")

        # 4. Rate limit
        if not self._limiter.check((name, ctx.tenant_id, ctx.actor_id), spec.rate_limit_per_minute):
            return MoResult(
                ResultState.RATE_LIMITED,
                f"Tool '{name}' rate limit of {spec.rate_limit_per_minute}/min exceeded.",
                meta={"tool": name, "limit_per_minute": spec.rate_limit_per_minute},
            )

        # 5. Input validation
        problem = spec.validate_input(payload)
        if problem:
            return MoResult(ResultState.FAILED, f"Invalid input for '{name}': {problem}.")

        # 6. Execute — a handler exception is a failure, never a success
        started = time.perf_counter()
        try:
            result = spec.handler(ctx, payload)
        except TimeoutError as exc:
            return MoResult(ResultState.TIMEOUT, f"Tool '{name}' timed out: {exc}")
        except Exception as exc:
            return MoResult(
                ResultState.FAILED,
                f"Tool '{name}' raised {type(exc).__name__}: {exc}",
                meta={"tool": name},
            )
        if not isinstance(result, MoResult):
            return MoResult(
                ResultState.FAILED,
                f"Tool '{name}' returned {type(result).__name__}, not an MoResult.",
            )
        result.meta.setdefault("tool", name)
        result.meta.setdefault("duration_ms", int((time.perf_counter() - started) * 1000))
        return result

    def reset_rate_limits(self) -> None:
        self._limiter.reset()


_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        from .builtin import register_builtin_tools
        register_builtin_tools(_registry)
        from ..intelligence.tools import register_domain_tools
        register_domain_tools(_registry)
        from ..authority.desktop import register_desktop_tool
        register_desktop_tool(_registry)
    return _registry


def reset_tool_registry() -> None:
    global _registry
    _registry = None
