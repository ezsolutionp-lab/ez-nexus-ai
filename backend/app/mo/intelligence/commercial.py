"""
MO NEXUS OMEGA — Commercial intelligence: pricing, lead scoring, pipeline, finance, recommendations.

Everything here is deterministic arithmetic over data the caller supplies. Nothing is
learned, nothing is fetched, and no number is invented: when an input needed for a
figure is missing, the figure is listed under ``not_computed`` with the reason.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Optional

MAX_ITEMS = 5000


def _num(value: Any, name: str, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return float(value)


def _pct(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


# ── pricing ─────────────────────────────────────────────────────────────────

def price_recommendation(unit_cost: float, *, target_margin: float = 0.3,
                         competitor_prices: Optional[list[float]] = None,
                         price_elasticity: Optional[float] = None) -> dict[str, Any]:
    """Cost-plus floor, optional competitor band, optional constant-elasticity optimum.

    floor = cost / (1 - margin). Competitor band is the interquartile range. With a
    constant price elasticity e < -1 the profit-maximising price is cost * e / (1 + e);
    for e >= -1 no finite optimum exists and none is claimed.
    """
    cost = _num(unit_cost, "unit_cost", minimum=0)
    margin = _num(target_margin, "target_margin", minimum=0, maximum=0.95)
    floor = cost / (1 - margin)
    out: dict[str, Any] = {"unit_cost": cost, "target_margin": margin, "floor_price": round(floor, 4),
                           "method": "cost-plus floor; competitor interquartile band; constant-elasticity optimum",
                           "not_computed": []}
    recommended = floor
    notes = ["Floor is the lowest price that still reaches the target margin."]

    comps = competitor_prices or []
    if len(comps) > MAX_ITEMS:
        raise ValueError(f"at most {MAX_ITEMS} competitor prices")
    if comps:
        vals = sorted(_num(p, "competitor_prices[]", minimum=0) for p in comps)
        q1, med, q3 = _pct(vals, 0.25), _pct(vals, 0.5), _pct(vals, 0.75)
        out["competitor_band"] = {"low": round(q1, 4), "median": round(med, 4), "high": round(q3, 4), "n": len(vals)}
        if q3 < floor:
            notes.append("The whole competitor band sits below your margin floor: you cannot match the market "
                         "at the target margin.")
            out["market_position"] = "priced_out"
        else:
            recommended = max(floor, med)
            out["market_position"] = "competitive"
            notes.append("Recommended price is the higher of the floor and the competitor median.")
    else:
        out["not_computed"].append({"figure": "competitor_band", "reason": "no competitor_prices supplied"})

    if price_elasticity is not None:
        e = _num(price_elasticity, "price_elasticity", maximum=0)
        if e < -1:
            opt = cost * e / (1 + e)
            out["elasticity_optimum"] = round(opt, 4)
            if opt > recommended:
                recommended = opt
                notes.append("Elasticity optimum exceeds the market-based price and was used.")
        else:
            out["not_computed"].append({"figure": "elasticity_optimum",
                                        "reason": "needs elasticity below -1; otherwise raising price always "
                                                  "raises profit in this model, so no finite optimum exists"})
    else:
        out["not_computed"].append({"figure": "elasticity_optimum", "reason": "no price_elasticity supplied"})

    out["recommended_price"] = round(recommended, 4)
    out["margin_at_recommended"] = round((recommended - cost) / recommended, 4) if recommended else 0.0
    out["notes"] = notes
    return out


# ── lead scoring ────────────────────────────────────────────────────────────

_SIZE_POINTS = [(1000, 15), (200, 12), (50, 8), (10, 4), (1, 2)]
_SENIORITY = {"c-level": 20, "vp": 17, "director": 14, "manager": 9, "individual": 4}
_SOURCE = {"referral": 15, "inbound": 12, "event": 9, "outbound": 5, "purchased_list": 2}
_INTENT = {"demo_request": 20, "pricing_page": 14, "content_download": 8, "newsletter": 3}


def score_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Transparent 0-100 rule score. Every point is attributed to a named factor."""
    if not isinstance(lead, dict):
        raise ValueError("lead must be an object")
    factors: list[dict[str, Any]] = []

    def add(name: str, points: float, maxp: float, why: str) -> None:
        factors.append({"factor": name, "points": points, "max": maxp, "why": why})

    size = lead.get("company_size")
    if size is None:
        add("company_size", 0, 15, "not supplied")
    else:
        n = _num(size, "company_size", minimum=0)
        pts = next((p for threshold, p in _SIZE_POINTS if n >= threshold), 0)
        add("company_size", pts, 15, f"{int(n)} employees")

    sen = str(lead.get("seniority", "")).lower()
    add("seniority", _SENIORITY.get(sen, 0), 20, sen or "not supplied")
    src = str(lead.get("source", "")).lower()
    add("source", _SOURCE.get(src, 0), 15, src or "not supplied")
    intent = str(lead.get("intent", "")).lower()
    add("intent", _INTENT.get(intent, 0), 20, intent or "not supplied")

    if lead.get("budget_confirmed") is True:
        add("budget", 15, 15, "budget confirmed")
    elif lead.get("budget_confirmed") is False:
        add("budget", 0, 15, "budget explicitly not confirmed")
    else:
        add("budget", 0, 15, "not supplied")

    days = lead.get("days_since_last_contact")
    if days is None:
        add("recency", 0, 15, "not supplied")
    else:
        d = _num(days, "days_since_last_contact", minimum=0)
        add("recency", 15 if d <= 7 else 10 if d <= 30 else 4 if d <= 90 else 0, 15, f"{int(d)} days ago")

    total = sum(f["points"] for f in factors)
    possible = sum(f["max"] for f in factors)
    score = round(100 * total / possible) if possible else 0
    grade = "A" if score >= 75 else "B" if score >= 55 else "C" if score >= 35 else "D"
    return {"score": score, "grade": grade, "factors": factors,
            "method": "transparent rule-based score (not a trained model)",
            "missing_inputs": [f["factor"] for f in factors if f["why"].startswith("not supplied")]}


# ── pipeline ────────────────────────────────────────────────────────────────

DEFAULT_STAGE_PROBABILITY = {"lead": 0.05, "qualified": 0.15, "proposal": 0.35, "negotiation": 0.6, "won": 1.0,
                             "lost": 0.0}


def pipeline_forecast(deals: list[dict[str, Any]], stage_probability: Optional[dict[str, float]] = None
                      ) -> dict[str, Any]:
    """Stage-probability weighted forecast. commit = deals at >=60%; best_case = all open deals."""
    if not isinstance(deals, list) or not deals:
        raise ValueError("deals must be a non-empty list")
    if len(deals) > MAX_ITEMS:
        raise ValueError(f"at most {MAX_ITEMS} deals")
    probs = dict(DEFAULT_STAGE_PROBABILITY)
    for k, v in (stage_probability or {}).items():
        probs[str(k).lower()] = _num(v, f"stage_probability[{k}]", minimum=0, maximum=1)

    weighted = commit = best = won = 0.0
    by_stage: dict[str, dict[str, float]] = {}
    unknown: list[str] = []
    for i, d in enumerate(deals):
        amount = _num(d.get("amount"), f"deals[{i}].amount", minimum=0)
        stage = str(d.get("stage", "")).lower()
        if stage not in probs:
            unknown.append(stage or f"(deal {i} has no stage)")
            continue
        p = probs[stage]
        if "probability" in d and d["probability"] is not None:
            p = _num(d["probability"], f"deals[{i}].probability", minimum=0, maximum=1)
        s = by_stage.setdefault(stage, {"count": 0, "amount": 0.0, "weighted": 0.0})
        s["count"] += 1
        s["amount"] += amount
        s["weighted"] += amount * p
        if stage == "won":
            won += amount
        elif stage != "lost":
            weighted += amount * p
            best += amount
            if p >= 0.6:
                commit += amount
    return {"won": round(won, 2), "weighted_open": round(weighted, 2), "commit": round(commit, 2),
            "best_case": round(best, 2), "expected_total": round(won + weighted, 2),
            "by_stage": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in by_stage.items()},
            "skipped_unknown_stage": sorted(set(unknown)),
            "method": "stage-probability weighting; probabilities are inputs, not learned"}


# ── finance ─────────────────────────────────────────────────────────────────

def npv(rate: float, cashflows: list[float]) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def irr(cashflows: list[float], *, lo: float = -0.99, hi: float = 10.0, tol: float = 1e-9) -> Optional[float]:
    """Bisection IRR. None when the cash flows do not change sign or no root brackets."""
    if not (any(c < 0 for c in cashflows) and any(c > 0 for c in cashflows)):
        return None
    f_lo, f_hi = npv(lo, cashflows), npv(hi, cashflows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid, cashflows)
        if abs(f_mid) < tol or (hi - lo) / 2 < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def finance_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Compute only the ratios the supplied figures support; report the rest as not_computed."""
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    out: dict[str, Any] = {}
    skipped: list[dict[str, str]] = []

    def get(name: str) -> Optional[float]:
        v = data.get(name)
        return None if v is None else _num(v, name)

    def need(figure: str, *names: str) -> Optional[list[float]]:
        vals = [get(n) for n in names]
        if any(v is None for v in vals):
            skipped.append({"figure": figure, "reason": "needs " + ", ".join(names)})
            return None
        return vals  # type: ignore[return-value]

    if (v := need("gross_margin", "revenue", "cost_of_goods_sold")) and v[0] != 0:
        out["gross_margin"] = round((v[0] - v[1]) / v[0], 4)
    if (v := need("net_margin", "revenue", "net_income")) and v[0] != 0:
        out["net_margin"] = round(v[1] / v[0], 4)
    if (v := need("current_ratio", "current_assets", "current_liabilities")) and v[1] != 0:
        out["current_ratio"] = round(v[0] / v[1], 4)
    if (v := need("quick_ratio", "current_assets", "inventory", "current_liabilities")) and v[2] != 0:
        out["quick_ratio"] = round((v[0] - v[1]) / v[2], 4)
    if (v := need("debt_to_equity", "total_debt", "total_equity")) and v[1] != 0:
        out["debt_to_equity"] = round(v[0] / v[1], 4)
    if v := need("monthly_burn", "monthly_cash_out", "monthly_cash_in"):
        burn = v[0] - v[1]
        out["monthly_burn"] = round(burn, 2)
        cash = get("cash")
        if burn <= 0:
            out["runway_months"] = None
            out["runway_note"] = "cash-flow positive: no burn, so no runway limit"
        elif cash is None:
            skipped.append({"figure": "runway_months", "reason": "needs cash"})
        else:
            out["runway_months"] = round(cash / burn, 2)
        nnr = get("net_new_revenue_monthly")
        if burn > 0 and nnr and nnr > 0:
            out["burn_multiple"] = round(burn / nnr, 3)
        elif burn > 0:
            skipped.append({"figure": "burn_multiple", "reason": "needs net_new_revenue_monthly > 0"})

    cfs = data.get("cashflows")
    if cfs is not None:
        if not isinstance(cfs, list) or len(cfs) < 2 or len(cfs) > 1000:
            raise ValueError("cashflows must be a list of 2-1000 numbers (period 0 first)")
        flows = [_num(c, "cashflows[]") for c in cfs]
        rate = get("discount_rate")
        if rate is None:
            skipped.append({"figure": "npv", "reason": "needs discount_rate"})
        else:
            if rate <= -1:
                raise ValueError("discount_rate must be > -1")
            out["npv"] = round(npv(rate, flows), 4)
        r = irr(flows)
        if r is None:
            skipped.append({"figure": "irr", "reason": "cash flows have no sign change or no root in (-99%, 1000%)"})
        else:
            out["irr"] = round(r, 6)
    else:
        skipped.append({"figure": "npv/irr", "reason": "needs cashflows"})

    out["not_computed"] = skipped
    return out


# ── recommender ─────────────────────────────────────────────────────────────

def recommend(baskets: list[list[str]], seed_items: list[str], top_k: int = 5) -> dict[str, Any]:
    """Item-item co-occurrence cosine. Recommendations name the seed item that caused them."""
    if not isinstance(baskets, list) or not baskets:
        raise ValueError("baskets must be a non-empty list of item lists")
    if len(baskets) > MAX_ITEMS:
        raise ValueError(f"at most {MAX_ITEMS} baskets")
    if not seed_items:
        raise ValueError("seed_items must not be empty")
    if not 1 <= top_k <= 50:
        raise ValueError("top_k must be between 1 and 50")
    counts: dict[str, int] = {}
    co: dict[tuple[str, str], int] = {}
    for b in baskets:
        if not isinstance(b, list) or len(b) > 200:
            raise ValueError("each basket must be a list of at most 200 items")
        items = sorted({str(x) for x in b})
        for x in items:
            counts[x] = counts.get(x, 0) + 1
        for a, c in combinations(items, 2):
            co[(a, c)] = co.get((a, c), 0) + 1

    seeds = [str(s) for s in seed_items]
    unknown = [s for s in seeds if s not in counts]
    scores: dict[str, tuple[float, str, int]] = {}
    for s in seeds:
        if s not in counts:
            continue
        for other in counts:
            if other == s or other in seeds:
                continue
            n = co.get((min(s, other), max(s, other)), 0)
            if not n:
                continue
            sim = n / math.sqrt(counts[s] * counts[other])
            prev = scores.get(other)
            if prev is None or sim > prev[0]:
                scores[other] = (sim, s, n)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1][0], kv[0]))[:top_k]
    return {"recommendations": [{"item": k, "score": round(v[0], 4), "because": v[1], "co_occurrences": v[2]}
                                for k, v in ranked],
            "unknown_seed_items": unknown, "baskets_used": len(baskets),
            "method": "item-item co-occurrence cosine (no personalisation model)"}
