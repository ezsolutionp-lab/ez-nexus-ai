"""
MO NEXUS OMEGA — Enterprise knowledge (permission-aware hybrid RAG).

Pipeline for a question:

  1. PERMISSION FILTER  tenant, classification ceiling and allowed scopes are applied
                        to the candidate set *before* any scoring. A chunk the caller may
                        not read never influences a ranking, a citation or an answer.
  2. HYBRID RETRIEVAL   BM25 + local dense cosine + entity graph, fused by RRF.
  3. CORRECTIVE CHECK   if the best evidence is too weak the answer is BLOCKED with the
                        reason, rather than a confident guess.
  4. GROUNDED ANSWER    extractive when no model is configured; with a model, the answer
                        is verified claim-by-claim against the retrieved evidence and
                        unsupported claims are reported (or the answer is withheld).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..errors import MoError, MoResult, ResultState
from ..db import KnowledgeChunk, KnowledgeDoc
from ..guards import grounding
from ..guards.pipeline import guard_input, guard_output
from ..modelfabric.router import ModelRequest, get_router
from . import ranking

CLASSIFICATION_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}
CHUNK_WORDS = 90
CHUNK_OVERLAP = 20
MAX_DOC_CHARS = 500_000
MIN_EVIDENCE_SCORE = 0.30          # normalised top-hit strength below which we refuse to answer
MIN_LEXICAL_COVERAGE = 0.34        # share of query terms the top chunk must actually contain


def chunk_text(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sentence-aware windows: sentences are packed to ~`size` words with `overlap` carried over."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = len(sentence.split())
        if current and count + words > size:
            chunks.append(" ".join(current))
            carried: list[str] = []
            carry_words = 0
            for prev in reversed(current):
                w = len(prev.split())
                if carry_words + w > overlap:
                    break
                carried.insert(0, prev)
                carry_words += w
            current, count = carried, carry_words
        current.append(sentence)
        count += words
    if current:
        chunks.append(" ".join(current))
    return chunks


def _rank(classification: str) -> int:
    return CLASSIFICATION_RANK.get(classification.upper(), 3)   # unknown = most restrictive


def can_read(ctx: RequestContext, doc: KnowledgeDoc) -> bool:
    if doc.tenant_id != ctx.tenant_id:
        return False
    if _rank(doc.classification) > _rank(ctx.data_classification):
        return False
    scopes = json.loads(doc.allowed_scopes_json or "[]")
    if scopes and not (ctx.is_admin or set(scopes) & set(ctx.scopes)):
        return False
    return True


class KnowledgeService:
    def __init__(self, db: Session, ctx: RequestContext):
        self.db, self.ctx = db, ctx
        self.embedder = ranking.get_embedder()

    # ── ingest ──────────────────────────────────────────────────────────────

    def ingest(self, title: str, text: str, *, source: Optional[str] = None,
               classification: str = "INTERNAL", allowed_scopes: Optional[list[str]] = None) -> MoResult:
        if classification.upper() not in CLASSIFICATION_RANK:
            return MoResult(ResultState.FAILED, f"Unknown classification '{classification}'.")
        classification = classification.upper()
        if not text or not text.strip():
            return MoResult(ResultState.FAILED, "Document text is empty.")
        if len(text) > MAX_DOC_CHARS:
            return MoResult(ResultState.FAILED, f"Document exceeds {MAX_DOC_CHARS} characters.")
        if _rank(classification) > _rank(self.ctx.data_classification):
            return MoResult(ResultState.POLICY_DENIED,
                            f"This context is limited to {self.ctx.data_classification} and cannot "
                            f"store {classification} material.")

        gate = guard_input(text, self.ctx, self.db)
        if gate.blocked:
            return gate.to_result()
        clean = gate.text        # secrets and PII never enter the index in the clear

        digest = hashlib.sha256(clean.encode()).hexdigest()
        existing = (self.db.query(KnowledgeDoc)
                    .filter(KnowledgeDoc.tenant_id == self.ctx.tenant_id,
                            KnowledgeDoc.content_hash == digest).first())
        if existing:
            return MoResult(ResultState.BLOCKED,
                            "An identical document is already indexed for this tenant.",
                            meta={"doc_id": existing.id, "duplicate": True})

        pieces = chunk_text(clean)
        doc = KnowledgeDoc(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, title=title[:300],
            source=(source or "")[:500] or None, classification=classification,
            allowed_scopes_json=json.dumps(sorted(set(allowed_scopes or []))),
            content_hash=digest, chunk_count=len(pieces), embedder=self.embedder.name,
        )
        self.db.add(doc)
        self.db.flush()
        for seq, piece in enumerate(pieces):
            self.db.add(KnowledgeChunk(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, doc_id=doc.id, seq=seq,
                text=piece, terms_json=json.dumps(ranking.terms(piece)),
                vector_json=json.dumps({str(k): round(v, 5) for k, v in self.embedder.embed(piece).items()}),
                entities_json=json.dumps(sorted(ranking.entities(piece))),
            ))
        chain.record(self.db, self.ctx, action="knowledge.ingest", result_state=ResultState.SUCCESS,
                     resource_type="knowledge_doc", resource_id=doc.id,
                     detail=f"{len(pieces)} chunks", payload={"title": title, "classification": classification})
        self.db.flush()
        return MoResult.ok({"doc_id": doc.id, "chunks": len(pieces), "embedder": self.embedder.name,
                            "redactions": [f.kind for f in gate.findings]})

    def delete(self, doc_id: str) -> MoResult:
        doc = self.db.get(KnowledgeDoc, doc_id)
        if doc is None or not can_read(self.ctx, doc):
            return MoResult(ResultState.FAILED, "No such document.")     # never confirm existence
        self.db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).delete()
        self.db.delete(doc)
        chain.record(self.db, self.ctx, action="knowledge.delete", result_state=ResultState.SUCCESS,
                     resource_type="knowledge_doc", resource_id=doc_id)
        self.db.flush()
        return MoResult.ok({"deleted": doc_id})

    def list_docs(self) -> list[dict[str, Any]]:
        docs = (self.db.query(KnowledgeDoc).filter(KnowledgeDoc.tenant_id == self.ctx.tenant_id)
                .order_by(KnowledgeDoc.created_at.desc()).all())
        return [{"id": d.id, "title": d.title, "source": d.source, "classification": d.classification,
                 "chunks": d.chunk_count, "embedder": d.embedder}
                for d in docs if can_read(self.ctx, d)]

    # ── retrieval ───────────────────────────────────────────────────────────

    def _candidates(self) -> list[tuple[KnowledgeChunk, KnowledgeDoc]]:
        """Only chunks the caller may read. This runs before any scoring."""
        rows = (self.db.query(KnowledgeChunk, KnowledgeDoc)
                .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
                .filter(KnowledgeChunk.tenant_id == self.ctx.tenant_id,
                        KnowledgeDoc.tenant_id == self.ctx.tenant_id).all())
        return [(c, d) for c, d in rows if can_read(self.ctx, d)]

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        cands = self._candidates()
        if not cands or not query.strip():
            return []
        qterms = ranking.terms(query)
        docs_terms = [json.loads(c.terms_json) for c, _ in cands]
        sparse = ranking.bm25_scores(qterms, docs_terms)
        qvec = self.embedder.embed(query)
        dense = [ranking.cosine(qvec, {int(k): v for k, v in json.loads(c.vector_json).items()})
                 for c, _ in cands]
        graph = ranking.graph_scores(ranking.entities(query), [set(json.loads(c.entities_json)) for c, _ in cands])
        fused = ranking.reciprocal_rank_fusion(
            [ranking.rank_of(sparse), ranking.rank_of(dense), ranking.rank_of(graph)])
        order = sorted(fused, key=lambda i: -fused[i])[:top_k]
        nsparse, ndense = ranking.normalise(sparse), ranking.normalise(dense)
        qset = set(qterms)
        hits = []
        for i in order:
            chunk, doc = cands[i]
            coverage = len(qset & set(docs_terms[i])) / len(qset) if qset else 0.0
            hits.append({
                "chunk_id": chunk.id, "doc_id": doc.id, "title": doc.title, "seq": chunk.seq,
                "text": chunk.text, "classification": doc.classification,
                "fused": round(fused[i], 5), "bm25": round(nsparse[i], 3), "dense": round(ndense[i], 3),
                "graph": round(graph[i], 3), "coverage": round(coverage, 3),
                # relevance blends lexical coverage with the strongest single signal
                "relevance": round(0.6 * coverage + 0.4 * max(nsparse[i], ndense[i]), 3),
            })
        return hits

    # ── answer ──────────────────────────────────────────────────────────────

    def answer(self, question: str, *, top_k: int = 4) -> MoResult:
        gate = guard_input(question, self.ctx, self.db)
        if gate.blocked:
            return gate.to_result()
        hits = self.search(gate.text, top_k=top_k)
        if not hits:
            return MoResult(ResultState.BLOCKED, "No accessible knowledge matches this question.",
                            meta={"citations": []})
        best = hits[0]
        if best["relevance"] < MIN_EVIDENCE_SCORE or best["coverage"] < MIN_LEXICAL_COVERAGE:
            return MoResult(ResultState.BLOCKED,
                            "The knowledge base does not contain enough evidence to answer this reliably.",
                            meta={"best_relevance": best["relevance"], "best_coverage": best["coverage"],
                                  "citations": []})
        citations = [{"chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "title": h["title"],
                      "seq": h["seq"], "relevance": h["relevance"]} for h in hits]
        evidence = [(h["chunk_id"], h["text"]) for h in hits]

        router = get_router()
        if not router.is_configured:
            sentences = _best_sentences(gate.text, best["text"])
            text = guard_output(" ".join(sentences), self.ctx, self.db).text
            return MoResult.ok({"answer": text, "mode": "EXTRACTIVE", "citations": citations[:1]},
                               model_used=False)

        prompt = ("Answer using ONLY the numbered evidence. If the evidence is insufficient say so.\n\n"
                  + "\n\n".join(f"[{n}] {t}" for n, (_, t) in enumerate(evidence, 1))
                  + f"\n\nQuestion: {gate.text}")
        result = router.complete(ModelRequest(
            prompt=prompt, system="You are a careful enterprise assistant. Never state facts not in the evidence.",
            capability="reasoning", data_classification=best["classification"], max_tokens=600))
        if not result.state.is_success:
            return result
        out = guard_output(result.data["text"], self.ctx, self.db).text
        report = grounding.verify_claims(out, evidence)
        if report.grounded_ratio < 0.6:
            return MoResult(ResultState.BLOCKED,
                            "The drafted answer was not supported by the retrieved evidence and was withheld.",
                            meta={"grounded_ratio": report.grounded_ratio, "unsupported": [c.to_dict() for c in report.unsupported[:5]]})
        return MoResult.ok({"answer": out, "mode": "MODEL_VERIFIED", "citations": citations},
                           grounded_ratio=report.grounded_ratio, unsupported=[c.to_dict() for c in report.unsupported])


def _best_sentences(question: str, text: str, n: int = 2) -> list[str]:
    q = set(ranking.terms(question))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    scored = sorted(sentences, key=lambda s: -len(q & set(ranking.terms(s))))
    picked = [s for s in scored[:n] if q & set(ranking.terms(s))] or scored[:1]
    return [s for s in sentences if s in picked]
