"""
MO NEXUS OMEGA — Metrics registry with Prometheus text exposition.

Counters, gauges and fixed-bucket histograms, label-aware and thread-safe. This
is process-local: in a multi-worker deployment each worker exposes its own
series and the scraper aggregates them, which is the standard Prometheus model.
"""

from __future__ import annotations

import threading
from typing import Iterable

DEFAULT_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)   # milliseconds


def _key(labels: dict[str, str]) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _fmt(name: str, labels: Iterable[tuple[str, str]], value: float) -> str:
    lab = ",".join(f'{k}="{v.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
                   for k, v in labels)
    return f"{name}{{{lab}}} {value:g}" if lab else f"{name} {value:g}"


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple, float]] = {}
        self._gauges: dict[str, dict[tuple, float]] = {}
        self._hist: dict[str, dict[tuple, dict]] = {}
        self._help: dict[str, str] = {}

    def describe(self, name: str, text: str) -> None:
        self._help[name] = text

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            series = self._counters.setdefault(name, {})
            k = _key(labels)
            series[k] = series.get(k, 0.0) + value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges.setdefault(name, {})[_key(labels)] = value

    def observe(self, name: str, value_ms: float, buckets: tuple = DEFAULT_BUCKETS, **labels: str) -> None:
        with self._lock:
            series = self._hist.setdefault(name, {})
            h = series.setdefault(_key(labels), {"buckets": buckets, "counts": [0] * len(buckets),
                                                 "sum": 0.0, "count": 0})
            for i, edge in enumerate(h["buckets"]):
                if value_ms <= edge:
                    h["counts"][i] += 1
            h["sum"] += value_ms
            h["count"] += 1

    def counter_value(self, name: str, **labels: str) -> float:
        return self._counters.get(name, {}).get(_key(labels), 0.0)

    def histogram_stats(self, name: str, **labels: str) -> dict:
        h = self._hist.get(name, {}).get(_key(labels))
        if not h:
            return {"count": 0, "sum": 0.0, "avg": 0.0}
        return {"count": h["count"], "sum": h["sum"], "avg": h["sum"] / h["count"]}

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": {n: [{"labels": dict(k), "value": v} for k, v in s.items()]
                             for n, s in self._counters.items()},
                "gauges": {n: [{"labels": dict(k), "value": v} for k, v in s.items()]
                           for n, s in self._gauges.items()},
                "histograms": {n: [{"labels": dict(k), "count": h["count"], "sum": h["sum"]}
                                   for k, h in s.items()] for n, s in self._hist.items()},
            }

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, series in sorted(self._counters.items()):
                lines += [f"# HELP {name} {self._help.get(name, name)}", f"# TYPE {name} counter"]
                lines += [_fmt(name, k, v) for k, v in sorted(series.items())]
            for name, series in sorted(self._gauges.items()):
                lines += [f"# HELP {name} {self._help.get(name, name)}", f"# TYPE {name} gauge"]
                lines += [_fmt(name, k, v) for k, v in sorted(series.items())]
            for name, series in sorted(self._hist.items()):
                lines += [f"# HELP {name} {self._help.get(name, name)}", f"# TYPE {name} histogram"]
                for k, h in sorted(series.items()):
                    for edge, count in zip(h["buckets"], h["counts"]):
                        lines.append(_fmt(f"{name}_bucket", k + (("le", str(edge)),), count))
                    lines.append(_fmt(f"{name}_bucket", k + (("le", "+Inf"),), h["count"]))
                    lines.append(_fmt(f"{name}_sum", k, h["sum"]))
                    lines.append(_fmt(f"{name}_count", k, h["count"]))
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._hist.clear()


metrics = Registry()
metrics.describe("mo_tool_invocations_total", "Governed tool invocations by tool and result state")
metrics.describe("mo_tool_duration_ms", "Governed tool invocation latency in milliseconds")
metrics.describe("mo_model_requests_total", "Model router requests by result state")
metrics.describe("mo_model_cost_usd_total", "Model spend in US dollars by provider")
metrics.describe("mo_model_duration_ms", "Model router latency in milliseconds")
metrics.describe("mo_run_steps_total", "Orchestrated run steps by result state")
metrics.describe("mo_guard_actions_total", "Guard interventions by direction and outcome")
