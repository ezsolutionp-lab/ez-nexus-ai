"""Memory: kinds, privacy, redaction, recall ranking, erasure and consolidation."""

from datetime import datetime, timedelta

import pytest

from app.mo.context import RequestContext
from app.mo.db import MemoryRecord
from app.mo.errors import ResultState
from app.mo.memory.store import KINDS, MemoryStore

pytestmark = pytest.mark.regression


def actor(tenant, name, **kw):
    return RequestContext(tenant_id=tenant, actor_id=name, scopes=frozenset(), **kw)


def test_all_six_kinds_are_supported(db, ctx):
    m = MemoryStore(db, ctx)
    for kind in KINDS:
        assert m.remember(kind, f"a {kind.lower()} note about invoices").state.is_success
    assert m.stats()["total"] == 6


def test_unknown_kind_and_empty_content_fail(db, ctx):
    m = MemoryStore(db, ctx)
    assert m.remember("DREAM", "x").state is ResultState.FAILED
    assert m.remember("LONG_TERM", "   ").state is ResultState.FAILED


def test_secrets_are_refused_and_never_stored(db, ctx):
    m = MemoryStore(db, ctx)
    res = m.remember("LONG_TERM", "the aws key is AKIAABCDEFGHIJKLMNOP remember it")
    assert res.state is ResultState.POLICY_DENIED
    assert db.query(MemoryRecord).count() == 0


def test_pii_is_redacted_in_private_memory_and_refused_in_shared(db, ctx):
    m = MemoryStore(db, ctx)
    ok = m.remember("LONG_TERM", "Customer email is jo@example.com prefers mornings")
    assert ok.state.is_success and ok.data["redactions"] == ["EMAIL"]
    stored = db.get(MemoryRecord, ok.data["id"])
    assert "jo@example.com" not in stored.content
    denied = m.remember("LONG_TERM", "Contact jo@example.com", shared=True)
    assert denied.state is ResultState.POLICY_DENIED


def test_recall_ranks_relevant_first(db, ctx):
    m = MemoryStore(db, ctx)
    m.remember("LONG_TERM", "Customer Rivera prefers appointments on Tuesday mornings")
    m.remember("LONG_TERM", "The warehouse forklift needs servicing every quarter")
    hits = m.recall("when does Rivera like appointments")
    assert hits and "Rivera" in hits[0]["content"]
    assert all(h["score"] > 0 for h in hits)


def test_memory_is_private_to_the_actor_unless_shared(db, tenant_a):
    alice, bob = actor(tenant_a, "alice"), actor(tenant_a, "bob")
    MemoryStore(db, alice).remember("LONG_TERM", "Alice's private plan is the falcon project")
    MemoryStore(db, alice).remember("LONG_TERM", "Team standup happens at nine daily", shared=True)
    assert MemoryStore(db, bob).recall("falcon project plan") == []
    assert MemoryStore(db, bob).recall("team standup")


def test_tenant_isolation_even_for_shared_memory(db, tenant_a, tenant_b):
    MemoryStore(db, actor(tenant_a, "alice")).remember("LONG_TERM", "Shared standup at nine", shared=True)
    assert MemoryStore(db, actor(tenant_b, "alice")).recall("standup") == []


def test_expired_memories_are_not_recalled(db, ctx):
    m = MemoryStore(db, ctx)
    m.remember("WORKING", "temporary scratch about widgets", ttl=timedelta(seconds=-1))
    assert m.recall("scratch widgets") == []


def test_keyed_memory_is_updated_not_duplicated(db, ctx):
    m = MemoryStore(db, ctx)
    m.remember("LONG_TERM", "Preferred language is English", key="lang")
    second = m.remember("LONG_TERM", "Preferred language is Spanish", key="lang")
    assert second.data["updated"] is True
    assert db.query(MemoryRecord).count() == 1
    assert "Spanish" in m.get_by_key("LONG_TERM", "lang")["content"]


def test_forget_is_a_hard_delete_and_owner_only(db, tenant_a):
    alice, bob = actor(tenant_a, "alice"), actor(tenant_a, "bob")
    mid = MemoryStore(db, alice).remember("LONG_TERM", "Alice shared note", shared=True).data["id"]
    assert MemoryStore(db, bob).forget(mid).state is ResultState.FAILED
    assert MemoryStore(db, alice).forget(mid).state.is_success
    assert db.get(MemoryRecord, mid) is None


def test_erasure_removes_only_the_callers_memories(db, tenant_a):
    alice, bob = actor(tenant_a, "alice"), actor(tenant_a, "bob")
    for i in range(3):
        MemoryStore(db, alice).remember("LONG_TERM", f"alice memory number {i}")
    MemoryStore(db, bob).remember("LONG_TERM", "bob memory survives")
    assert MemoryStore(db, alice).forget_all().data["erased"] == 3
    assert db.query(MemoryRecord).count() == 1


def test_consolidation_promotes_hot_short_term_items(db, ctx):
    m = MemoryStore(db, ctx)
    mid = m.remember("SHORT_TERM", "Client prefers invoices sent on Fridays").data["id"]
    for _ in range(3):
        m.recall("invoices Fridays")
    result = m.consolidate()
    assert result.data["promoted"] == 1
    rec = db.get(MemoryRecord, mid)
    assert rec.kind == "LONG_TERM" and rec.expires_at is None


def test_consolidation_folds_old_episodes_into_a_semantic_digest(db, ctx):
    m = MemoryStore(db, ctx)
    for text in ("Pipe repair at Elm Street took two hours. Customer paid by card.",
                 "Pipe repair at Oak Avenue took three hours. Customer paid by card.",
                 "Pipe repair at Main Road took one hour. Customer paid by cash."):
        rid = m.remember("EPISODIC", text).data["id"]
        db.get(MemoryRecord, rid).created_at = datetime.utcnow() - timedelta(days=30)
    db.flush()
    res = m.consolidate()
    assert res.data["episodes_summarised"] == 3
    assert m.stats()["by_kind"]["EPISODIC"] == 0
    digest = m.recall("pipe repair", kinds=["SEMANTIC"])
    assert digest and "consolidated" in digest[0]["tags"]


def test_every_memory_operation_is_audited(db, ctx):
    from app.mo.audit import chain
    m = MemoryStore(db, ctx)
    mid = m.remember("LONG_TERM", "audited note").data["id"]
    m.forget(mid)
    assert chain.tenant_event_count(db, ctx.tenant_id) == 2
    assert chain.verify_chain(db, ctx.tenant_id)["valid"]
