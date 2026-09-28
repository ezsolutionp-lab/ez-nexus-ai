"""
MO NEXUS OMEGA — Context management and semantic cache.

ContextPolicy / compress:  keep the system prompt and the most recent turns verbatim, and
replace older turns with an *extractive* summary (their most informative sentences, verbatim,
plus every figure they stated). Nothing is generated, so nothing can be invented; the cost is
that it is blunter than an LLM summary. Token counts are estimates (~4 characters per token),
not a tokenizer's.

SemanticCache:  reuse an earlier answer for a near-identical question. Entries are keyed by
tenant and namespace, so one tenant can never be served another's answer; a question
containing a secret or PII is never stored; entries expire and the cache is size-bounded.
Similarity uses the local hashed n-gram embedder (not neural), so the threshold is strict
by default and a miss is always safe.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections import OrderedDict, Counter
from dataclasses import dataclass
from typing import Any, Optional

from ..guards import pii
from ..knowledge.ranking import cosine, get_embedder, terms

CHARS_PER_TOKEN = 4
MAX_TURNS = 5_000


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


@dataclass
class ContextPolicy:
    max_tokens: int = 64_000
    summarize_after_tokens: int = 24_000
    keep_recent_turns: int = 12
    retrieval_budget_tokens: int = 16_000
    response_budget_tokens: int = 4_000

    def __post_init__(self) -> None:
        for name in ("max_tokens", "summarize_after_tokens", "keep_recent_turns",
                     "retrieval_budget_tokens", "response_budget_tokens"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.summarize_after_tokens > self.max_tokens:
            raise ValueError("summarize_after_tokens cannot exceed max_tokens")
        if self.retrieval_budget_tokens + self.response_budget_tokens >= self.max_tokens:
            raise ValueError("retrieval and response budgets must leave room for the conversation")


def should_summarize(current_tokens: int, policy: ContextPolicy) -> bool:
    return current_tokens >= policy.summarize_after_tokens


_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def _extract_summary(texts: list[str], budget_tokens: int) -> str:
    sentences = [s.strip() for t in texts for s in _SENT.split(t) if len(terms(s)) >= 3]
    if not sentences:
        return ""
    freq = Counter(w for s in sentences for w in set(terms(s)))
    scored = []
    for i, s in enumerate(sentences):
        ws = set(terms(s))
        score = sum(math.log(1 + freq[w]) for w in ws) / math.sqrt(len(ws) or 1) + 0.5 * len(_NUM.findall(s))
        scored.append((score, i, s))
    chosen, used = [], 0
    for _, i, s in sorted(scored, key=lambda x: (-x[0], x[1])):
        cost = estimate_tokens(s) + 1
        if used + cost > budget_tokens:
            continue
        chosen.append((i, s)); used += cost
    return " ".join(s for _, s in sorted(chosen))


def compress(messages: list[dict[str, Any]], policy: Optional[ContextPolicy] = None) -> dict[str, Any]:
    """Return {messages, compressed, tokens_before, tokens_after, dropped_turns}. Never mutates the input."""
    policy = policy or ContextPolicy()
    if not isinstance(messages, list) or len(messages) > MAX_TURNS:
        raise ValueError(f"messages must be a list of at most {MAX_TURNS} turns")
    for m in messages:
        if not isinstance(m, dict) or not isinstance(m.get("content"), str) or not isinstance(m.get("role"), str):
            raise ValueError("every message needs a string 'role' and 'content'")
    before = sum(estimate_tokens(m["content"]) for m in messages)
    if not should_summarize(before, policy):
        return {"messages": [dict(m) for m in messages], "compressed": False, "tokens_before": before,
                "tokens_after": before, "dropped_turns": 0}
    system = [m for m in messages if m["role"] == "system"]
    convo = [m for m in messages if m["role"] != "system"]
    recent = convo[-policy.keep_recent_turns:] if policy.keep_recent_turns else []
    older = convo[: len(convo) - len(recent)]
    kept_tokens = sum(estimate_tokens(m["content"]) for m in system + recent)
    room = max(0, policy.max_tokens - policy.retrieval_budget_tokens - policy.response_budget_tokens - kept_tokens)
    budget = min(room, max(256, policy.summarize_after_tokens // 4))
    summary = _extract_summary([m["content"] for m in older], budget) if older else ""
    out = [dict(m) for m in system]
    if summary:
        out.append({"role": "system", "content": "Summary of earlier conversation (extractive, verbatim sentences): " + summary})
    out += [dict(m) for m in recent]
    after = sum(estimate_tokens(m["content"]) for m in out)
    return {"messages": out, "compressed": bool(older), "tokens_before": before, "tokens_after": after,
            "dropped_turns": len(older), "summary_is_extractive": True}


class SemanticCache:
    def __init__(self, *, threshold: float = 0.93, ttl_seconds: float = 3600.0, max_entries: int = 1000) -> None:
        if not 0.5 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.5 and 1.0")
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("ttl_seconds and max_entries must be positive")
        self.threshold, self.ttl, self.max_entries = threshold, ttl_seconds, max_entries
        self._store: OrderedDict[tuple[str, str, int], dict[str, Any]] = OrderedDict()
        self._seq = 0
        self._lock = threading.Lock()
        self._embedder = get_embedder()
        self.hits = self.misses = 0

    def put(self, tenant_id: str, question: str, answer: str, *, namespace: str = "default",
            now: Optional[float] = None) -> bool:
        """Store an answer. Returns False (and stores nothing) when the question or answer holds a secret or PII."""
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not question.strip() or not answer.strip():
            return False
        if pii.scan(question) or pii.scan(answer):
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            self._seq += 1
            self._store[(tenant_id, namespace, self._seq)] = {
                "vec": self._embedder.embed(question), "question": question, "answer": answer, "at": now}
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)
        return True

    def get(self, tenant_id: str, question: str, *, namespace: str = "default",
            now: Optional[float] = None) -> Optional[dict[str, Any]]:
        now = time.monotonic() if now is None else now
        vec = self._embedder.embed(question)
        best, best_key = 0.0, None
        with self._lock:
            for key in [k for k, e in self._store.items() if now - e["at"] > self.ttl]:
                del self._store[key]
            for key, e in self._store.items():
                if key[0] != tenant_id or key[1] != namespace:
                    continue
                sim = cosine(vec, e["vec"])
                if sim > best:
                    best, best_key = sim, key
            if best_key is not None and best >= self.threshold:
                self._store.move_to_end(best_key)
                self.hits += 1
                e = self._store[best_key]
                return {"answer": e["answer"], "matched_question": e["question"], "similarity": round(best, 4)}
            self.misses += 1
        return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {"entries": len(self._store), "hits": self.hits, "misses": self.misses,
                    "hit_rate": round(self.hits / total, 3) if total else 0.0, "embedder": self._embedder.name}

    def clear(self, tenant_id: Optional[str] = None) -> int:
        with self._lock:
            keys = [k for k in self._store if tenant_id is None or k[0] == tenant_id]
            for k in keys:
                del self._store[k]
            return len(keys)
