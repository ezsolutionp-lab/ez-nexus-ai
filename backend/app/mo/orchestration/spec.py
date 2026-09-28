"""
MO NEXUS OMEGA — Orchestration plan validation.

A plan is a DAG of governed steps. Validation is strict and happens before anything
is stored or run: an unknown tool, a cycle, a dangling dependency or a template that
references a step it does not depend on is rejected up front with a message that names
the offending step.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..tools.spec import get_tool_registry

KINDS = ("tool", "domain", "gate")
MAX_STEPS = 100
MAX_RETRIES = 3
KEY_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,63}$")
TEMPLATE_RE = re.compile(r"\$\{([a-z][a-z0-9_\-]*)((?:\.[A-Za-z0-9_\-]+)*)\}")
ON_FAILURE = ("continue", "abort")


def _templates(value: Any) -> list[str]:
    if isinstance(value, str):
        return [m.group(1) for m in TEMPLATE_RE.finditer(value)]
    if isinstance(value, dict):
        return [k for v in value.values() for k in _templates(v)]
    if isinstance(value, list):
        return [k for v in value for k in _templates(v)]
    return []


def validate_plan(plan: Any) -> Optional[str]:
    """Return a human-readable problem, or None when the plan is runnable."""
    if not isinstance(plan, dict):
        return "The plan must be an object."
    name = plan.get("name")
    if not isinstance(name, str) or not name.strip():
        return "The plan needs a non-empty 'name'."
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return "The plan needs at least one step."
    if len(steps) > MAX_STEPS:
        return f"A plan may have at most {MAX_STEPS} steps."
    budget = plan.get("budget_usd", 1.0)
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget < 0:
        return "'budget_usd' must be a non-negative number."

    registry = get_tool_registry()
    keys: dict[str, dict] = {}
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            return f"Step {i} must be an object."
        key = s.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            return f"Step {i} needs a 'key' of lowercase letters, digits, '_' or '-'."
        if key in keys:
            return f"Duplicate step key '{key}'."
        keys[key] = s
    for key, s in keys.items():
        kind = s.get("kind", "tool")
        if kind not in KINDS:
            return f"Step '{key}': kind must be one of {', '.join(KINDS)} (got '{kind}')."
        deps = s.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            return f"Step '{key}': depends_on must be a list of step keys."
        for d in deps:
            if d == key:
                return f"Step '{key}' depends on itself."
            if d not in keys:
                return f"Step '{key}' depends on unknown step '{d}'."
        inp = s.get("input", {})
        if not isinstance(inp, dict):
            return f"Step '{key}': input must be an object."
        for ref in _templates(inp):
            if ref not in deps:
                return f"Step '{key}' references '${{{ref}}}' but does not list '{ref}' in depends_on."
        retries = s.get("retries", 0)
        if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= MAX_RETRIES:
            return f"Step '{key}': retries must be an integer from 0 to {MAX_RETRIES}."
        timeout = s.get("timeout_s")
        if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                                    or not 0 < timeout <= 3600):
            return f"Step '{key}': timeout_s must be between 0 and 3600 seconds."
        if s.get("on_failure", "continue") not in ON_FAILURE:
            return f"Step '{key}': on_failure must be one of {', '.join(ON_FAILURE)}."
        if kind == "gate":
            if s.get("risk", "MEDIUM") not in ("MEDIUM", "HIGH", "CRITICAL"):
                return f"Step '{key}': a gate's risk must be MEDIUM, HIGH or CRITICAL."
            continue
        target = s.get("target")
        spec = registry.get(target) if isinstance(target, str) else None
        if spec is None:
            return f"Step '{key}': no tool named '{target}' is registered."
        if kind == "domain" and not str(target).startswith("domain."):
            return f"Step '{key}': a domain step must target a 'domain.*' tool."
        if not _templates(inp):
            problem = spec.validate_input(inp)
            if problem:
                return f"Step '{key}': invalid input for '{target}': {problem}."

    # Cycle detection (Kahn).
    indeg = {k: len(s.get("depends_on", [])) for k, s in keys.items()}
    ready = [k for k, n in indeg.items() if n == 0]
    seen = 0
    while ready:
        k = ready.pop()
        seen += 1
        for k2, s2 in keys.items():
            if k in s2.get("depends_on", []):
                indeg[k2] -= 1
                if indeg[k2] == 0:
                    ready.append(k2)
    if seen != len(keys):
        stuck = sorted(k for k, n in indeg.items() if n > 0)
        return f"The plan contains a dependency cycle involving: {', '.join(stuck)}."
    return None


def resolve_templates(value: Any, outputs: dict[str, Any]) -> Any:
    """Substitute ${step.path} references from prior step outputs. Raises KeyError if absent."""
    if isinstance(value, str):
        whole = TEMPLATE_RE.fullmatch(value)
        if whole:
            return _lookup(outputs, whole.group(1), whole.group(2))
        return TEMPLATE_RE.sub(lambda m: str(_lookup(outputs, m.group(1), m.group(2))), value)
    if isinstance(value, dict):
        return {k: resolve_templates(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_templates(v, outputs) for v in value]
    return value


def _lookup(outputs: dict[str, Any], key: str, path: str) -> Any:
    cur: Any = outputs[key]
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise KeyError(f"'{key}{path}' is not present in the output of step '{key}'")
    return cur
