"""
MO NEXUS OMEGA — Lightweight tracing.

`span()` records a named unit of work with its parent, duration, result state and
attributes. Spans nest automatically through a context variable, share the
request's `trace_id`, and are held in a bounded per-tenant ring buffer so trace
storage cannot grow without limit. A span records failure faithfully: an
exception marks it FAILED and is re-raised, never swallowed.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from ..context import RequestContext
from .metrics import metrics

MAX_SPANS_PER_TENANT = 2000
_current: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("mo_span", default=None)


@dataclass
class Span:
    span_id: str
    trace_id: str
    parent_id: Optional[str]
    name: str
    tenant_id: str
    started_at: float
    duration_ms: float = 0.0
    state: str = "SUCCESS"
    error: Optional[str] = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"span_id": self.span_id, "trace_id": self.trace_id, "parent_id": self.parent_id,
                "name": self.name, "duration_ms": round(self.duration_ms, 3), "state": self.state,
                "error": self.error, "attributes": self.attributes}


class Tracer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: dict[str, deque[Span]] = defaultdict(lambda: deque(maxlen=MAX_SPANS_PER_TENANT))

    @contextmanager
    def span(self, name: str, ctx: RequestContext, **attributes: Any) -> Iterator[Span]:
        sp = Span(uuid.uuid4().hex[:16], ctx.trace_id, _current.get(), name, ctx.tenant_id,
                  time.perf_counter(), attributes=dict(attributes))
        token = _current.set(sp.span_id)
        try:
            yield sp
        except Exception as exc:
            sp.state, sp.error = "FAILED", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _current.reset(token)
            sp.duration_ms = (time.perf_counter() - sp.started_at) * 1000
            with self._lock:
                self._spans[ctx.tenant_id].append(sp)

    def traces(self, tenant_id: str, *, trace_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        with self._lock:
            spans = list(self._spans.get(tenant_id, ()))
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return [s.to_dict() for s in spans[-limit:]]

    def tree(self, tenant_id: str, trace_id: str) -> list[dict]:
        """Spans of one trace nested by parent, oldest root first."""
        nodes = {s["span_id"]: {**s, "children": []} for s in self.traces(tenant_id, trace_id=trace_id, limit=MAX_SPANS_PER_TENANT)}
        roots = []
        for n in nodes.values():
            parent = nodes.get(n["parent_id"])
            (parent["children"] if parent else roots).append(n)
        return roots

    def reset(self) -> None:
        with self._lock:
            self._spans.clear()


tracer = Tracer()


def record_model_call(result, elapsed_ms: float) -> None:
    metrics.inc("mo_model_requests_total", state=result.state.value)
    metrics.observe("mo_model_duration_ms", elapsed_ms)
    if result.state.is_success:
        provider = str(result.meta.get("provider", "unknown"))
        metrics.inc("mo_model_cost_usd_total", float(result.meta.get("cost_usd") or 0.0), provider=provider)
