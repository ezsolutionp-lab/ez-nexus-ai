"""Claim verification and the domain router: known answers, edge cases, limits, and tool governance."""

import pytest

from app.mo.context import RequestContext
from app.mo.errors import ResultState
from app.mo.intelligence.router import route_domain
from app.mo.tools.spec import get_tool_registry
from app.mo.truth import split_claims, verify_claims

pytestmark = pytest.mark.builder

EV = [
    {"id": "10k", "text": "Revenue grew 12% in 2025 to 4.2 million dollars.", "source": "10-K", "quality": 0.9,
     "date": "2026-03-01"},
    {"id": "faq", "text": "Refunds are available within 30 days of purchase.", "source": "support-faq", "quality": 0.6,
     "date": "2020-01-01"},
    {"id": "pol", "text": "The service does not store payment card numbers.", "source": "security-policy"},
]


def _verdicts(answer, **kw):
    return [c["verdict"] for c in verify_claims(answer, EV, **kw)["claims"]]


def test_supported_claim_cites_its_evidence():
    r = verify_claims("Revenue grew 12% in 2025.", EV)
    c = r["claims"][0]
    assert c["verdict"] == "SUPPORTED" and c["citations"] == ["10k"] and 0.5 < c["confidence"] <= 0.95
    assert r["groundedness"] == 1.0 and r["abstain"] is False and r["requires_human_review"] is False


def test_wrong_figure_is_a_contradiction_not_a_pass():
    r = verify_claims("Revenue grew 15% in 2025.", EV)
    assert r["claims"][0]["verdict"] == "CONTRADICTED"
    assert r["abstain"] and r["requires_human_review"]
    assert any("contradict" in x for x in r["reasons"])


def test_flipped_polarity_is_a_contradiction():
    assert _verdicts("The service stores payment card numbers.") == ["CONTRADICTED"]
    assert _verdicts("The service does not store payment card numbers.") == ["SUPPORTED"]


def test_claim_with_no_evidence_is_unsupported_and_abstains():
    r = verify_claims("The company opened a Paris office last spring.", EV)
    assert r["claims"][0]["verdict"] == "UNSUPPORTED" and r["abstain"] is True


def test_stale_evidence_is_flagged_only_when_a_limit_is_set():
    assert _verdicts("Refunds are available within 30 days of purchase.") == ["SUPPORTED"]
    assert _verdicts("Refunds are available within 30 days of purchase.", max_age_days=365,
                     today=__import__("datetime").date(2026, 6, 1)) == ["STALE"]


def test_corroboration_raises_confidence_and_conflict_lowers_it():
    one = [{"id": "a", "text": "The pilot enrolled 240 patients.", "source": "s1", "quality": 0.6}]
    two = one + [{"id": "b", "text": "The pilot enrolled 240 patients in total.", "source": "s2", "quality": 0.6}]
    clash = one + [{"id": "c", "text": "The pilot enrolled 300 patients.", "source": "s3", "quality": 0.6}]
    ask = "The pilot enrolled 240 patients."
    c1 = verify_claims(ask, one)["claims"][0]["confidence"]
    c2 = verify_claims(ask, two)["claims"][0]["confidence"]
    c3 = verify_claims(ask, clash)["claims"][0]
    assert c2 > c1 and c3["confidence"] < c1 and c3["contradicting"] == ["c"]


def test_higher_source_quality_gives_higher_confidence():
    lo = [{"id": "a", "text": "The pilot enrolled 240 patients.", "quality": 0.2}]
    hi = [{"id": "a", "text": "The pilot enrolled 240 patients.", "quality": 1.0}]
    ask = "The pilot enrolled 240 patients."
    assert verify_claims(ask, hi)["claims"][0]["confidence"] > verify_claims(ask, lo)["claims"][0]["confidence"]


def test_critical_output_always_requires_human_review():
    r = verify_claims("Revenue grew 12% in 2025.", EV, critical=True)
    assert r["abstain"] is False and r["requires_human_review"] is True


def test_questions_are_not_claims_and_claims_can_be_supplied():
    assert split_claims("What was the revenue in 2025? Revenue grew 12% in 2025.") == ["Revenue grew 12% in 2025."]
    r = verify_claims(None, EV, claims=["Revenue grew 12% in 2025."])
    assert r["counts"]["SUPPORTED"] == 1


def test_result_states_its_limits():
    r = verify_claims("Revenue grew 12% in 2025.", EV)
    assert "not an entailment model" in r["model_class"] and "paraphrase" in r["limits"]


@pytest.mark.parametrize("answer,evidence,kw", [
    ("Revenue grew.", [], {}), ("Revenue grew.", "nope", {}), ("Revenue grew.", [{"text": ""}], {}),
    ("Revenue grew.", [{"id": "x", "text": "a"}, {"id": "x", "text": "b"}], {}),
    ("Revenue grew.", [{"text": "a", "quality": 2}], {}), ("Revenue grew.", [{"text": "a", "date": "yesterday"}], {}),
    ("ok", EV, {}), ("Revenue grew 12% in 2025.", EV, {"max_age_days": -1}),
    ("Revenue grew 12% in 2025.", EV, {"min_groundedness": 0}),
    (123, EV, {}),
])
def test_invalid_input_raises_value_error(answer, evidence, kw):
    with pytest.raises(ValueError):
        verify_claims(answer, evidence, **kw)


def test_size_limits():
    with pytest.raises(ValueError):
        split_claims("x" * 300_000)
    with pytest.raises(ValueError):
        verify_claims(None, [{"text": "a b c"}] * 201, claims=["one two three"])


# ── router ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,domain", [
    ("Sync my Shopify inventory and refund the order", "commerce"),
    ("Draft a screenplay for the next episode", "media"),
    ("Review the pull request and deploy to github", "dev"),
    ("Check the 5G cell latency on the base station", "telecom"),
    ("Pay the invoice and run payroll", "finance"),
    ("A phishing breach and a new CVE", "cyber"),
    ("Update the roadmap and the critical path milestone", "pmo"),
    ("Guest reservation for the hotel", "hospitality"),
])
def test_router_known_routes(text, domain):
    r = route_domain(text)
    assert r["domain"] == domain and r["confidence"] > 0.5 and r["matched"]


def test_router_unknown_is_general_with_zero_confidence():
    r = route_domain("hello there, how are you")
    assert r["domain"] == "general" and r["confidence"] == 0.0


def test_router_flags_ambiguity_and_reports_alternatives():
    r = route_domain("invoice for the shopify order")
    assert r["alternatives"] and (r["ambiguous"] or r["confidence"] < 0.99)


def test_router_stems_and_is_case_insensitive():
    assert route_domain("INVOICES and EXPENSES")["domain"] == "finance"


@pytest.mark.parametrize("bad", ["", "   ", None, 5, "x" * 30_000])
def test_router_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        route_domain(bad)


# ── governed tools ──────────────────────────────────────────────────────────

@pytest.fixture
def dctx(tenant_a):
    return RequestContext(tenant_id=tenant_a, actor_id="u", actor_label="u", scopes=frozenset({"domain:run"}))


def test_tools_are_registered_and_scope_gated(ctx, dctx):
    reg = get_tool_registry()
    for name in ("domain.verify_claims", "domain.route", "domain.compress_context"):
        assert reg.get(name) is not None
    denied = reg.invoke(ctx, "domain.route", {"text": "invoice"})
    assert denied.state == ResultState.POLICY_DENIED
    ok = reg.invoke(dctx, "domain.route", {"text": "pay the invoice"})
    assert ok.state == ResultState.SUCCESS and ok.data["domain"] == "finance"


def test_verify_tool_validates_and_reports(dctx):
    reg = get_tool_registry()
    ok = reg.invoke(dctx, "domain.verify_claims", {"answer": "Revenue grew 12% in 2025.", "evidence": EV})
    assert ok.state == ResultState.SUCCESS and ok.data["counts"]["SUPPORTED"] == 1
    both = reg.invoke(dctx, "domain.verify_claims", {"answer": "x y z", "claims": ["a b c"], "evidence": EV})
    assert both.state == ResultState.FAILED
    bad = reg.invoke(dctx, "domain.verify_claims", {"answer": "Revenue grew 12% in 2025.", "evidence": [], "extra": 1})
    assert bad.state == ResultState.FAILED


def test_truth_eval_suite_passes(db, admin_ctx):
    from app.mo.evaluation import suites
    from app.mo.evaluation.harness import run_suite
    assert "truth-and-routing" in suites.suite_names()
    res = run_suite(db, admin_ctx, suites.get_suite("truth-and-routing"))
    assert res.state == ResultState.SUCCESS, res.detail
