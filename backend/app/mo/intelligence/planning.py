"""Critical-path analysis and Monte Carlo schedule risk (PMO). Deterministic given a seed."""

from __future__ import annotations

import math
import random
import statistics
from typing import Any, Optional

MAX_TASKS = 500
MAX_SIMULATIONS = 100_000


def _tasks(tasks: Any, *, need: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a non-empty list")
    if len(tasks) > MAX_TASKS:
        raise ValueError(f"at most {MAX_TASKS} tasks are supported")
    out: dict[str, dict[str, Any]] = {}
    for t in tasks:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"]:
            raise ValueError("every task needs a string 'id'")
        if t["id"] in out:
            raise ValueError(f"duplicate task id '{t['id']}'")
        for f in need:
            v = t.get(f)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise ValueError(f"task '{t['id']}' needs a non-negative number '{f}'")
        deps = t.get("deps", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise ValueError(f"task '{t['id']}' deps must be a list of ids")
        out[t["id"]] = {**t, "deps": list(dict.fromkeys(deps))}
    for t in out.values():
        for d in t["deps"]:
            if d not in out:
                raise ValueError(f"task '{t['id']}' depends on unknown task '{d}'")
            if d == t["id"]:
                raise ValueError(f"task '{t['id']}' depends on itself")
    return out


def _order(tasks: dict[str, dict[str, Any]]) -> list[str]:
    indeg = {k: len(v["deps"]) for k, v in tasks.items()}
    children: dict[str, list[str]] = {k: [] for k in tasks}
    for k, v in tasks.items():
        for d in v["deps"]:
            children[d].append(k)
    ready = sorted(k for k, n in indeg.items() if n == 0)
    order = []
    while ready:
        k = ready.pop(0)
        order.append(k)
        for c in sorted(children[k]):
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    if len(order) != len(tasks):
        raise ValueError("the task graph contains a cycle: " + ", ".join(sorted(set(tasks) - set(order))))
    return order


def critical_path(tasks: Any) -> dict[str, Any]:
    t = _tasks(tasks, need=("duration",))
    order = _order(t)
    es, ef = {}, {}
    for k in order:
        es[k] = max((ef[d] for d in t[k]["deps"]), default=0.0)
        ef[k] = es[k] + t[k]["duration"]
    total = max(ef.values())
    children: dict[str, list[str]] = {k: [] for k in t}
    for k, v in t.items():
        for d in v["deps"]:
            children[d].append(k)
    lf, ls = {}, {}
    for k in reversed(order):
        lf[k] = min((ls[c] for c in children[k]), default=total)
        ls[k] = lf[k] - t[k]["duration"]
    eps = 1e-9
    rows = [{"id": k, "duration": t[k]["duration"], "es": es[k], "ef": ef[k], "ls": ls[k], "lf": lf[k],
             "slack": round(ls[k] - es[k], 9), "critical": abs(ls[k] - es[k]) < eps} for k in order]
    crit = {r["id"] for r in rows if r["critical"]}
    path, cur = [], next((k for k in order if k in crit and not [d for d in t[k]["deps"] if d in crit]), None)
    while cur:
        path.append(cur)
        cur = next((c for c in sorted(children[cur]) if c in crit and abs(es[c] - ef[cur]) < eps), None)
    return {"project_duration": total, "critical_path": path, "tasks": rows}


def monte_carlo(tasks: Any, simulations: int = 10_000, seed: int = 42, deadline: Optional[float] = None) -> dict[str, Any]:
    t = _tasks(tasks, need=("optimistic", "likely", "pessimistic"))
    if isinstance(simulations, bool) or not isinstance(simulations, int) or not 100 <= simulations <= MAX_SIMULATIONS:
        raise ValueError(f"simulations must be an integer between 100 and {MAX_SIMULATIONS}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    for k, v in t.items():
        if not v["optimistic"] <= v["likely"] <= v["pessimistic"]:
            raise ValueError(f"task '{k}' needs optimistic <= likely <= pessimistic")
    order = _order(t)
    rng = random.Random(seed)
    totals = []
    critical_hits = {k: 0 for k in t}
    for _ in range(simulations):
        ef: dict[str, float] = {}
        via: dict[str, Optional[str]] = {}
        for k in order:
            v = t[k]
            dur = rng.triangular(v["optimistic"], v["pessimistic"], v["likely"]) if v["pessimistic"] > v["optimistic"] else v["likely"]
            best_d = max(v["deps"], key=lambda d: ef[d], default=None)
            ef[k] = (ef[best_d] if best_d else 0.0) + dur
            via[k] = best_d
        end = max(ef, key=lambda k: ef[k])
        totals.append(ef[end])
        cur: Optional[str] = end
        while cur:
            critical_hits[cur] += 1
            cur = via[cur]
    totals.sort()

    def pct(p: float) -> float:
        return round(totals[min(len(totals) - 1, int(p / 100 * len(totals)))], 4)

    out: dict[str, Any] = {
        "simulations": simulations, "seed": seed, "distribution": "triangular per task",
        "mean": round(statistics.fmean(totals), 4), "stdev": round(statistics.pstdev(totals), 4),
        "percentiles": {f"p{p}": pct(p) for p in (10, 50, 80, 90, 95)},
        "criticality_index": {k: round(n / simulations, 4) for k, n in sorted(critical_hits.items())}}
    if deadline is not None:
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise ValueError("deadline must be a number")
        out["probability_of_meeting_deadline"] = round(sum(1 for x in totals if x <= deadline) / simulations, 4)
    return out
