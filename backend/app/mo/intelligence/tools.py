"""
MO NEXUS OMEGA — Domain intelligence tools.

The engines in this package are exposed only as governed tools, so scope, rate limits,
audit spans and metrics apply to them like any other capability. All are LOW risk:
they compute over the payload and touch no external system.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from ..context import RequestContext
from ..errors import MoResult, ResultState
from ..tools.spec import RiskLevel, ToolRegistry, ToolSpec
from . import commercial, planning, text, timeseries

SCOPE = "domain:run"

_ARR = {"type": "array"}
_OBJ = {"type": "object"}


def _wrap(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[RequestContext, dict[str, Any]], MoResult]:
    def handler(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
        try:
            return MoResult.ok(fn(payload))
        except ValueError as exc:
            return MoResult(ResultState.FAILED, f"Invalid input: {exc}")
    return handler


def _briefing(p: dict[str, Any]) -> dict[str, Any]:
    kwargs = {k: p[k] for k in ("quiet_start", "quiet_end", "max_items") if k in p}
    return text.build_briefing(p["items"], now=p["now"], **kwargs)


def _action_items(p: dict[str, Any]) -> dict[str, Any]:
    today = None
    if p.get("today"):
        try:
            today = date.fromisoformat(p["today"])
        except ValueError:
            raise ValueError("today must be YYYY-MM-DD") from None
    return text.extract_action_items(p["text"], today=today)


_TOOLS: list[tuple[str, str, Callable, dict]] = [
    ("domain.forecast", "Forecast a numeric series with a 95% interval (classical Holt, optional seasonality).",
     lambda p: timeseries.forecast(p["series"], p.get("horizon", 6), p.get("season", 0)),
     {"properties": {"series": _ARR, "horizon": {"type": "integer"}, "season": {"type": "integer"}},
      "required": ["series"]}),
    ("domain.anomaly", "Flag outliers in a numeric series (MAD, z-score or IQR).",
     lambda p: timeseries.anomalies(p["series"], p.get("method", "mad"), p.get("threshold")),
     {"properties": {"series": _ARR, "method": {"type": "string"}, "threshold": {"type": "number"}},
      "required": ["series"]}),
    ("domain.montecarlo", "Monte Carlo schedule-risk simulation over triangular task estimates (seeded).",
     lambda p: planning.monte_carlo(p["tasks"], p.get("simulations", 10000), p.get("seed", 42), p.get("deadline")),
     {"properties": {"tasks": _ARR, "simulations": {"type": "integer"}, "seed": {"type": "integer"},
                     "deadline": {"type": "number"}}, "required": ["tasks"]}),
    ("domain.critical_path", "Critical path and slack for a task dependency graph.",
     lambda p: planning.critical_path(p["tasks"]),
     {"properties": {"tasks": _ARR}, "required": ["tasks"]}),
    ("domain.pricing", "Price recommendation from unit cost, target margin, competitors and elasticity.",
     lambda p: commercial.price_recommendation(
         p["unit_cost"], target_margin=p.get("target_margin", 0.3),
         competitor_prices=p.get("competitor_prices"), price_elasticity=p.get("price_elasticity")),
     {"properties": {"unit_cost": {"type": "number"}, "target_margin": {"type": "number"},
                     "competitor_prices": _ARR, "price_elasticity": {"type": "number"}},
      "required": ["unit_cost"]}),
    ("domain.lead_score", "Transparent rule-based lead score with per-factor attribution.",
     lambda p: commercial.score_lead(p["lead"]),
     {"properties": {"lead": _OBJ}, "required": ["lead"]}),
    ("domain.pipeline_forecast", "Stage-weighted sales pipeline forecast (commit / best case).",
     lambda p: commercial.pipeline_forecast(p["deals"], p.get("stage_probability")),
     {"properties": {"deals": _ARR, "stage_probability": _OBJ}, "required": ["deals"]}),
    ("domain.finance", "Runway, margins, liquidity, leverage, NPV and IRR from supplied figures.",
     lambda p: commercial.finance_metrics(p["data"]),
     {"properties": {"data": _OBJ}, "required": ["data"]}),
    ("domain.recommend", "Item recommendations from co-occurrence in past baskets, with the reason.",
     lambda p: commercial.recommend(p["baskets"], p["seed_items"], p.get("top_k", 5)),
     {"properties": {"baskets": _ARR, "seed_items": _ARR, "top_k": {"type": "integer"}},
      "required": ["baskets", "seed_items"]}),
    ("domain.keywords", "Keyword and key-phrase extraction by frequency.",
     lambda p: text.extract_keywords(p["text"], p.get("top_k", 10)),
     {"properties": {"text": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["text"]}),
    ("domain.action_items", "Extract explicit action items, owners and due dates from meeting notes.",
     _action_items,
     {"properties": {"text": {"type": "string"}, "today": {"type": "string"}}, "required": ["text"]}),
    ("domain.briefing", "Order pending items into a briefing, holding non-urgent ones during quiet hours.",
     _briefing,
     {"properties": {"items": _ARR, "now": {"type": "string"}, "quiet_start": {"type": "string"},
                     "quiet_end": {"type": "string"}, "max_items": {"type": "integer"}},
      "required": ["items", "now"]}),
]


def register_domain_tools(registry: ToolRegistry) -> None:
    for name, description, fn, schema in _TOOLS:
        if registry.get(name):
            continue
        registry.register(ToolSpec(
            name=name, description=description, handler=_wrap(fn), risk_level=RiskLevel.LOW,
            required_scopes=(SCOPE,), rate_limit_per_minute=120, timeout_seconds=30,
            input_schema={"type": "object", "additionalProperties": False, **schema},
        ))
