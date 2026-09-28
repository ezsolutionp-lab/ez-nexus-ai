"""
MO NEXUS OMEGA — Memory system.

Six kinds, with different lifetimes and purposes:

  WORKING     scratch state for the current task; expires in hours
  SHORT_TERM  recent context; expires in days
  LONG_TERM   durable facts and preferences
  SEMANTIC    distilled knowledge (consolidation output)
  EPISODIC    what happened and when (events, outcomes)
  PROCEDURAL  how to do things (learned steps)

Rules that make this safe to run in an enterprise:

  * private to the actor that wrote it unless explicitly shared within the tenant
  * secrets are refused outright; PII is redacted before storage
  * `forget` and `forget_all` are hard deletes and are audited
  * recall ranks by relevance, importance and recency — and never returns expired items
  * consolidation is real: it promotes frequently-used SHORT_TERM items to LONG_TERM and
    folds old EPISODIC runs into an extractive SEMANTIC summary
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import MemoryRecord
from ..errors import MoResult, ResultState
from ..guards import pii
from ..knowledge import ranking

KINDS = ("WORKING", "SHORT_TERM", "LONG_TERM", "SEMANTIC", "EPISODIC", "PROCEDURAL")
DEFAULT_TTL = {
    "WORKING": timedelta(hours=8),
    "SHORT_TERM": timedelta(days=7),
    "LONG_TERM": None,
    "SEMANTIC": None,
    "EPISODIC": timedelta(days=365),
    "PROCEDURAL": None,
}
RECENCY_HALF_LIFE_DAYS = 30.0
PROMOTE_AFTER_ACCESSES = 3
MAX_CONTENT_CHARS = 4000


class MemoryStore:
    def __init__(self, db: Session, ctx: RequestContext):
        self.db, self.ctx = db, ctx
        self.embedder = ranking.local_embedder()

    def _visible(self):
        """Own records, plus shared records from the same tenant. Expired records are excluded."""
        now = datetime.utcnow()
        return (self.db.query(MemoryRecord)
                .filter(MemoryRecord.tenant_id == self.ctx.tenant_id,
                        or_(MemoryRecord.actor_id == self.ctx.actor_id, MemoryRecord.shared.is_(True)),
                        or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now)))

    def remember(self, kind: str, content: str, *, key: Optional[str] = None, importance: float = 0.5,
                 shared: bool = False, tags: Optional[list[str]] = None,
                 ttl: Optional[timedelta] = None) -> MoResult:
        kind = kind.upper()
        if kind not in KINDS:
            return MoResult(ResultState.FAILED, f"Unknown memory kind '{kind}'. Use one of {', '.join(KINDS)}.")
        if not content or not content.strip():
            return MoResult(ResultState.FAILED, "Nothing to remember: content is empty.")
        if len(content) > MAX_CONTENT_CHARS:
            return MoResult(ResultState.FAILED, f"Memory exceeds {MAX_CONTENT_CHARS} characters.")
        importance = min(1.0, max(0.0, importance))

        clean, findings = pii.redact(content)
        secrets = [f for f in findings if f.severity == "CRITICAL"]
        if secrets:
            chain.record(self.db, self.ctx, action="memory.refused", result_state=ResultState.POLICY_DENIED,
                         detail="secret in memory content", payload={"kinds": sorted({f.kind for f in secrets})})
            return MoResult(ResultState.POLICY_DENIED,
                            "Refusing to remember this: it contains what looks like a secret "
                            f"({', '.join(sorted({f.kind for f in secrets}))}).")
        if shared and findings:
            return MoResult(ResultState.POLICY_DENIED,
                            "Personal data cannot be stored in shared memory. Store it privately or remove it.",
                            meta={"kinds": sorted({f.kind for f in findings})})

        # Upsert by key: the same actor updating a named memory replaces it rather than duplicating.
        existing = None
        if key:
            existing = (self.db.query(MemoryRecord)
                        .filter(MemoryRecord.tenant_id == self.ctx.tenant_id,
                                MemoryRecord.actor_id == self.ctx.actor_id,
                                MemoryRecord.kind == kind, MemoryRecord.key == key).first())
        ttl = ttl if ttl is not None else DEFAULT_TTL[kind]
        expires = datetime.utcnow() + ttl if ttl else None
        rec = existing or MemoryRecord(tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id,
                                       actor_id=self.ctx.actor_id, kind=kind, key=key)
        rec.content, rec.importance, rec.shared = clean, importance, shared
        rec.classification = self.ctx.data_classification
        rec.tags_json = json.dumps(sorted(set(tags or [])))
        rec.terms_json = json.dumps(ranking.terms(clean))
        rec.vector_json = json.dumps({str(k): round(v, 5) for k, v in self.embedder.embed(clean).items()})
        rec.expires_at = expires
        rec.redactions_json = json.dumps(sorted({f.kind for f in findings}))
        if existing is None:
            self.db.add(rec)
        self.db.flush()
        chain.record(self.db, self.ctx, action="memory.remember", result_state=ResultState.SUCCESS,
                     resource_type="memory", resource_id=rec.id, detail=kind, payload={"kind": kind, "key": key})
        return MoResult.ok({"id": rec.id, "kind": kind, "updated": existing is not None,
                            "redactions": sorted({f.kind for f in findings}),
                            "expires_at": expires.isoformat() if expires else None})

    def recall(self, query: str, *, kinds: Optional[list[str]] = None, top_k: int = 5,
               touch: bool = True) -> list[dict[str, Any]]:
        q = self._visible()
        if kinds:
            q = q.filter(MemoryRecord.kind.in_([k.upper() for k in kinds]))
        recs = q.all()
        if not recs or not query.strip():
            return []
        qterms = ranking.terms(query)
        sparse = ranking.bm25_scores(qterms, [json.loads(r.terms_json) for r in recs])
        qvec = self.embedder.embed(query)
        dense = [ranking.cosine(qvec, {int(k): v for k, v in json.loads(r.vector_json).items()}) for r in recs]
        rel = [0.6 * a + 0.4 * b for a, b in zip(ranking.normalise(sparse), ranking.normalise(dense))]
        now = datetime.utcnow()
        scored = []
        for r, relevance in zip(recs, rel):
            if relevance <= 0.05:
                continue
            age_days = max(0.0, (now - (r.last_accessed_at or r.created_at)).total_seconds() / 86400)
            recency = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
            score = 0.65 * relevance + 0.2 * r.importance + 0.15 * recency
            scored.append((score, relevance, recency, r))
        scored.sort(key=lambda t: -t[0])
        out = []
        for score, relevance, recency, r in scored[:top_k]:
            if touch:
                r.access_count += 1
                r.last_accessed_at = now
            out.append({"id": r.id, "kind": r.kind, "key": r.key, "content": r.content,
                        "importance": r.importance, "shared": r.shared, "score": round(score, 4),
                        "relevance": round(relevance, 3), "recency": round(recency, 3),
                        "owner": r.actor_id, "tags": json.loads(r.tags_json)})
        self.db.flush()
        return out

    def get_by_key(self, kind: str, key: str) -> Optional[dict[str, Any]]:
        r = self._visible().filter(MemoryRecord.kind == kind.upper(), MemoryRecord.key == key).first()
        return None if r is None else {"id": r.id, "kind": r.kind, "key": r.key, "content": r.content}

    def forget(self, memory_id: str) -> MoResult:
        """Hard delete. Only the owner may forget; a shared item is still only the owner's to remove."""
        rec = self.db.get(MemoryRecord, memory_id)
        if rec is None or rec.tenant_id != self.ctx.tenant_id or (
                rec.actor_id != self.ctx.actor_id and not self.ctx.is_admin):
            return MoResult(ResultState.FAILED, "No such memory.")
        self.db.delete(rec)
        chain.record(self.db, self.ctx, action="memory.forget", result_state=ResultState.SUCCESS,
                     resource_type="memory", resource_id=memory_id)
        self.db.flush()
        return MoResult.ok({"forgotten": memory_id})

    def forget_all(self) -> MoResult:
        """Right-to-erasure for the calling actor within their tenant."""
        n = (self.db.query(MemoryRecord)
             .filter(MemoryRecord.tenant_id == self.ctx.tenant_id, MemoryRecord.actor_id == self.ctx.actor_id)
             .delete())
        chain.record(self.db, self.ctx, action="memory.erase", result_state=ResultState.SUCCESS,
                     detail=f"{n} memories erased")
        self.db.flush()
        return MoResult.ok({"erased": n})

    def consolidate(self, *, episodic_older_than: timedelta = timedelta(days=7),
                    min_episodes: int = 3) -> MoResult:
        """Promote hot SHORT_TERM items; expire dead ones; fold old EPISODIC runs into SEMANTIC."""
        now = datetime.utcnow()
        own = self.db.query(MemoryRecord).filter(MemoryRecord.tenant_id == self.ctx.tenant_id,
                                                 MemoryRecord.actor_id == self.ctx.actor_id)
        promoted = 0
        for r in own.filter(MemoryRecord.kind == "SHORT_TERM").all():
            if r.access_count >= PROMOTE_AFTER_ACCESSES:
                r.kind, r.expires_at = "LONG_TERM", None
                promoted += 1
        expired = own.filter(MemoryRecord.expires_at.isnot(None), MemoryRecord.expires_at <= now).delete()

        old = (own.filter(MemoryRecord.kind == "EPISODIC",
                          MemoryRecord.created_at <= now - episodic_older_than)
               .order_by(MemoryRecord.created_at).all())
        summarised = 0
        if len(old) >= min_episodes:
            digest = _extractive_digest([r.content for r in old])
            self.remember("SEMANTIC", digest, key=f"digest:{now:%Y%m%d}", importance=0.6,
                          tags=["consolidated"])
            for r in old:
                self.db.delete(r)
            summarised = len(old)
        chain.record(self.db, self.ctx, action="memory.consolidate", result_state=ResultState.SUCCESS,
                     payload={"promoted": promoted, "expired": expired, "summarised": summarised})
        self.db.flush()
        return MoResult.ok({"promoted": promoted, "expired": expired, "episodes_summarised": summarised})

    def stats(self) -> dict[str, Any]:
        by_kind = {k: 0 for k in KINDS}
        for r in self._visible().all():
            by_kind[r.kind] += 1
        return {"by_kind": by_kind, "total": sum(by_kind.values()), "embedder": self.embedder.name}


def _extractive_digest(items: list[str], max_sentences: int = 5) -> str:
    """Pick the most representative sentences by centrality over term frequency. No model involved."""
    sentences = []
    for text in items:
        sentences += [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
    freq: dict[str, int] = {}
    for s in sentences:
        for t in set(ranking.terms(s)):
            freq[t] = freq.get(t, 0) + 1
    def weight(s: str) -> float:
        ts = set(ranking.terms(s))
        return sum(freq[t] for t in ts) / math.sqrt(len(ts) or 1)
    top = sorted(sentences, key=weight, reverse=True)[:max_sentences]
    keep = [s for s in sentences if s in top]
    return ". ".join(s.rstrip(".") for s in keep) + "."
