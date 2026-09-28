"""Context compression and the semantic cache."""

import pytest

from app.mo.modelfabric.context import ContextPolicy, SemanticCache, compress, estimate_tokens, should_summarize

pytestmark = pytest.mark.builder

POLICY = ContextPolicy(max_tokens=8000, summarize_after_tokens=3000, keep_recent_turns=4,
                       retrieval_budget_tokens=1000, response_budget_tokens=500)


def _convo(n=60):
    msgs = [{"role": "system", "content": "You are MO."}]
    for i in range(n):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant",
                     "content": f"Turn {i}. The budget for project Alpha is {i * 100} dollars. " * 40})
    return msgs


def test_policy_validation():
    ContextPolicy()
    for kw in ({"max_tokens": -1}, {"summarize_after_tokens": 10**6}, {"keep_recent_turns": True},
               {"retrieval_budget_tokens": 60_000, "response_budget_tokens": 10_000}):
        with pytest.raises(ValueError):
            ContextPolicy(**kw)


def test_should_summarize_threshold():
    p = ContextPolicy()
    assert not should_summarize(p.summarize_after_tokens - 1, p) and should_summarize(p.summarize_after_tokens, p)


def test_short_conversation_is_untouched_and_not_mutated():
    msgs = _convo(2)
    snapshot = [dict(m) for m in msgs]
    r = compress(msgs, POLICY)
    assert r["compressed"] is False and r["messages"] == msgs and msgs == snapshot


def test_long_conversation_shrinks_and_keeps_system_and_recent_turns():
    msgs = _convo()
    r = compress(msgs, POLICY)
    assert r["compressed"] and r["tokens_after"] < r["tokens_before"] / 4
    assert r["messages"][0] == msgs[0]
    assert r["messages"][-4:] == msgs[-4:]
    assert r["dropped_turns"] == len(msgs) - 1 - 4
    assert r["summary_is_extractive"] is True
    assert r["tokens_after"] <= POLICY.max_tokens - POLICY.retrieval_budget_tokens - POLICY.response_budget_tokens


def test_summary_only_contains_sentences_from_the_original():
    msgs = _convo(30)
    r = compress(msgs, POLICY)
    summary = next(m["content"] for m in r["messages"] if m["content"].startswith("Summary of earlier"))
    body = summary.split(": ", 1)[1]
    originals = " ".join(m["content"] for m in msgs)
    for sentence in [s.strip() for s in body.split(". ") if s.strip()][:5]:
        assert sentence.rstrip(".") in originals


@pytest.mark.parametrize("bad", ["x", [{"role": "user"}], [{"content": "x", "role": 1}], [1]])
def test_compress_rejects_malformed_messages(bad):
    with pytest.raises(ValueError):
        compress(bad, POLICY)


def test_estimate_tokens():
    assert estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2


# ── cache ───────────────────────────────────────────────────────────────────

def test_cache_hits_near_identical_question_only_within_tenant_and_namespace():
    c = SemanticCache()
    assert c.put("t1", "What is the refund window for orders?", "30 days.")
    assert c.get("t1", "what is the refund window for orders")["answer"] == "30 days."
    assert c.get("t2", "What is the refund window for orders?") is None
    assert c.get("t1", "What is the refund window for orders?", namespace="other") is None
    assert c.get("t1", "How do I reset my password?") is None


def test_cache_refuses_secrets_and_pii():
    c = SemanticCache()
    assert c.put("t1", "my ssn is 123-45-6789, what is my status", "ok") is False
    assert c.put("t1", "what is my status", "your ssn is 123-45-6789") is False
    assert c.stats()["entries"] == 0


def test_cache_expires_and_is_bounded():
    c = SemanticCache(ttl_seconds=10, max_entries=2)
    c.put("t", "alpha question about invoices", "a", now=0)
    assert c.get("t", "alpha question about invoices", now=5) is not None
    assert c.get("t", "alpha question about invoices", now=20) is None
    for i, q in enumerate(["first distinct topic about shipping", "second distinct topic about payroll",
                           "third distinct topic about roadmap"]):
        c.put("t", q, str(i), now=100)
    assert c.stats()["entries"] == 2


def test_cache_stats_and_clear_by_tenant():
    c = SemanticCache()
    c.put("a", "one question about hotels", "x"); c.put("b", "one question about hotels", "y")
    c.get("a", "one question about hotels"); c.get("a", "totally different words entirely")
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["hit_rate"] == 0.5 and "hashed" in s["embedder"]
    assert c.clear("a") == 1 and c.stats()["entries"] == 1


def test_cache_validation():
    for kw in ({"threshold": 0.1}, {"ttl_seconds": 0}, {"max_entries": 0}):
        with pytest.raises(ValueError):
            SemanticCache(**kw)
    with pytest.raises(ValueError):
        SemanticCache().put("", "q", "a")
