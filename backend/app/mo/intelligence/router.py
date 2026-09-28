"""
Domain router — decides which business domain a request belongs to.

Weighted keyword and phrase scoring over stemmed terms, with a confidence and the
runner-up domains, so a caller can ask a clarifying question instead of guessing. It is a
rule-based router: it recognises the vocabulary below and nothing else.
"""

from __future__ import annotations

import re
from typing import Any

from ..knowledge.ranking import stem

MAX_TEXT = 20_000

# domain -> {term or phrase: weight}. Phrases match on the raw lowercase text.
DOMAINS: dict[str, dict[str, float]] = {
    "commerce": {"shopify": 3, "amazon": 3, "ebay": 3, "order": 1.5, "product": 1, "inventory": 2, "sku": 2,
                 "cart": 1.5, "checkout": 2, "storefront": 2, "shipping": 1, "refund": 1.5},
    "marketing": {"campaign": 2, "seo": 3, "content": 1, "social": 1.5, "ads": 2, "newsletter": 2, "audience": 1.5,
                  "brand": 1, "engagement": 1.5, "keyword": 1},
    "sales": {"lead": 2, "crm": 3, "prospect": 2.5, "pipeline": 2.5, "deal": 2, "quota": 2, "outreach": 2,
              "opportunity": 1.5, "forecast": 0.5},
    "finance": {"invoice": 3, "expense": 2.5, "budget": 2, "payroll": 3, "tax": 3, "ledger": 2.5, "revenue": 1,
                "cashflow": 2.5, "audit": 1, "reconciliation": 2.5, "accounting": 2.5},
    "pmo": {"project": 1.5, "milestone": 3, "risk": 1, "resource": 1, "roadmap": 3, "sprint": 2, "deadline": 2,
            "gantt": 3, "stakeholder": 2, "dependency": 1.5, "critical path": 3},
    "cyber": {"threat": 3, "security": 2, "incident": 2, "vulnerability": 3, "malware": 3, "phishing": 3,
              "breach": 3, "firewall": 2.5, "siem": 3, "exploit": 3, "cve": 3},
    "telecom": {"ran": 3, "cell": 1.5, "telecom": 3, "network": 1, "antenna": 2.5, "latency": 1, "spectrum": 3,
                "5g": 3, "lte": 3, "base station": 3},
    "hospitality": {"reservation": 3, "guest": 2.5, "hotel": 3, "room": 1.5, "concierge": 2, "check-in": 2.5,
                    "housekeeping": 3, "booking": 1.5},
    "media": {"screenplay": 3, "film": 3, "episode": 2.5, "music": 2, "dubbing": 3, "script": 1, "scene": 2,
              "soundtrack": 3, "storyboard": 3},
    "dev": {"repo": 3, "code": 1, "test": 1, "deploy": 2.5, "github": 3, "commit": 2, "pull request": 3,
            "bug": 2, "refactor": 3, "ci": 1.5, "pipeline failed": 2},
}

_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_INDEX: dict[str, list[tuple[str, float]]] = {}
_PHRASES: list[tuple[str, str, float]] = []
for _d, _kw in DOMAINS.items():
    for _k, _w in _kw.items():
        if " " in _k:
            _PHRASES.append((_d, _k, _w))
        else:
            _INDEX.setdefault(_k, []).append((_d, _w))
            _INDEX.setdefault(stem(_k), []).append((_d, _w))


def route_domain(text: Any, *, min_score: float = 2.0, max_alternatives: int = 2) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if len(text) > MAX_TEXT:
        raise ValueError(f"text is limited to {MAX_TEXT} characters")
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)) or min_score < 0:
        raise ValueError("min_score must be a non-negative number")
    low = text.lower()
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for word in _WORD.findall(low):
        forms = {word, stem(word)}
        if word.endswith("es"):
            forms.add(word[:-2])
        if word.endswith("s"):
            forms.add(word[:-1])
        for key in forms:
            for domain, weight in _INDEX.get(key, ()):
                if (domain, word) in seen:
                    continue
                seen.add((domain, word))
                scores[domain] = scores.get(domain, 0.0) + weight
                hits.setdefault(domain, []).append(word)
    for domain, phrase, weight in _PHRASES:
        if phrase in low:
            scores[domain] = scores.get(domain, 0.0) + weight
            hits.setdefault(domain, []).append(phrase)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < min_score:
        return {"domain": "general", "confidence": 0.0, "ambiguous": False, "matched": [],
                "alternatives": [{"domain": d, "score": round(s, 2)} for d, s in ranked[:max_alternatives]],
                "note": "No domain vocabulary matched strongly enough; ask a clarifying question or handle generally."}
    top, top_score = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = round(min(0.99, (top_score - runner) / top_score * 0.6 + min(top_score, 6) / 6 * 0.4), 3)
    ambiguous = runner > 0 and runner >= 0.75 * top_score
    return {"domain": top, "confidence": confidence, "ambiguous": ambiguous, "matched": sorted(set(hits[top])),
            "alternatives": [{"domain": d, "score": round(s, 2)} for d, s in ranked[1:1 + max_alternatives]],
            "note": "Two domains scored closely; confirm with the user." if ambiguous else ""}
