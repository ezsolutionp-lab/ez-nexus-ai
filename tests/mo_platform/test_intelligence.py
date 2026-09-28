"""Intelligence engines: known values, determinism, input limits, and tool governance."""

from datetime import date

import pytest

from app.mo.context import RequestContext
from app.mo.errors import ResultState
from app.mo.intelligence import commercial, planning, text, timeseries
from app.mo.tools.spec import get_tool_registry

pytestmark = pytest.mark.builder


# ── timeseries ──────────────────────────────────────────────────────────────

def test_forecast_recovers_linear_trend():
    r = timeseries.forecast([10, 12, 14, 16, 18, 20], horizon=3)
    assert r["forecast"] == pytest.approx([22, 24, 26], abs=0.5)
    assert all(lo <= f <= hi for lo, f, hi in zip(r["lower_95"], r["forecast"], r["upper_95"]))
    assert "not a neural model" in r["model_class"]


def test_forecast_seasonal_pattern_continues():
    base = [10, 20, 30, 20]
    r = timeseries.forecast(base * 4, horizon=4, season=4)
    assert r["forecast"] == pytest.approx(base, abs=1.0)


def test_forecast_seasonal_with_trend_and_odd_season():
    y = [t * 2 + [0, 6, -6][t % 3] for t in range(18)]
    r = timeseries.forecast(y, horizon=3, season=3)
    assert r["forecast"] == pytest.approx([36 + 0, 38 + 6, 40 - 6], abs=1.0)


@pytest.mark.parametrize("series,kw", [
    ([1, 2], {}), ("abc", {}), ([1, 2, float("nan"), 4], {}), ([1, 2, True, 4], {}),
    ([1, 2, 3, 4, 5], {"horizon": 0}), ([1, 2, 3, 4, 5], {"horizon": 10_000}),
    ([1, 2, 3, 4, 5], {"season": 1}), ([1, 2, 3, 4, 5], {"season": 4}),
])
def test_forecast_rejects_bad_input(series, kw):
    with pytest.raises(ValueError):
        timeseries.forecast(series, **kw)


def test_forecast_rejects_oversized_series():
    with pytest.raises(ValueError):
        timeseries.forecast([1.0] * (timeseries.MAX_POINTS + 1))


@pytest.mark.parametrize("method", ["mad", "zscore", "iqr"])
def test_anomaly_methods_find_a_single_spike(method):
    series = [10, 11, 10, 12, 11, 10, 95, 11, 10, 12]
    idx = {a["index"] for a in timeseries.anomalies(series, method, 2.5 if method == "zscore" else None)["anomalies"]}
    assert idx == {6}


def test_robust_methods_catch_repeated_spikes_that_mask_the_zscore():
    series = [10, 11, 10, 12, 11, 10, 95, 11, 10, 12] * 2
    assert {a["index"] for a in timeseries.anomalies(series, "mad")["anomalies"]} == {6, 16}
    assert {a["index"] for a in timeseries.anomalies(series, "iqr")["anomalies"]} == {6, 16}
    assert timeseries.anomalies(series, "zscore")["anomalies"] == []     # the outliers inflate the stdev


def test_anomaly_none_in_clean_series_and_constant_series():
    assert timeseries.anomalies([5, 6, 5, 6, 5, 6, 5, 6])["anomalies"] == []
    assert timeseries.anomalies([7] * 10, "zscore")["anomalies"] == []


def test_anomaly_rejects_unknown_method():
    with pytest.raises(ValueError):
        timeseries.anomalies([1, 2, 3, 4, 5, 6], "magic")


# ── planning ────────────────────────────────────────────────────────────────

CLASSIC = [
    {"id": "A", "duration": 3}, {"id": "B", "duration": 2},
    {"id": "C", "duration": 2, "deps": ["A"]}, {"id": "D", "duration": 3, "deps": ["B", "C"]},
]


def test_critical_path_known_answer():
    r = planning.critical_path(CLASSIC)
    assert r["project_duration"] == 8
    assert r["critical_path"] == ["A", "C", "D"]
    slack = {t["id"]: t["slack"] for t in r["tasks"]}
    assert slack["B"] == 3 and slack["A"] == 0


def test_critical_path_rejects_cycles_unknown_deps_duplicates():
    with pytest.raises(ValueError, match="(?i)cycle"):
        planning.critical_path([{"id": "A", "duration": 1, "deps": ["B"]}, {"id": "B", "duration": 1, "deps": ["A"]}])
    with pytest.raises(ValueError):
        planning.critical_path([{"id": "A", "duration": 1, "deps": ["Z"]}])
    with pytest.raises(ValueError):
        planning.critical_path([{"id": "A", "duration": 1}, {"id": "A", "duration": 2}])
    with pytest.raises(ValueError):
        planning.critical_path([])
    with pytest.raises(ValueError):
        planning.critical_path([{"id": f"t{i}", "duration": 1} for i in range(planning.MAX_TASKS + 1)])


MC = [{"id": "A", "optimistic": 2, "likely": 3, "pessimistic": 8},
      {"id": "B", "optimistic": 1, "likely": 2, "pessimistic": 4, "deps": ["A"]}]


def test_monte_carlo_is_deterministic_and_ordered():
    a, b = planning.monte_carlo(MC, 2000, seed=7), planning.monte_carlo(MC, 2000, seed=7)
    assert a == b
    p = a["percentiles"]
    assert p["p10"] <= p["p50"] <= p["p80"] <= p["p90"] <= p["p95"]
    assert 3 <= a["mean"] <= 12
    assert planning.monte_carlo(MC, 2000, seed=8)["mean"] != a["mean"]


def test_monte_carlo_mean_matches_triangular_expectation():
    # E[triangular] = (a+b+c)/3 ; serial tasks add
    expected = (2 + 3 + 8) / 3 + (1 + 2 + 4) / 3
    assert planning.monte_carlo(MC, 20000, seed=1)["mean"] == pytest.approx(expected, abs=0.1)


def test_monte_carlo_deadline_probability_bounds():
    assert planning.monte_carlo(MC, 1000, deadline=1000)["probability_of_meeting_deadline"] == 1.0
    assert planning.monte_carlo(MC, 1000, deadline=1)["probability_of_meeting_deadline"] == 0.0


def test_monte_carlo_rejects_bad_input():
    with pytest.raises(ValueError):
        planning.monte_carlo([{"id": "A", "optimistic": 5, "likely": 3, "pessimistic": 9}])
    with pytest.raises(ValueError):
        planning.monte_carlo(MC, simulations=10)
    with pytest.raises(ValueError):
        planning.monte_carlo(MC, simulations=planning.MAX_SIMULATIONS + 1)


# ── commercial ──────────────────────────────────────────────────────────────

def test_pricing_floor_and_elasticity_known_values():
    r = commercial.price_recommendation(70, target_margin=0.3)
    assert r["floor_price"] == 100.0
    assert {n["figure"] for n in r["not_computed"]} == {"competitor_band", "elasticity_optimum"}
    r = commercial.price_recommendation(70, competitor_prices=[90, 100, 110, 120], price_elasticity=-3)
    assert r["elasticity_optimum"] == 105.0 and r["recommended_price"] == 105.0
    assert r["market_position"] == "competitive"


def test_pricing_admits_being_priced_out_and_refuses_inelastic_optimum():
    r = commercial.price_recommendation(90, target_margin=0.3, competitor_prices=[80, 85, 90], price_elasticity=-0.5)
    assert r["market_position"] == "priced_out"
    assert r["recommended_price"] == r["floor_price"]
    assert any(n["figure"] == "elasticity_optimum" for n in r["not_computed"])
    assert "elasticity_optimum" not in r


@pytest.mark.parametrize("kw", [{"unit_cost": -1}, {"unit_cost": 1, "target_margin": 1.0},
                                {"unit_cost": 1, "price_elasticity": 2}, {"unit_cost": "x"},
                                {"unit_cost": 1, "competitor_prices": [-5]}])
def test_pricing_rejects_bad_input(kw):
    with pytest.raises(ValueError):
        commercial.price_recommendation(**kw)


def test_lead_score_is_fully_attributed_and_grades():
    hot = commercial.score_lead({"company_size": 500, "seniority": "vp", "source": "referral",
                                 "intent": "demo_request", "budget_confirmed": True, "days_since_last_contact": 2})
    assert hot["score"] >= 75 and hot["grade"] == "A"
    assert sum(f["points"] for f in hot["factors"]) <= sum(f["max"] for f in hot["factors"])
    cold = commercial.score_lead({"source": "purchased_list"})
    assert cold["grade"] == "D"
    assert "seniority" in cold["missing_inputs"]
    assert "not a trained model" in cold["method"]


def test_lead_score_rejects_non_object():
    with pytest.raises(ValueError):
        commercial.score_lead("hot")


def test_pipeline_forecast_math():
    deals = [{"amount": 1000, "stage": "won"}, {"amount": 1000, "stage": "negotiation"},
             {"amount": 2000, "stage": "qualified"}, {"amount": 500, "stage": "lost"},
             {"amount": 100, "stage": "mystery"}]
    r = commercial.pipeline_forecast(deals)
    assert r["won"] == 1000
    assert r["weighted_open"] == 1000 * 0.6 + 2000 * 0.15
    assert r["commit"] == 1000 and r["best_case"] == 3000
    assert r["expected_total"] == 1000 + 900
    assert r["skipped_unknown_stage"] == ["mystery"]


def test_pipeline_override_and_validation():
    r = commercial.pipeline_forecast([{"amount": 100, "stage": "lead", "probability": 0.5}])
    assert r["weighted_open"] == 50
    with pytest.raises(ValueError):
        commercial.pipeline_forecast([])
    with pytest.raises(ValueError):
        commercial.pipeline_forecast([{"amount": 1, "stage": "lead", "probability": 2}])


def test_npv_irr_known_values():
    flows = [-100, 60, 60]
    assert commercial.npv(0.1, flows) == pytest.approx(4.1322, abs=1e-3)
    assert commercial.irr(flows) == pytest.approx(0.130662, abs=1e-5)
    assert commercial.npv(commercial.irr(flows), flows) == pytest.approx(0, abs=1e-6)
    assert commercial.irr([100, 50]) is None
    assert commercial.irr([-100, -50]) is None


def test_finance_computes_only_what_it_can():
    r = commercial.finance_metrics({"revenue": 1000, "cost_of_goods_sold": 400, "cash": 120000,
                                    "monthly_cash_out": 30000, "monthly_cash_in": 10000,
                                    "net_new_revenue_monthly": 5000})
    assert r["gross_margin"] == 0.6
    assert r["monthly_burn"] == 20000 and r["runway_months"] == 6.0
    assert r["burn_multiple"] == 4.0
    figures = {n["figure"] for n in r["not_computed"]}
    assert {"net_margin", "current_ratio", "debt_to_equity"} <= figures
    assert "gross_margin" not in figures


def test_finance_ratios_and_cashflow():
    r = commercial.finance_metrics({"current_assets": 300, "inventory": 100, "current_liabilities": 100,
                                    "total_debt": 50, "total_equity": 200, "cashflows": [-100, 60, 60],
                                    "discount_rate": 0.1})
    assert r["current_ratio"] == 3.0 and r["quick_ratio"] == 2.0 and r["debt_to_equity"] == 0.25
    assert r["npv"] == pytest.approx(4.1322, abs=1e-3) and r["irr"] == pytest.approx(0.130662, abs=1e-5)


def test_finance_positive_cashflow_has_no_runway_and_no_divide_by_zero():
    r = commercial.finance_metrics({"monthly_cash_out": 5, "monthly_cash_in": 9, "revenue": 0,
                                    "cost_of_goods_sold": 0, "current_liabilities": 0, "current_assets": 5})
    assert r["runway_months"] is None and "no burn" in r["runway_note"]
    assert "gross_margin" not in r and "current_ratio" not in r


def test_finance_rejects_bad_input():
    with pytest.raises(ValueError):
        commercial.finance_metrics({"revenue": "lots"})
    with pytest.raises(ValueError):
        commercial.finance_metrics({"cashflows": [1]})
    with pytest.raises(ValueError):
        commercial.finance_metrics({"cashflows": [-1, 2], "discount_rate": -1})


def test_recommender_scores_and_reasons():
    baskets = [["a", "b"], ["a", "b", "c"], ["a", "c"], ["d"]]
    r = commercial.recommend(baskets, ["a"])
    top = r["recommendations"][0]
    assert top["because"] == "a" and top["score"] == pytest.approx(2 / (3 * 2) ** 0.5, abs=1e-4)
    assert all(x["item"] not in ("a",) for x in r["recommendations"])
    assert "d" not in {x["item"] for x in r["recommendations"]}
    assert commercial.recommend(baskets, ["zzz"])["unknown_seed_items"] == ["zzz"]


def test_recommender_validation():
    with pytest.raises(ValueError):
        commercial.recommend([], ["a"])
    with pytest.raises(ValueError):
        commercial.recommend([["a"]], [])
    with pytest.raises(ValueError):
        commercial.recommend([["a"]], ["a"], top_k=0)


# ── text ────────────────────────────────────────────────────────────────────

NOTES = """Meeting notes
Action: @sara to send the pricing deck by 2026-10-02
- Ravi will update the roadmap by friday
TODO: review contract
We talked about lunch.
"""


def test_action_items_owner_due_and_unattributed():
    r = text.extract_action_items(NOTES, today=date(2026, 9, 28))     # a Monday
    by = {i["task"][:12]: i for i in r["action_items"]}
    assert r["count"] == 3 and r["without_owner"] == 1
    assert by["@sara to sen"]["owner"] == "sara" and by["@sara to sen"]["due"] == "2026-10-02"
    assert by["Ravi will up"]["owner"] == "Ravi" and by["Ravi will up"]["due"] == "2026-10-02"
    assert by["review contr"]["owner"] is None and by["review contr"]["due"] is None


def test_action_item_relative_dates():
    d = date(2026, 9, 28)
    assert text.extract_action_items("TODO: ship it tomorrow by tomorrow", today=d)["action_items"][0]["due"] == "2026-09-29"
    assert text.extract_action_items("TODO: x by monday", today=d)["action_items"][0]["due"] == "2026-10-05"
    assert text.extract_action_items("TODO: x by 2026-13-45", today=d)["action_items"][0]["due"] is None


def test_action_items_none_found_and_limits():
    assert text.extract_action_items("just chatting here")["count"] == 0
    with pytest.raises(ValueError):
        text.extract_action_items("")
    with pytest.raises(ValueError):
        text.extract_action_items("x" * (text.MAX_TEXT_CHARS + 1))


def test_keywords_drop_stopwords_and_prefer_phrases():
    r = text.extract_keywords("pricing deck pricing deck roadmap the and of roadmap once", top_k=3)
    terms = [k["term"] for k in r["keywords"]]
    assert terms[0] == "pricing deck" and "the" not in terms and "and" not in terms
    with pytest.raises(ValueError):
        text.extract_keywords("hello", top_k=0)


def test_briefing_quiet_hours_hold_non_urgent_but_deliver_urgent():
    items = [{"title": "low one", "priority": "low"}, {"title": "fire", "priority": "urgent"},
             {"title": "normal", "priority": "normal"}]
    night = text.build_briefing(items, now="23:30")
    assert night["quiet_hours_active"] is True
    assert [x["title"] for x in night["deliver"]] == ["fire"]
    assert {x["title"] for x in night["held"]} == {"low one", "normal"}
    day = text.build_briefing(items, now="10:00")
    assert day["quiet_hours_active"] is False and day["held"] == []
    assert [x["title"] for x in day["deliver"]] == ["fire", "normal", "low one"]


def test_quiet_hours_boundaries_and_non_wrapping_window():
    assert text.build_briefing([], now="22:00")["quiet_hours_active"] is True
    assert text.build_briefing([], now="07:00")["quiet_hours_active"] is False
    assert text.build_briefing([], now="00:30")["quiet_hours_active"] is True
    assert text.build_briefing([], now="13:00", quiet_start="12:00", quiet_end="14:00")["quiet_hours_active"] is True
    assert text.build_briefing([], now="09:00", quiet_start="09:00", quiet_end="09:00")["quiet_hours_active"] is False


def test_briefing_overflow_and_validation():
    items = [{"title": f"t{i}", "priority": "normal"} for i in range(5)]
    r = text.build_briefing(items, now="10:00", max_items=2)
    assert len(r["deliver"]) == 2 and r["overflow"] == 3
    for bad in ([{"title": ""}], [{"title": "x", "priority": "asap"}], ["str"]):
        with pytest.raises(ValueError):
            text.build_briefing(bad, now="10:00")
    with pytest.raises(ValueError):
        text.build_briefing([], now="25:99")


# ── governed tools ──────────────────────────────────────────────────────────

def user(scopes=("domain:run",), tenant="t1"):
    return RequestContext(tenant_id=tenant, actor_id="u1", scopes=frozenset(scopes))


DOMAIN_TOOLS = {"domain.forecast", "domain.anomaly", "domain.montecarlo", "domain.critical_path", "domain.pricing",
                "domain.lead_score", "domain.pipeline_forecast", "domain.finance", "domain.recommend",
                "domain.keywords", "domain.action_items", "domain.briefing"}


def test_all_domain_tools_registered_low_risk_and_scoped():
    reg = get_tool_registry()
    assert DOMAIN_TOOLS <= set(reg.names())
    for n in DOMAIN_TOOLS:
        spec = reg.get(n)
        assert spec.risk_level == "LOW" and spec.required_scopes == ("domain:run",)
        assert spec.credential_env_var is None and spec.input_schema["additionalProperties"] is False


def test_tool_runs_and_requires_scope():
    reg = get_tool_registry()
    ok = reg.invoke(user(), "domain.critical_path", {"tasks": CLASSIC})
    assert ok.state.is_success and ok.data["project_duration"] == 8
    denied = reg.invoke(user(scopes=()), "domain.critical_path", {"tasks": CLASSIC})
    assert denied.state is ResultState.POLICY_DENIED


def test_engine_value_errors_become_failed_not_exceptions_or_success():
    reg = get_tool_registry()
    r = reg.invoke(user(), "domain.critical_path",
                   {"tasks": [{"id": "A", "duration": 1, "deps": ["A"]}]})
    assert r.state is ResultState.FAILED and "Invalid input" in r.detail


def test_tool_schema_rejects_unexpected_and_wrong_type():
    reg = get_tool_registry()
    assert reg.invoke(user(), "domain.keywords", {"text": "hello world", "evil": 1}).state is ResultState.FAILED
    assert reg.invoke(user(), "domain.keywords", {"text": 5}).state is ResultState.FAILED
    assert reg.invoke(user(), "domain.keywords", {}).state is ResultState.FAILED


def test_briefing_and_action_item_tools_end_to_end():
    reg = get_tool_registry()
    b = reg.invoke(user(), "domain.briefing", {"items": [{"title": "x", "priority": "low"}], "now": "23:00"})
    assert b.state.is_success and b.data["held"][0]["title"] == "x"
    a = reg.invoke(user(), "domain.action_items", {"text": "TODO: x by tomorrow", "today": "2026-09-28"})
    assert a.data["action_items"][0]["due"] == "2026-09-29"
    bad = reg.invoke(user(), "domain.action_items", {"text": "TODO: x", "today": "soon"})
    assert bad.state is ResultState.FAILED


def test_admin_context_can_use_tools_and_default_user_scope_includes_domain():
    reg = get_tool_registry()
    admin = RequestContext(tenant_id="t1", actor_id="a", is_admin=True, scopes=frozenset({"*"}))
    assert reg.invoke(admin, "domain.finance", {"data": {"revenue": 10, "net_income": 2}}).data["net_margin"] == 0.2
