"""
MO NEXUS OMEGA — Retrieval primitives shared by knowledge search and memory recall.

Three independent signals, fused with reciprocal-rank fusion:

  sparse   BM25 over stemmed terms.
  dense    cosine over feature-hashed word-unigram, bigram and character-trigram
           vectors. This is a *local* embedding: it captures morphology and phrase
           overlap, not neural semantics. It sits behind `Embedder` so a provider
           embedding can replace it; until one is configured the capability
           reports the local embedder by name rather than implying more.
  graph    entity co-occurrence: chunks that share entities with the query, or
           with chunks that do, are pulled in one hop.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from typing import Iterable, Optional, Sequence

from ..guards.grounding import tokens as content_tokens

RRF_K = 60
DENSE_DIM = 1024
BM25_K1 = 1.5
BM25_B = 0.75


def stem(word: str) -> str:
    """Conservative suffix stripper. Deliberately small: over-stemming merges unrelated words."""
    for suffix, min_len in (("ations", 6), ("ation", 6), ("ingly", 6), ("ing", 5), ("edly", 6), ("ies", 5),
                            ("ied", 5), ("ed", 4), ("es", 4), ("ly", 5), ("s", 4)):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and len(word) >= min_len:
            base = word[: -len(suffix)]
            return base + "y" if suffix in ("ies", "ied") else base
    return word


def terms(text: str) -> list[str]:
    return [stem(t) for t in content_tokens(text)]


# ── sparse ───────────────────────────────────────────────────────────────────

def bm25_scores(query_terms: Sequence[str], docs: Sequence[Sequence[str]]) -> list[float]:
    """BM25 for `query_terms` over already-tokenised docs. Statistics come from `docs` only."""
    n = len(docs)
    if n == 0 or not query_terms:
        return [0.0] * n
    avgdl = (sum(len(d) for d in docs) / n) or 1.0
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for q in set(query_terms):
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            f = tf[q]
            s += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * len(d) / avgdl))
        scores.append(s)
    return scores


# ── dense ────────────────────────────────────────────────────────────────────

class Embedder:
    name = "abstract"
    neural = False

    def embed(self, text: str) -> dict[int, float]:
        raise NotImplementedError


class HashedNgramEmbedder(Embedder):
    """Deterministic, dependency-free, tenant-safe. Not a neural model."""

    name = "local-hashed-ngram"
    neural = False

    @staticmethod
    def _bucket(feature: str) -> tuple[int, float]:
        h = 2166136261
        for ch in feature:
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
        return h % DENSE_DIM, 1.0 if (h >> 31) & 1 else -1.0

    def embed(self, text: str) -> dict[int, float]:
        words = terms(text)
        feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.8) for a, b in zip(words, words[1:])]
        for w in words:
            padded = f"^{w}$"
            feats += [(f"c:{padded[i:i + 3]}", 0.3) for i in range(len(padded) - 2)]
        vec: dict[int, float] = defaultdict(float)
        for feat, weight in feats:
            idx, sign = self._bucket(feat)
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {i: v / norm for i, v in vec.items()}


def cosine(a: dict, b: dict) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(i, 0.0) for i, v in a.items())


# ── graph ────────────────────────────────────────────────────────────────────

_ENTITY = re.compile(r"\b(?:[A-Z][a-zA-Z0-9&\-]+(?:\s+[A-Z][a-zA-Z0-9&\-]+)+|[A-Z]{2,}[A-Z0-9\-]*|[A-Z][a-z]{2,})\b")
_SENTENCE_START_STOP = {"the", "this", "that", "these", "those", "there", "here", "what", "when", "where", "which",
                        "who", "how", "why", "for", "and", "but", "our", "your", "their", "its"}


def entities(text: str) -> set[str]:
    """Capitalised phrases, acronyms and proper nouns, lower-cased. Sentence-initial stopwords are dropped."""
    out = set()
    for m in _ENTITY.finditer(text):
        e = m.group().strip()
        if e.lower() in _SENTENCE_START_STOP:
            continue
        out.add(e.lower())
    return out


def graph_scores(query_entities: set[str], chunk_entities: Sequence[set[str]]) -> list[float]:
    """Direct entity match scores 1.0 each; one-hop neighbours through a shared third entity score 0.35."""
    n = len(chunk_entities)
    direct = [float(len(query_entities & ents)) for ents in chunk_entities]
    if not any(direct):
        return [0.0] * n
    seed_entities: set[str] = set()
    for d, ents in zip(direct, chunk_entities):
        if d:
            seed_entities |= ents
    seed_entities -= query_entities
    scores = list(direct)
    for i, ents in enumerate(chunk_entities):
        if not direct[i] and ents & seed_entities:
            scores[i] = 0.35 * len(ents & seed_entities) / (1 + len(seed_entities) ** 0.5)
    return scores


# ── fusion ───────────────────────────────────────────────────────────────────

def rank_of(scores: Sequence[float]) -> dict[int, int]:
    """Index → 1-based rank for strictly positive scores only; a zero score is not a vote."""
    order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: -scores[i])
    return {i: r for r, i in enumerate(order, start=1)}


def reciprocal_rank_fusion(rankings: Iterable[dict[int, int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for idx, r in ranking.items():
            fused[idx] += 1.0 / (k + r)
    return dict(fused)


def normalise(scores: Sequence[float]) -> list[float]:
    top = max(scores) if scores else 0.0
    return [s / top if top > 0 else 0.0 for s in scores]


class ProviderEmbedder(Embedder):
    """
    A neural embedding model behind an OpenAI-compatible /embeddings endpoint. Configured with
    MO_EMBEDDINGS_PROVIDER=openai plus OPENAI_API_KEY (or MO_EMBEDDINGS_API_KEY); MO_EMBEDDINGS_BASE_URL and
    MO_EMBEDDINGS_MODEL override the defaults. Errors raise EmbeddingError; nothing is ever faked.
    """

    neural = True
    MAX_BATCH = 64

    def __init__(self, api_key: str, base_url: str, model: str, transport=None, timeout: float = 20.0) -> None:
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.transport, self.timeout = transport, timeout
        self.name = f"provider:{model}"

    def embed_many(self, texts: Sequence[str]) -> list[dict[int, float]]:
        from ..protocols.netguard import pinned_client
        import httpx
        out: list[dict[int, float]] = []
        for i in range(0, len(texts), self.MAX_BATCH):
            batch = [t[:8000] for t in texts[i:i + self.MAX_BATCH]]
            try:
                with pinned_client(timeout=self.timeout, transport=self.transport) as http:
                    resp = http.post(f"{self.base_url}/embeddings", json={"model": self.model, "input": batch},
                                     headers={"Authorization": f"Bearer {self.api_key}"})
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"embedding provider unreachable: {type(exc).__name__}") from exc
            if resp.status_code in (401, 403):
                raise EmbeddingError(f"embedding provider rejected the credential (HTTP {resp.status_code})")
            if resp.status_code != 200:
                raise EmbeddingError(f"embedding provider answered HTTP {resp.status_code}")
            try:
                rows = sorted(resp.json()["data"], key=lambda r: r["index"])
                vecs = [r["embedding"] for r in rows]
            except (ValueError, KeyError, TypeError) as exc:
                raise EmbeddingError("embedding provider returned a malformed body") from exc
            if len(vecs) != len(batch) or any(not isinstance(v, list) or not v for v in vecs):
                raise EmbeddingError("embedding provider returned the wrong number of vectors")
            for v in vecs:
                norm = math.sqrt(sum(x * x for x in v)) or 1.0
                out.append({j: x / norm for j, x in enumerate(v) if x})
        return out

    def embed(self, text: str) -> dict[int, float]:
        return self.embed_many([text])[0]


class EmbeddingError(RuntimeError):
    pass


_default_embedder: Optional[Embedder] = None
_local_embedder: Optional[Embedder] = None


def local_embedder() -> Embedder:
    """The deterministic embedder. Memory always uses it, so its stored vectors never depend on a provider."""
    global _local_embedder
    if _local_embedder is None:
        _local_embedder = HashedNgramEmbedder()
    return _local_embedder


def provider_configured() -> bool:
    return os.getenv("MO_EMBEDDINGS_PROVIDER", "").lower() == "openai" and bool(
        (os.getenv("MO_EMBEDDINGS_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip())


def get_embedder() -> Embedder:
    """A provider embedder when configured, else the local one (which reports itself as non-neural by name)."""
    global _default_embedder
    if provider_configured():
        key = (os.getenv("MO_EMBEDDINGS_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        base = os.getenv("MO_EMBEDDINGS_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("MO_EMBEDDINGS_MODEL", "text-embedding-3-small")
        cur = _default_embedder
        if not (isinstance(cur, ProviderEmbedder) and (cur.api_key, cur.base_url, cur.model) == (key, base.rstrip("/"), model)):
            _default_embedder = ProviderEmbedder(key, base, model)
        return _default_embedder
    if _default_embedder is None or isinstance(_default_embedder, ProviderEmbedder):
        _default_embedder = local_embedder()
    return _default_embedder
