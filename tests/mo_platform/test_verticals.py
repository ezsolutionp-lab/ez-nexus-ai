"""Vertical engines: known values (CVSS, hotel KPIs, overbooking), graph reasoning, reconciliation, input limits."""

import math

import pytest

from app.mo.context import RequestContext
from app.mo.errors import ResultState
from app.mo.intelligence import business_box, verticals as v
from app.mo.tools.spec import get_tool_registry

pytestmark = pytest.mark.builder


# ── CVSS ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("vector,score,sev", [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8, "CRITICAL"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1, "MEDIUM"),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", 5.5, "MEDIUM"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0, "CRITICAL"),
    ("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", 1.6, "LOW"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0, "NONE"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:L", 7.4, "HIGH"),
])
def test_cvss_matches_published_scores(vector, score, sev):
    r = v.cvss_base(vector)
    assert r["base_score"] == score and r["severity"] == sev


@pytest.mark.parametrize("bad", ["", None, "AV:N", "CVSS:3.1/AV:N", "CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                                 "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:F", "CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P", "CVSS:3.1/AV/AC"])
def test_cvss_rejects_malformed_vectors(bad):
    with pytest.raises(ValueError):
        v.cvss_base(bad)


# ── telecom ─────────────────────────────────────────────────────────────────

def test_cell_health_classifies_and_ranks_worst_first():
    r = v.cell_health([{"id": "c1", "prb_utilization": 0.4, "drop_rate": 0.002, "availability": 0.999, "throughput_mbps": 50},
                       {"id": "c2", "prb_utilization": 0.75, "drop_rate": 0.002},
                       {"id": "c3", "prb_utilization": 0.95, "drop_rate": 0.05, "availability": 0.9}])
    assert [c["id"] for c in r["cells"]] == ["c3", "c2", "c1"]
    assert r["summary"] == {"HEALTHY": 1, "DEGRADED": 1, "CRITICAL": 1}
    assert len(next(c for c in r["cells"] if c["id"] == "c3")["reasons"]) == 3


def test_capacity_breach_reports_the_first_period_over_threshold():
    r = v.capacity_breach([0.50 + 0.01 * i for i in range(30)], threshold=0.85, horizon=60)
    assert r["breach_expected"] and 3 <= r["periods_until_breach"] <= 8
    assert v.capacity_breach([0.3] * 20, 0.8, 30)["breach_expected"] is False


def test_root_cause_prefers_the_upstream_alarm_that_explains_the_rest():
    topo = {"core": None, "agg1": "core", "agg2": "core", "a": "agg1", "b": "agg1", "c": "agg2"}
    r = v.root_cause(topo, ["agg1", "a", "b", "c"], {"a": 1000, "b": 800, "c": 500})
    top = r["probable_root_causes"][0]
    assert top["node"] == "agg1" and top["alarmed_descendants"] == ["a", "b"] and top["customers_affected"] == 1800
    assert [x["node"] for x in r["probable_root_causes"]] == ["agg1", "c"]
    assert v.root_cause(topo, ["a"])["probable_root_causes"][0]["node"] == "a"


@pytest.mark.parametrize("topo,alarms", [({}, ["a"]), ({"a": None}, []), ({"a": None}, ["zzz"]), ({"a": "ghost"}, ["a"]),
                                         ({"a": "b", "b": "a"}, ["a"]), ("x", ["a"])])
def test_root_cause_validates_topology(topo, alarms):
    with pytest.raises(ValueError):
        v.root_cause(topo, alarms)


# ── hospitality ─────────────────────────────────────────────────────────────

def test_hotel_kpis_known_values():
    r = v.hotel_kpis(100, 80, 12000, 15000)
    assert r == {"occupancy": 0.8, "adr": 150.0, "revpar": 120.0, "trevpar": 150.0}
    assert v.hotel_kpis(50, 0, 0)["adr"] is None
    for args in ((0, 0, 0), (10, 11, 5), (10, -1, 5), (10, True, 5)):
        with pytest.raises(ValueError):
            v.hotel_kpis(*args)


def test_overbooking_finds_the_cost_minimum():
    r = v.overbooking(100, 0.10, 150, 400)
    assert r["cost_without_overbooking"] == 1500.0                    # 10 expected empty rooms x $150
    assert 5 <= r["recommended_extra_bookings"] <= 12 and r["expected_cost"] < 1500
    costlier_walk = v.overbooking(100, 0.10, 150, 4000)
    assert costlier_walk["recommended_extra_bookings"] < r["recommended_extra_bookings"]
    assert v.overbooking(100, 0.0, 150, 400)["recommended_extra_bookings"] == 0          # nobody no-shows: never overbook
    # the recommended level really is a minimum of the expected-cost curve
    cost = lambda k: v.overbooking(100, 0.10, 150, 400, max_extra=k)["expected_cost"]
    assert cost(r["recommended_extra_bookings"]) <= cost(r["recommended_extra_bookings"] + 5)


def test_overbooking_validation():
    for args in ((0, 0.1, 100, 100), (100, 0.99, 100, 100), (100, 0.1, -1, 100), (100, "x", 1, 1)):
        with pytest.raises(ValueError):
            v.overbooking(*args)


# ── revenue intelligence ────────────────────────────────────────────────────

def test_deal_risk_attributes_every_point():
    r = v.deal_risk({"days_in_stage": 50, "typical_days_in_stage": 20, "days_since_activity": 30, "contacts": 1, "has_champion": False,
                     "close_date_slips": 2, "discount_pct": 30, "next_step_scheduled": False})
    total = sum(f["points"] for f in r["factors"])
    assert r["level"] == "HIGH" and total == 116 and r["risk_score"] == min(100, total) == 100      # capped, factors stay visible
    mild = v.deal_risk({"days_in_stage": 25, "typical_days_in_stage": 20, "contacts": 2})
    assert mild["risk_score"] == sum(f["points"] for f in mild["factors"]) == 10 and mild["level"] == "LOW"
    healthy = v.deal_risk({"days_in_stage": 5, "days_since_activity": 2, "contacts": 4})
    assert healthy["level"] == "LOW" and healthy["risk_score"] == 0


def test_renewal_risk():
    r = v.renewal_risk({"usage_change_pct": -45, "nps": -10, "open_critical_tickets": 2, "late_payments": 2, "days_to_renewal": 30,
                        "executive_sponsor": False})
    assert r["level"] == "HIGH" and any("usage is down" in f["reason"] for f in r["factors"])
    assert v.renewal_risk({"usage_change_pct": 20})["level"] == "LOW"


def test_revenue_leakage_reconciliation():
    contracts = [{"customer": "A", "item": "seat", "unit_price": 10, "quantity": 100},
                 {"customer": "B", "item": "support", "unit_price": 500, "quantity": 1},
                 {"customer": "C", "item": "seat", "unit_price": 10, "quantity": 10}]
    invoices = [{"customer": "A", "item": "seat", "unit_price": 10, "quantity": 80},
                {"customer": "C", "item": "seat", "unit_price": 12, "quantity": 10},
                {"customer": "D", "item": "misc", "unit_price": 99, "quantity": 1}]
    r = v.revenue_leakage(contracts, invoices)
    kinds = {(i["customer"], i["type"]): i["amount"] for i in r["issues"]}
    assert kinds == {("A", "UNDERBILLED"): 200.0, ("B", "UNBILLED"): 500.0, ("C", "OVERBILLED"): 20.0, ("D", "BILLED_WITHOUT_CONTRACT"): 99.0}
    assert r["estimated_leakage"] == 700.0 and r["estimated_overbilling"] == 119.0
    clean = v.revenue_leakage(contracts[:1], [{"customer": "A", "item": "seat", "unit_price": 10, "quantity": 100}])
    assert clean["issues"] == []


def test_revenue_leakage_validation():
    with pytest.raises(ValueError):
        v.revenue_leakage([{"customer": "A"}], [{"customer": "A", "item": "x", "unit_price": 1, "quantity": 1}])


# ── cyber triage ────────────────────────────────────────────────────────────

def test_triage_correlates_by_asset_and_window_and_never_executes():
    events = [{"asset": "web-1", "type": "bruteforce", "severity": "medium", "minute": 0, "count": 200, "asset_criticality": 4},
              {"asset": "web-1", "type": "malware", "severity": "high", "minute": 10, "count": 1, "asset_criticality": 4},
              {"asset": "web-1", "type": "bruteforce", "severity": "low", "minute": 500, "count": 2, "asset_criticality": 4},
              {"asset": "kiosk", "type": "phishing", "severity": "low", "minute": 5}]
    r = v.triage_incidents(events)
    assert len(r["incidents"]) == 3
    first = r["incidents"][0]
    assert first["asset"] == "web-1" and first["events"] == 2 and first["priority"] in ("P1", "P2")
    assert set(first["event_types"]) == {"bruteforce", "malware"} and first["containment_requires_approval"] is True
    assert any("isolate the host" in a for a in first["suggested_containment"])
    assert r["incidents"][-1]["priority"] == "P3"


def test_triage_validation():
    for events in ([], [{"asset": "a"}], [{"asset": "a", "type": "x", "severity": "extreme"}], "no"):
        with pytest.raises(ValueError):
            v.triage_incidents(events)


# ── business in a box ───────────────────────────────────────────────────────

def test_all_twelve_verticals_produce_a_complete_blueprint():
    assert len(business_box.verticals()) == 12
    for name in business_box.verticals():
        b = business_box.blueprint(name, "Acme")
        for key in ("services", "roles", "agents", "kpis", "compliance", "integrations", "modules", "builder_prompt"):
            assert b[key], (name, key)
        assert "Do not deploy" in b["builder_prompt"] and "CREDENTIAL_REQUIRED" in b["builder_prompt"]


def test_blueprint_aliases_and_errors():
    assert business_box.blueprint("hvac")["vertical"] == "HVAC" and business_box.blueprint("Dentist")["vertical"] == "dental"
    for bad in ("", "spaceship repair", None, 5):
        with pytest.raises(ValueError):
            business_box.blueprint(bad)
    with pytest.raises(ValueError):
        business_box.blueprint("law", "x" * 200)


def test_blueprint_prompt_drives_the_real_builder(db, admin_ctx, workspace_root):
    from app.mo.builder.compiler import BuilderCompiler
    from app.mo.builder.intent import BuildIntent
    prompt = business_box.blueprint("plumbing", "Acme Plumbing")["builder_prompt"]
    project, _ = BuilderCompiler(db, admin_ctx, workspace_root=workspace_root).compile(
        BuildIntent(prompt=prompt, tenant_id=admin_ctx.tenant_id, requested_by=admin_ctx.actor_id), run_build=False)
    assert project.status != "DEPLOYED" and project.name


# ── governed tools ──────────────────────────────────────────────────────────

@pytest.fixture
def dctx(tenant_a):
    return RequestContext(tenant_id=tenant_a, actor_id="u", scopes=frozenset({"domain:run"}))


@pytest.mark.parametrize("tool,payload,check", [
    ("domain.cvss", {"vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}, lambda d: d["base_score"] == 9.8),
    ("domain.hotel_kpis", {"rooms_available": 100, "rooms_sold": 80, "room_revenue": 12000}, lambda d: d["revpar"] == 120.0),
    ("domain.overbooking", {"capacity": 50, "no_show_rate": 0.1, "room_rate": 100, "walk_cost": 300}, lambda d: d["recommended_extra_bookings"] >= 1),
    ("domain.cell_health", {"cells": [{"id": "x", "prb_utilization": 0.95}]}, lambda d: d["summary"]["CRITICAL"] == 1),
    ("domain.deal_risk", {"deal": {"contacts": 1}}, lambda d: d["risk_score"] >= 15),
    ("domain.business_blueprint", {"vertical": "law"}, lambda d: d["vertical"] == "law"),
])
def test_verticals_are_governed_tools(dctx, ctx, tool, payload, check):
    reg = get_tool_registry()
    assert reg.invoke(ctx, tool, payload).state == ResultState.POLICY_DENIED             # needs domain:run
    res = reg.invoke(dctx, tool, payload)
    assert res.state == ResultState.SUCCESS and check(res.data)
    assert reg.get(tool).risk_level == "LOW"


def test_bad_vertical_input_is_a_failure_not_a_crash(dctx):
    res = get_tool_registry().invoke(dctx, "domain.cvss", {"vector": "nonsense"})
    assert res.state == ResultState.FAILED and "Invalid input" in res.detail
