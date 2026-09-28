"""
Vertical engines from the blueprint's domain agents: telecom, hospitality, revenue intelligence and cyber defence.

Deterministic, rule-based or closed-form. Each function scores the data it is given and says which factors drove the
result; none reads live systems, and none takes action (containment options are suggestions that still need approval).
"""

from __future__ import annotations

import math
from typing import Any, Optional

MAX_ITEMS = 5_000


def _num(v: Any, name: str, lo: float = -math.inf, hi: float = math.inf) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{name} must be a number" + (f" between {lo} and {hi}" if (lo, hi) != (-math.inf, math.inf) else ""))
    return float(v)


def _list(v: Any, name: str, limit: int = MAX_ITEMS) -> list:
    if not isinstance(v, list) or not v:
        raise ValueError(f"{name} must be a non-empty list")
    if len(v) > limit:
        raise ValueError(f"{name} is limited to {limit} items")
    return v


# ── telecom ─────────────────────────────────────────────────────────────────

CELL_THRESHOLDS = {"prb_utilization": (0.70, 0.90), "drop_rate": (0.01, 0.03), "availability": (0.995, 0.98),
                   "throughput_mbps": (10.0, 3.0)}      # (degraded, critical); availability and throughput are lower-is-worse


def cell_health(cells: Any) -> dict[str, Any]:
    out, counts = [], {"HEALTHY": 0, "DEGRADED": 0, "CRITICAL": 0}
    for c in _list(cells, "cells"):
        if not isinstance(c, dict) or not isinstance(c.get("id"), str):
            raise ValueError("every cell needs a string 'id'")
        level, reasons = 0, []
        for kpi, (warn, crit) in CELL_THRESHOLDS.items():
            if kpi not in c:
                continue
            v = _num(c[kpi], f"cell '{c['id']}' {kpi}", 0)
            lower_is_worse = kpi in ("availability", "throughput_mbps")
            bad = (v < crit) if lower_is_worse else (v > crit)
            warn_hit = (v < warn) if lower_is_worse else (v > warn)
            if bad:
                level = max(level, 2); reasons.append(f"{kpi} {v:g} is beyond the critical limit {crit:g}")
            elif warn_hit:
                level = max(level, 1); reasons.append(f"{kpi} {v:g} is beyond the warning limit {warn:g}")
        status = ("HEALTHY", "DEGRADED", "CRITICAL")[level]
        counts[status] += 1
        out.append({"id": c["id"], "status": status, "reasons": reasons or ["all reported KPIs are within limits"]})
    order = {"CRITICAL": 0, "DEGRADED": 1, "HEALTHY": 2}
    out.sort(key=lambda r: (order[r["status"]], r["id"]))
    return {"summary": counts, "cells": out, "total": len(out)}


def capacity_breach(utilization: Any, threshold: float = 0.8, horizon: int = 90, season: int = 0) -> dict[str, Any]:
    from .timeseries import forecast
    thr = _num(threshold, "threshold", 0.01, 1.0)
    f = forecast(utilization, horizon, season)
    for i, v in enumerate(f["forecast"], 1):
        if v >= thr:
            return {"breach_expected": True, "periods_until_breach": i, "threshold": thr, "forecast_at_breach": v, "forecast": f}
    return {"breach_expected": False, "periods_until_breach": None, "threshold": thr, "horizon": horizon, "forecast": f}


def root_cause(topology: Any, alarms: Any, customers: Optional[dict] = None) -> dict[str, Any]:
    """topology: {child: parent} (or null for a root). A node whose ancestor is also alarmed is a symptom, not a cause."""
    if not isinstance(topology, dict) or not topology or len(topology) > MAX_ITEMS:
        raise ValueError("topology must be an object mapping each node to its parent (null for a root)")
    if not isinstance(alarms, list) or not alarms or not all(isinstance(a, str) for a in alarms):
        raise ValueError("alarms must be a non-empty list of node ids")
    unknown = sorted(a for a in alarms if a not in topology)
    if unknown:
        raise ValueError(f"alarmed node(s) not in the topology: {', '.join(unknown)}")
    customers = customers or {}
    children: dict[str, list[str]] = {}
    for node, parent in topology.items():
        if parent is not None:
            if parent not in topology:
                raise ValueError(f"'{node}' has unknown parent '{parent}'")
            children.setdefault(parent, []).append(node)

    def ancestors(n: str) -> list[str]:
        seen, cur = [], topology[n]
        while cur is not None:
            if cur in seen or cur == n:
                raise ValueError("the topology contains a cycle")
            seen.append(cur); cur = topology[cur]
        return seen

    def subtree(n: str) -> list[str]:
        out, stack = [], list(children.get(n, []))
        while stack:
            x = stack.pop(); out.append(x); stack.extend(children.get(x, []))
        return out

    alarmed = set(alarms)
    roots = sorted(n for n in alarmed if not (set(ancestors(n)) & alarmed))
    result = []
    for n in roots:
        sub = subtree(n)
        symptoms = sorted(x for x in sub if x in alarmed)
        impact = sum(int(customers.get(x, 0)) for x in [n, *sub])
        result.append({"node": n, "alarmed_descendants": symptoms, "downstream_nodes": len(sub), "customers_affected": impact,
                       "explains": len(symptoms) + 1, "confidence": round((len(symptoms) + 1) / len(alarmed), 3)})
    result.sort(key=lambda r: (-r["explains"], -r["customers_affected"], r["node"]))
    return {"probable_root_causes": result, "alarms": len(alarmed), "method": "upstream-most alarmed nodes (topology reasoning)",
            "note": "A ranked hypothesis from topology and alarms; it is not a diagnosis. Verify on the network."}


# ── hospitality ─────────────────────────────────────────────────────────────

def hotel_kpis(rooms_available: Any, rooms_sold: Any, room_revenue: Any, total_revenue: Any = None) -> dict[str, Any]:
    avail, sold, rev = _num(rooms_available, "rooms_available", 0), _num(rooms_sold, "rooms_sold", 0), _num(room_revenue, "room_revenue", 0)
    if avail == 0:
        raise ValueError("rooms_available must be greater than 0")
    if sold > avail:
        raise ValueError("rooms_sold cannot exceed rooms_available")
    out = {"occupancy": round(sold / avail, 4), "adr": round(rev / sold, 2) if sold else None, "revpar": round(rev / avail, 2)}
    if total_revenue is not None:
        out["trevpar"] = round(_num(total_revenue, "total_revenue", 0) / avail, 2)
    return out


def _binom_pmf(n: int, k: int, p: float) -> float:
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    return math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p))


def overbooking(capacity: Any, no_show_rate: Any, room_rate: Any, walk_cost: Any, max_extra: int = 50) -> dict[str, Any]:
    """Choose how many bookings beyond capacity minimise expected cost (walked guests vs empty rooms)."""
    cap = int(_num(capacity, "capacity", 1, 2000))
    p_show = 1.0 - _num(no_show_rate, "no_show_rate", 0, 0.95)
    rate, walk = _num(room_rate, "room_rate", 0), _num(walk_cost, "walk_cost", 0)
    extra_max = int(_num(max_extra, "max_extra", 0, 200))
    best = None
    table = []
    for k in range(extra_max + 1):
        n = cap + k
        pmf = [_binom_pmf(n, x, p_show) for x in range(n + 1)]
        denied = sum(pr * max(0, x - cap) for x, pr in enumerate(pmf))
        empty = sum(pr * max(0, cap - x) for x, pr in enumerate(pmf))
        cost = denied * walk + empty * rate
        table.append((k, cost))
        if best is None or cost < best[1] - 1e-12:
            best = (k, cost, denied, empty)
    k, cost, denied, empty = best
    return {"recommended_extra_bookings": k, "bookings_to_accept": cap + k, "expected_walked_guests": round(denied, 4),
            "expected_empty_rooms": round(empty, 4), "expected_cost": round(cost, 2),
            "cost_without_overbooking": round(table[0][1], 2), "model": "binomial show-up, independent guests",
            "note": "Assumes guests show up independently; group bookings and correlated cancellations break that."}


# ── revenue intelligence ────────────────────────────────────────────────────

def deal_risk(deal: Any) -> dict[str, Any]:
    if not isinstance(deal, dict):
        raise ValueError("deal must be an object")
    factors, score = [], 0

    def add(points: int, why: str) -> None:
        nonlocal score
        score += points; factors.append({"points": points, "reason": why})

    days_stage = _num(deal.get("days_in_stage", 0), "days_in_stage", 0)
    typical = _num(deal.get("typical_days_in_stage", 21), "typical_days_in_stage", 1)
    if days_stage > 2 * typical:
        add(25, f"{days_stage:g} days in stage is over twice the typical {typical:g}")
    elif days_stage > typical:
        add(10, f"{days_stage:g} days in stage exceeds the typical {typical:g}")
    idle = _num(deal.get("days_since_activity", 0), "days_since_activity", 0)
    if idle > 21:
        add(25, f"no activity for {idle:g} days")
    elif idle > 10:
        add(12, f"no activity for {idle:g} days")
    if int(_num(deal.get("contacts", 1), "contacts", 0)) <= 1:
        add(15, "single-threaded: only one contact")
    if not deal.get("has_champion", True):
        add(15, "no identified champion")
    slips = int(_num(deal.get("close_date_slips", 0), "close_date_slips", 0))
    if slips:
        add(min(20, 8 * slips), f"close date slipped {slips} time(s)")
    disc = _num(deal.get("discount_pct", 0), "discount_pct", 0, 100)
    if disc > 25:
        add(10, f"a {disc:g}% discount signals price resistance")
    if not deal.get("next_step_scheduled", True):
        add(10, "no next step is scheduled")
    score = min(score, 100)
    return {"risk_score": score, "level": "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW", "factors": factors,
            "method": "transparent additive rules, not a trained model"}


def renewal_risk(account: Any) -> dict[str, Any]:
    if not isinstance(account, dict):
        raise ValueError("account must be an object")
    factors, score = [], 0

    def add(points: int, why: str) -> None:
        nonlocal score
        score += points; factors.append({"points": points, "reason": why})

    usage = _num(account.get("usage_change_pct", 0), "usage_change_pct", -100, 10_000)
    if usage <= -30:
        add(30, f"usage is down {abs(usage):g}%")
    elif usage < -10:
        add(15, f"usage is down {abs(usage):g}%")
    nps = account.get("nps")
    if nps is not None and _num(nps, "nps", -100, 100) < 0:
        add(20, f"NPS is negative ({nps})")
    tickets = int(_num(account.get("open_critical_tickets", 0), "open_critical_tickets", 0))
    if tickets:
        add(min(20, 10 * tickets), f"{tickets} open critical ticket(s)")
    late = int(_num(account.get("late_payments", 0), "late_payments", 0))
    if late:
        add(min(15, 5 * late), f"{late} late payment(s)")
    days = _num(account.get("days_to_renewal", 365), "days_to_renewal", 0)
    if days <= 60 and score >= 30:
        add(10, f"renewal is only {days:g} days away")
    if not account.get("executive_sponsor", True):
        add(10, "no executive sponsor")
    score = min(score, 100)
    return {"risk_score": score, "level": "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW", "factors": factors,
            "method": "transparent additive rules, not a trained model"}


def revenue_leakage(contracts: Any, invoices: Any, tolerance: float = 0.005) -> dict[str, Any]:
    """Reconcile what contracts say should be billed against what was invoiced, per (customer, item)."""
    tol = _num(tolerance, "tolerance", 0, 1)
    expected: dict[tuple, dict] = {}
    for c in _list(contracts, "contracts"):
        if not isinstance(c, dict) or not all(k in c for k in ("customer", "item", "unit_price", "quantity")):
            raise ValueError("every contract needs customer, item, unit_price and quantity")
        key = (c["customer"], c["item"])
        prev = expected.get(key)
        qty = _num(c["quantity"], "quantity", 0)
        expected[key] = {"unit_price": _num(c["unit_price"], "unit_price", 0), "quantity": qty + (prev["quantity"] if prev else 0)}
    billed: dict[tuple, dict] = {}
    for i in _list(invoices, "invoices"):
        if not isinstance(i, dict) or not all(k in i for k in ("customer", "item", "unit_price", "quantity")):
            raise ValueError("every invoice line needs customer, item, unit_price and quantity")
        key = (i["customer"], i["item"])
        b = billed.setdefault(key, {"amount": 0.0, "quantity": 0.0, "prices": set()})
        b["amount"] += _num(i["unit_price"], "unit_price", 0) * _num(i["quantity"], "quantity", 0)
        b["quantity"] += _num(i["quantity"], "quantity", 0)
        b["prices"].add(float(i["unit_price"]))
    issues, leakage, overbilled = [], 0.0, 0.0
    for key in sorted(set(expected) | set(billed), key=str):
        cust, item = key
        e, b = expected.get(key), billed.get(key)
        if e and not b:
            amt = e["unit_price"] * e["quantity"]
            issues.append({"customer": cust, "item": item, "type": "UNBILLED", "amount": round(amt, 2)}); leakage += amt
        elif b and not e:
            issues.append({"customer": cust, "item": item, "type": "BILLED_WITHOUT_CONTRACT", "amount": round(b["amount"], 2)}); overbilled += b["amount"]
        else:
            want = e["unit_price"] * e["quantity"]
            diff = b["amount"] - want
            if abs(diff) > tol * max(want, 1):
                kind = "UNDERBILLED" if diff < 0 else "OVERBILLED"
                issues.append({"customer": cust, "item": item, "type": kind, "amount": round(abs(diff), 2), "expected": round(want, 2),
                               "billed": round(b["amount"], 2)})
                if diff < 0:
                    leakage += -diff
                else:
                    overbilled += diff
    return {"issues": issues, "estimated_leakage": round(leakage, 2), "estimated_overbilling": round(overbilled, 2),
            "lines_checked": len(set(expected) | set(billed))}


# ── cyber defence ───────────────────────────────────────────────────────────

_CVSS = {"AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}, "AC": {"L": 0.77, "H": 0.44}, "UI": {"N": 0.85, "R": 0.62},
         "C": {"H": 0.56, "L": 0.22, "N": 0.0}, "I": {"H": 0.56, "L": 0.22, "N": 0.0}, "A": {"H": 0.56, "L": 0.22, "N": 0.0}}


def _roundup(x: float) -> float:
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss_base(vector: Any) -> dict[str, Any]:
    """CVSS v3.1 base score from a vector string such as CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H."""
    if not isinstance(vector, str) or not vector.startswith(("CVSS:3.1/", "CVSS:3.0/")):
        raise ValueError("vector must start with CVSS:3.1/")
    try:
        m = dict(part.split(":", 1) for part in vector.split("/")[1:])
    except ValueError:
        raise ValueError("the vector is malformed") from None
    need = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")
    if any(k not in m for k in need) or set(m) - set(need):
        raise ValueError("the vector must contain exactly AV, AC, PR, UI, S, C, I and A")
    changed = m["S"] == "C"
    if m["S"] not in ("U", "C") or m["PR"] not in ("N", "L", "H"):
        raise ValueError("invalid S or PR value")
    try:
        av, ac, ui = _CVSS["AV"][m["AV"]], _CVSS["AC"][m["AC"]], _CVSS["UI"][m["UI"]]
        c, i, a = _CVSS["C"][m["C"]], _CVSS["I"][m["I"]], _CVSS["A"][m["A"]]
    except KeyError as exc:
        raise ValueError(f"invalid metric value {exc}") from None
    pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[m["PR"]]
    iss = 1 - (1 - c) * (1 - i) * (1 - a)
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    expl = 8.22 * av * ac * pr * ui
    if impact <= 0:
        score = 0.0
    else:
        score = _roundup(min(1.08 * (impact + expl), 10)) if changed else _roundup(min(impact + expl, 10))
    sev = "NONE" if score == 0 else "LOW" if score < 4 else "MEDIUM" if score < 7 else "HIGH" if score < 9 else "CRITICAL"
    return {"base_score": score, "severity": sev, "impact_subscore": round(impact, 1), "exploitability_subscore": round(expl, 1),
            "version": vector[5:8]}


_SEV = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_CONTAINMENT = {"malware": ["isolate the host from the network", "revoke the user's active sessions"],
                "phishing": ["quarantine the message from all mailboxes", "reset the affected credentials"],
                "bruteforce": ["lock the targeted account", "block the source address at the edge"],
                "exfiltration": ["block the destination at egress", "suspend the account's data access"],
                "vulnerability": ["apply the vendor patch or mitigation", "restrict exposure until patched"]}


def triage_incidents(events: Any, window_minutes: float = 30) -> dict[str, Any]:
    """Correlate events on the same asset within a time window and rank them. Containment is suggested, never executed."""
    win = _num(window_minutes, "window_minutes", 1, 1440)
    rows = []
    for e in _list(events, "events"):
        if not isinstance(e, dict) or not isinstance(e.get("asset"), str) or not isinstance(e.get("type"), str):
            raise ValueError("every event needs a string 'asset' and 'type'")
        sev = _SEV.get(str(e.get("severity", "low")).lower())
        if sev is None:
            raise ValueError("severity must be low, medium, high or critical")
        rows.append({"asset": e["asset"], "type": e["type"].lower(), "sev": sev, "t": _num(e.get("minute", 0), "minute", 0),
                     "crit": int(_num(e.get("asset_criticality", 1), "asset_criticality", 1, 5)), "count": int(_num(e.get("count", 1), "count", 1))})
    rows.sort(key=lambda r: (r["asset"], r["t"]))
    groups: list[list[dict]] = []
    for r in rows:
        if groups and groups[-1][0]["asset"] == r["asset"] and r["t"] - groups[-1][-1]["t"] <= win:
            groups[-1].append(r)
        else:
            groups.append([r])
    incidents = []
    for g in groups:
        kinds = sorted({r["type"] for r in g})
        top, crit = max(r["sev"] for r in g), max(r["crit"] for r in g)
        volume = sum(r["count"] for r in g)
        score = min(100, top * 15 + crit * 8 + min(20, 5 * (len(kinds) - 1)) + min(15, int(math.log2(volume + 1) * 3)))
        incidents.append({"asset": g[0]["asset"], "event_types": kinds, "events": len(g), "total_count": volume,
                          "priority_score": score, "priority": "P1" if score >= 75 else "P2" if score >= 50 else "P3",
                          "window_start_minute": g[0]["t"], "window_end_minute": g[-1]["t"],
                          "suggested_containment": sorted({a for k in kinds for a in _CONTAINMENT.get(k, [])}),
                          "containment_requires_approval": True})
    incidents.sort(key=lambda i: (-i["priority_score"], i["asset"]))
    return {"incidents": incidents, "events_in": len(rows), "method": "rule-based correlation and scoring",
            "note": "Suggestions only. Any containment action must go through MO's approval gate."}
