"""
MO NEXUS OMEGA — Claim / evidence verification.

A claim is *supported* only when its content words are covered by a single
evidence passage and every number it states appears in that passage. This is
lexical grounding, not entailment: it reliably catches invented figures and
unsupported statements, and it cannot judge paraphrase that shares no words.
The result says which evidence supports each claim, so a citation is checkable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

_STOP = frozenset("""a an the and or but if then else of to in on at by for with from as is are was were be been being
it its this that these those there here we you they he she i our your their his her not no yes do does did done have has
had will would can could should may might must about into over under than so such also very just more most less""".split())
_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")

SUPPORT_THRESHOLD = 0.6


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip("%") for n in _NUMBER.findall(text)}


def split_claims(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if len(tokens(p)) >= 3]


@dataclass
class ClaimCheck:
    claim: str
    supported: bool
    coverage: float
    evidence_id: str | None
    unsupported_numbers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"claim": self.claim, "supported": self.supported, "coverage": round(self.coverage, 3),
                "evidence_id": self.evidence_id, "unsupported_numbers": self.unsupported_numbers}


@dataclass
class GroundingReport:
    claims: list[ClaimCheck]

    @property
    def grounded_ratio(self) -> float:
        return sum(c.supported for c in self.claims) / len(self.claims) if self.claims else 1.0

    @property
    def unsupported(self) -> list[ClaimCheck]:
        return [c for c in self.claims if not c.supported]

    def to_dict(self) -> dict:
        return {"grounded_ratio": round(self.grounded_ratio, 3), "claim_count": len(self.claims),
                "unsupported_count": len(self.unsupported), "claims": [c.to_dict() for c in self.claims]}


def verify_claims(answer: str, evidence: Iterable[tuple[str, str]]) -> GroundingReport:
    """`evidence` is (evidence_id, text) pairs. Each claim is matched to its best passage."""
    passages = [(eid, set(tokens(text)), numbers(text)) for eid, text in evidence]
    checks: list[ClaimCheck] = []
    for claim in split_claims(answer):
        words = set(tokens(claim))
        claim_numbers = numbers(claim)
        best_id, best_cov, best_missing = None, 0.0, sorted(claim_numbers)
        for eid, ev_words, ev_numbers in passages:
            cov = len(words & ev_words) / len(words) if words else 0.0
            missing = sorted(claim_numbers - ev_numbers)
            if (not missing, cov) > (not best_missing, best_cov):
                best_id, best_cov, best_missing = eid, cov, missing
        supported = best_cov >= SUPPORT_THRESHOLD and not best_missing
        checks.append(ClaimCheck(claim, supported, best_cov, best_id if supported else None,
                                 [] if supported else best_missing))
    return GroundingReport(checks)
