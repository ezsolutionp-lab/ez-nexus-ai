"""
MO NEXUS OMEGA — Claim / truth verification.

Splits an answer into checkable claims and grades each against the evidence passages the
caller supplies. This is a *lexical and numeric* verifier, not an entailment model:

  grounding      how much of a claim's content is present in a passage (stemmed terms)
  evidence link  the best passage per claim, with a citation id
  contradiction  same subject, but numbers differ or polarity (negation) is flipped
  source quality per-passage weight (0-1) scales confidence; corroboration by independent
                 sources raises it
  freshness      a claim supported only by passages older than `max_age_days` is STALE
  abstention     the report says when the answer should not be given as-is
  human review   flagged for critical output, contradictions, or low groundedness

It extends `guards.grounding` (which only answers supported / unsupported) with contradiction,
source quality, freshness and abstention. It can miss paraphrase and can be fooled by a passage that repeats a claim's words while
meaning something else. The result says so; it never certifies truth, only support.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from ..guards import grounding
from ..knowledge.ranking import terms

MAX_CLAIMS = 200
MAX_EVIDENCE = 200
MAX_TEXT = 200_000
SUPPORT_COVERAGE = 0.6

_NEGATIONS = {"not", "no", "never", "cannot", "without", "none", "neither", "nor", "isnt", "arent", "wasnt", "werent",
              "doesnt", "dont", "didnt", "wont", "cant", "couldnt", "shouldnt", "wouldnt", "hasnt", "havent", "hadnt",
              "fail", "fails", "failed", "unable", "lacks", "lack"}
_HEDGES = {"may", "might", "could", "possibly", "perhaps", "probably", "approximately", "roughly", "about",
           "around", "likely", "appears", "seems", "reportedly", "estimated", "suggests"}
_TOKEN = re.compile(r"[a-z0-9']+")


def _polarity(text: str) -> int:
    """+1 affirmative, -1 negated (odd number of negations)."""
    words = [w.replace("'", "") for w in _TOKEN.findall(text.lower())]
    n = sum(1 for w in words if w in _NEGATIONS)
    return -1 if n % 2 else 1


def _hedged(text: str) -> bool:
    return any(w in _HEDGES for w in _TOKEN.findall(text.lower()))


def split_claims(text: str) -> list[str]:
    """Checkable sentences (reuses the guard's splitter); questions are skipped and size is bounded."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if len(text) > MAX_TEXT:
        raise ValueError(f"text is limited to {MAX_TEXT} characters")
    claims = [c for c in grounding.split_claims(text) if not c.endswith("?")]
    if len(claims) > MAX_CLAIMS:
        raise ValueError(f"at most {MAX_CLAIMS} claims can be verified at once")
    return claims


def _parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"evidence date '{value}' is not YYYY-MM-DD") from None


def _clean_evidence(evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("evidence must be a non-empty list of passages")
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError(f"at most {MAX_EVIDENCE} evidence passages are supported")
    out, seen = [], set()
    for i, e in enumerate(evidence):
        if not isinstance(e, dict) or not isinstance(e.get("text"), str) or not e["text"].strip():
            raise ValueError("every evidence passage needs a non-empty string 'text'")
        if len(e["text"]) > MAX_TEXT:
            raise ValueError(f"an evidence passage is limited to {MAX_TEXT} characters")
        eid = str(e.get("id", f"e{i + 1}"))
        if eid in seen:
            raise ValueError(f"duplicate evidence id '{eid}'")
        seen.add(eid)
        q = e.get("quality", 0.6)
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not 0.0 <= q <= 1.0:
            raise ValueError(f"evidence '{eid}' quality must be a number between 0 and 1")
        out.append({"id": eid, "source": str(e.get("source", eid)), "quality": float(q),
                    "date": _parse_date(e.get("date")), "text": e["text"],
                    "terms": set(terms(e["text"])), "numbers": grounding.numbers(e["text"]), "polarity": _polarity(e["text"])})
    return out


def _coverage(claim_terms: set[str], ev_terms: set[str]) -> float:
    return len(claim_terms & ev_terms) / len(claim_terms) if claim_terms else 0.0


def _grade_claim(claim: str, evidence: list[dict[str, Any]], today: date, max_age_days: Optional[int]) -> dict[str, Any]:
    cterms, cnums, cpol = set(terms(claim)), grounding.numbers(claim), _polarity(claim)
    linked = sorted(((_coverage(cterms, e["terms"]), e) for e in evidence), key=lambda x: -x[0])
    related = [(c, e) for c, e in linked if c >= SUPPORT_COVERAGE]
    base = {"claim": claim, "hedged": _hedged(claim), "best_coverage": round(linked[0][0], 3) if linked else 0.0}
    if not related:
        return {**base, "verdict": "UNSUPPORTED", "confidence": 0.1, "citations": [],
                "note": "No evidence passage covers this claim."}

    supporting, contradicting = [], []
    reason = ""
    for cov, e in related:
        if cnums and e["numbers"] and not cnums <= e["numbers"]:
            contradicting.append((cov, e)); reason = "The evidence gives different figures."
        elif e["polarity"] != cpol:
            contradicting.append((cov, e)); reason = "The evidence asserts the opposite polarity."
        else:
            supporting.append((cov, e))
    if contradicting and not supporting:
        best = contradicting[0][1]
        return {**base, "verdict": "CONTRADICTED", "confidence": round(0.6 + 0.3 * best["quality"], 3),
                "citations": [e["id"] for _, e in contradicting], "note": reason}

    fresh, stale = [], []
    for cov, e in supporting:
        too_old = max_age_days is not None and e["date"] is not None and (today - e["date"]).days > max_age_days
        (stale if too_old else fresh).append((cov, e))
    if not fresh:
        return {**base, "verdict": "STALE", "confidence": 0.3, "citations": [e["id"] for _, e in stale],
                "note": f"Only evidence older than {max_age_days} days supports this claim."}

    sources = {e["source"] for _, e in fresh}
    best_cov, best = fresh[0]
    conf = best_cov * (0.5 + 0.5 * best["quality"])
    conf += 0.1 * min(2, len(sources) - 1)                      # corroboration by independent sources
    if contradicting:
        conf *= 0.6                                              # conflicting sources: lower and say so
    if base["hedged"]:
        conf *= 0.9
    conf = round(max(0.05, min(0.95, conf)), 3)
    note = f"Supported by {len(sources)} source(s)."
    if contradicting:
        note += f" {len(contradicting)} other passage(s) disagree; review before relying on it."
    return {**base, "verdict": "SUPPORTED", "confidence": conf, "citations": [e["id"] for _, e in fresh],
            "contradicting": [e["id"] for _, e in contradicting], "note": note}


def verify_claims(answer: Any = None, evidence: Any = None, *, claims: Optional[list[str]] = None,
                  today: Optional[date] = None, max_age_days: Optional[int] = None, critical: bool = False,
                  min_groundedness: float = 0.7) -> dict[str, Any]:
    if claims is None:
        claims = split_claims(answer)
    else:
        if not isinstance(claims, list) or not all(isinstance(c, str) and c.strip() for c in claims):
            raise ValueError("claims must be a list of non-empty strings")
        if len(claims) > MAX_CLAIMS:
            raise ValueError(f"at most {MAX_CLAIMS} claims can be verified at once")
    if not claims:
        raise ValueError("no checkable claims were found")
    if max_age_days is not None and (isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0):
        raise ValueError("max_age_days must be a non-negative integer")
    if isinstance(min_groundedness, bool) or not isinstance(min_groundedness, (int, float)) or not 0 < min_groundedness <= 1:
        raise ValueError("min_groundedness must be in (0, 1]")
    ev = _clean_evidence(evidence)
    today = today or datetime.now(timezone.utc).date()
    graded = [_grade_claim(c, ev, today, max_age_days) for c in claims]
    counts = {v: sum(1 for g in graded if g["verdict"] == v) for v in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "STALE")}
    groundedness = counts["SUPPORTED"] / len(graded)
    weights = [g["confidence"] for g in graded]
    mean_conf = round(math.fsum(weights) / len(weights), 3)
    abstain = counts["CONTRADICTED"] > 0 or groundedness < min_groundedness
    reasons = []
    if counts["CONTRADICTED"]:
        reasons.append(f"{counts['CONTRADICTED']} claim(s) contradict the evidence")
    if groundedness < min_groundedness:
        reasons.append(f"groundedness {groundedness:.0%} is below {min_groundedness:.0%}")
    if critical:
        reasons.append("output is marked critical")
    return {"method": "lexical-numeric-grounding", "model_class": "heuristic (not an entailment model)",
            "claims": graded, "counts": counts, "groundedness": round(groundedness, 3), "mean_confidence": mean_conf,
            "abstain": abstain, "requires_human_review": bool(critical or abstain),
            "reasons": reasons, "citations": sorted({c for g in graded for c in g["citations"]}),
            "limits": "Cannot detect paraphrase it does not share words with, or a passage that reuses a claim's words "
                      "while meaning something else. Support is not proof."}
