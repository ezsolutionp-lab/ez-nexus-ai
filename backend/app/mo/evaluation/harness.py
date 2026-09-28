"""
MO NEXUS OMEGA — Evaluation harness.

A suite is a list of cases; each case runs a governed tool (or a named guard probe) and
is graded by deterministic checks only: expected result state, exact / approximate values
at a data path, substrings, and a latency ceiling. There is no model-graded check here —
an LLM judge would need a provider credential and is not part of this harness.

A suite passes only when its score meets its threshold. Runs are persisted and audited,
so "the evals were green" is a checkable record, not a claim.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import EvalRun
from ..errors import MoResult, ResultState
from ..guards import pipeline
from ..tools.spec import ToolRegistry, get_tool_registry

MAX_CASES = 500
PROBE_PREFIX = "probe:"

PROBES: dict[str, Callable[[dict[str, Any]], MoResult]] = {
    "guard.input": lambda p: pipeline.guard_input(p["text"]).to_result(),
    "guard.output": lambda p: pipeline.guard_output(p["text"]).to_result(),
}


@dataclass
class EvalCase:
    id: str
    tool: str                                   # registered tool name, or "probe:<name>"
    input: dict[str, Any] = field(default_factory=dict)
    expect_state: str = "SUCCESS"
    equals: dict[str, Any] = field(default_factory=dict)       # dotted data path -> exact value
    approx: dict[str, tuple[float, float]] = field(default_factory=dict)   # path -> (value, abs tolerance)
    contains: dict[str, str] = field(default_factory=dict)     # path -> substring
    present: list[str] = field(default_factory=list)           # paths that must exist
    absent: list[str] = field(default_factory=list)            # paths that must not exist
    max_ms: Optional[float] = None


@dataclass
class EvalSuite:
    name: str
    cases: list[EvalCase]
    threshold: float = 1.0
    description: str = ""


_MISSING = object()


def _dig(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit() and -len(cur) <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def grade(case: EvalCase, result: MoResult, elapsed_ms: float) -> list[str]:
    """Return the list of failed checks (empty means the case passed)."""
    fails: list[str] = []
    if result.state.value != case.expect_state:
        fails.append(f"state {result.state.value} != expected {case.expect_state}")
    haystack = {"data": result.data, "meta": result.meta}
    root = result.data if isinstance(result.data, (dict, list)) else haystack["data"]
    for path, want in case.equals.items():
        got = _dig(root, path)
        if got is _MISSING:
            fails.append(f"{path} missing")
        elif got != want:
            fails.append(f"{path} = {got!r}, expected {want!r}")
    for path, (want, tol) in case.approx.items():
        got = _dig(root, path)
        if got is _MISSING or isinstance(got, bool) or not isinstance(got, (int, float)):
            fails.append(f"{path} missing or not numeric")
        elif not math.isclose(got, want, abs_tol=tol):
            fails.append(f"{path} = {got}, expected {want} ± {tol}")
    for path, needle in case.contains.items():
        got = _dig(root, path)
        if got is _MISSING or needle not in str(got):
            fails.append(f"{path} does not contain {needle!r}")
    for path in case.present:
        if _dig(root, path) is _MISSING:
            fails.append(f"{path} should be present")
    for path in case.absent:
        if _dig(root, path) is not _MISSING:
            fails.append(f"{path} should be absent")
    if case.max_ms is not None and elapsed_ms > case.max_ms:
        fails.append(f"took {elapsed_ms:.0f}ms, limit {case.max_ms:.0f}ms")
    return fails


def _run_case(case: EvalCase, ctx: RequestContext, registry: ToolRegistry) -> dict[str, Any]:
    started = time.perf_counter()
    if case.tool.startswith(PROBE_PREFIX):
        probe = PROBES.get(case.tool[len(PROBE_PREFIX):])
        if probe is None:
            result = MoResult(ResultState.FAILED, f"No probe named '{case.tool}'.")
        else:
            try:
                result = probe(case.input)
            except Exception as exc:
                result = MoResult(ResultState.FAILED, f"Probe raised {type(exc).__name__}: {exc}")
    else:
        result = registry.invoke(ctx, case.tool, case.input)
    elapsed = (time.perf_counter() - started) * 1000
    fails = grade(case, result, elapsed)
    return {"id": case.id, "tool": case.tool, "passed": not fails, "failures": fails,
            "state": result.state.value, "duration_ms": round(elapsed, 2)}


def run_suite(db: Session, ctx: RequestContext, suite: EvalSuite, *, target: str = "tool-registry",
              registry: Optional[ToolRegistry] = None) -> MoResult:
    if not suite.cases:
        return MoResult(ResultState.FAILED, f"Suite '{suite.name}' has no cases.")
    if len(suite.cases) > MAX_CASES:
        return MoResult(ResultState.FAILED, f"A suite may have at most {MAX_CASES} cases.")
    ids = [c.id for c in suite.cases]
    if len(set(ids)) != len(ids):
        return MoResult(ResultState.FAILED, "Case ids must be unique.")
    if not 0.0 < suite.threshold <= 1.0:
        return MoResult(ResultState.FAILED, "Threshold must be in (0, 1].")

    registry = registry or get_tool_registry()
    results = [_run_case(c, ctx, registry) for c in suite.cases]
    passed_count = sum(1 for r in results if r["passed"])
    score = passed_count / len(results)
    passed = score >= suite.threshold

    row = EvalRun(tenant_id=ctx.tenant_id, created_by=ctx.actor_id, suite=suite.name, target=target,
                  total=len(results), passed_count=passed_count, score=round(score, 4),
                  threshold=suite.threshold, passed=passed, results_json=json.dumps(results))
    db.add(row)
    db.flush()
    chain.record(db, ctx, action="eval.run", result_state=ResultState.SUCCESS if passed else ResultState.FAILED,
                 resource_type="eval", resource_id=row.id,
                 detail=f"{suite.name}: {passed_count}/{len(results)} passed (threshold {suite.threshold:.0%})",
                 payload={"suite": suite.name, "score": round(score, 4), "passed": passed})
    report = {"run_id": row.id, "suite": suite.name, "total": len(results), "passed_count": passed_count,
              "score": round(score, 4), "threshold": suite.threshold, "passed": passed, "results": results}
    if passed:
        return MoResult.ok(report)
    failed_ids = [r["id"] for r in results if not r["passed"]]
    return MoResult(ResultState.FAILED,
                    f"Suite '{suite.name}' scored {score:.0%}, below the {suite.threshold:.0%} threshold. "
                    f"Failing cases: {', '.join(failed_ids)}.", data=report)


def list_runs(db: Session, ctx: RequestContext, suite: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    q = db.query(EvalRun).filter(EvalRun.tenant_id == ctx.tenant_id)
    if suite:
        q = q.filter(EvalRun.suite == suite)
    rows = q.order_by(EvalRun.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return [{"run_id": r.id, "suite": r.suite, "target": r.target, "total": r.total, "passed_count": r.passed_count,
             "score": r.score, "threshold": r.threshold, "passed": r.passed,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


def get_run(db: Session, ctx: RequestContext, run_id: str) -> Optional[dict[str, Any]]:
    r = db.get(EvalRun, run_id)
    if r is None or r.tenant_id != ctx.tenant_id:
        return None
    return {"run_id": r.id, "suite": r.suite, "target": r.target, "total": r.total,
            "passed_count": r.passed_count, "score": r.score, "threshold": r.threshold, "passed": r.passed,
            "results": json.loads(r.results_json)}
