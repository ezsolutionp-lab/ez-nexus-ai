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
from ..modelfabric.context import ContextPolicy, compress
from ..truth import verify_claims
from . import business_box, commercial, planning, router, text, timeseries, verticals

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


def _verify(p: dict[str, Any]) -> dict[str, Any]:
    today = None
    if p.get("today"):
        try:
            today = date.fromisoformat(p["today"])
        except ValueError:
            raise ValueError("today must be YYYY-MM-DD") from None
    if (p.get("answer") is None) == (p.get("claims") is None):
        raise ValueError("provide exactly one of 'answer' or 'claims'")
    return verify_claims(p.get("answer"), p["evidence"], claims=p.get("claims"), today=today,
                         max_age_days=p.get("max_age_days"), critical=bool(p.get("critical", False)),
                         min_groundedness=p.get("min_groundedness", 0.7))


def _compress(p: dict[str, Any]) -> dict[str, Any]:
    policy = p.get("policy")
    if policy is not None and (not isinstance(policy, dict) or set(policy) - set(ContextPolicy.__dataclass_fields__)):
        raise ValueError("policy has unknown fields")
    return compress(p["messages"], ContextPolicy(**policy) if policy else None)


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
    ("domain.verify_claims", "Check an answer's claims against evidence: support, contradiction, staleness, "
     "source quality, abstention and human-review flag (lexical, not an entailment model).",
     _verify,
     {"properties": {"answer": {"type": "string"}, "claims": _ARR, "evidence": _ARR, "today": {"type": "string"},
                     "max_age_days": {"type": "integer"}, "critical": {"type": "boolean"},
                     "min_groundedness": {"type": "number"}}, "required": ["evidence"]}),
    ("domain.route", "Route a request to a business domain with confidence and alternatives (rule-based).",
     lambda p: router.route_domain(p["text"], min_score=p.get("min_score", 2.0)),
     {"properties": {"text": {"type": "string"}, "min_score": {"type": "number"}}, "required": ["text"]}),
    ("domain.compress_context", "Shrink a long conversation to fit a token budget with an extractive summary.",
     _compress,
     {"properties": {"messages": _ARR, "policy": _OBJ}, "required": ["messages"]}),
    ("domain.cell_health", "Classify cell/RAN KPIs (PRB use, drops, availability, throughput) as healthy, degraded or critical.",
     lambda p: verticals.cell_health(p["cells"]),
     {"properties": {"cells": _ARR}, "required": ["cells"]}),
    ("domain.capacity_breach", "Forecast utilisation and report when it will cross a threshold.",
     lambda p: verticals.capacity_breach(p["utilization"], p.get("threshold", 0.8), p.get("horizon", 90), p.get("season", 0)),
     {"properties": {"utilization": _ARR, "threshold": {"type": "number"}, "horizon": {"type": "integer"}, "season": {"type": "integer"}},
      "required": ["utilization"]}),
    ("domain.root_cause", "Rank probable network root causes from a topology (child->parent) and the alarmed nodes.",
     lambda p: verticals.root_cause(p["topology"], p["alarms"], p.get("customers")),
     {"properties": {"topology": _OBJ, "alarms": _ARR, "customers": _OBJ}, "required": ["topology", "alarms"]}),
    ("domain.hotel_kpis", "Occupancy, ADR, RevPAR and TRevPAR from supplied figures.",
     lambda p: verticals.hotel_kpis(p["rooms_available"], p["rooms_sold"], p["room_revenue"], p.get("total_revenue")),
     {"properties": {"rooms_available": {"type": "number"}, "rooms_sold": {"type": "number"}, "room_revenue": {"type": "number"},
                     "total_revenue": {"type": "number"}}, "required": ["rooms_available", "rooms_sold", "room_revenue"]}),
    ("domain.overbooking", "Expected-cost-minimising overbooking level for a room block (binomial show-up model).",
     lambda p: verticals.overbooking(p["capacity"], p["no_show_rate"], p["room_rate"], p["walk_cost"], p.get("max_extra", 50)),
     {"properties": {"capacity": {"type": "integer"}, "no_show_rate": {"type": "number"}, "room_rate": {"type": "number"},
                     "walk_cost": {"type": "number"}, "max_extra": {"type": "integer"}},
      "required": ["capacity", "no_show_rate", "room_rate", "walk_cost"]}),
    ("domain.deal_risk", "Transparent risk score for a sales deal, with the factors behind it.",
     lambda p: verticals.deal_risk(p["deal"]), {"properties": {"deal": _OBJ}, "required": ["deal"]}),
    ("domain.renewal_risk", "Transparent churn/renewal risk score for an account, with the factors behind it.",
     lambda p: verticals.renewal_risk(p["account"]), {"properties": {"account": _OBJ}, "required": ["account"]}),
    ("domain.revenue_leakage", "Reconcile contract terms against invoices to find unbilled, under- and over-billed items.",
     lambda p: verticals.revenue_leakage(p["contracts"], p["invoices"], p.get("tolerance", 0.005)),
     {"properties": {"contracts": _ARR, "invoices": _ARR, "tolerance": {"type": "number"}}, "required": ["contracts", "invoices"]}),
    ("domain.cvss", "CVSS v3.1 base score and severity from a vector string.",
     lambda p: verticals.cvss_base(p["vector"]), {"properties": {"vector": {"type": "string"}}, "required": ["vector"]}),
    ("domain.triage_incidents", "Correlate security events per asset and rank incidents; containment is suggested, never executed.",
     lambda p: verticals.triage_incidents(p["events"], p.get("window_minutes", 30)),
     {"properties": {"events": _ARR, "window_minutes": {"type": "number"}}, "required": ["events"]}),
    ("domain.business_blueprint", "Vertical business-in-a-box blueprint (modules, roles, agents, KPIs, compliance prompts) and a Builder prompt.",
     lambda p: business_box.blueprint(p["vertical"], p.get("business_name", "")),
     {"properties": {"vertical": {"type": "string"}, "business_name": {"type": "string"}}, "required": ["vertical"]}),
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
