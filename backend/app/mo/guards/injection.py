"""
MO NEXUS OMEGA — Prompt-injection screening.

Heuristic, and honest about it: these rules catch the common, well-known
override and exfiltration phrasings. They are a first line, not a guarantee —
the durable defence is that untrusted text never gains tool authority, which the
ToolRegistry and approval engine enforce regardless of what a prompt says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    name: str
    weight: int
    pattern: re.Pattern


def _s(name: str, weight: int, pattern: str) -> Signal:
    return Signal(name, weight, re.compile(pattern, re.IGNORECASE))


SIGNALS: tuple[Signal, ...] = (
    _s("override_instructions", 5,
       r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your)\b[^.\n]{0,30}"
       r"\b(instructions?|rules?|prompts?|guidelines?|directives?)\b"),
    _s("reveal_system_prompt", 4,
       r"\b(reveal|print|show|repeat|output|leak|tell me)\b[^.\n]{0,40}\b(system|hidden|initial|secret)\b[^.\n]{0,20}"
       r"\b(prompt|instructions?|message)\b"),
    _s("role_override", 3,
       r"\b(you are now|act as|pretend to be|from now on you)\b[^.\n]{0,60}\b(unrestricted|jailbroken|dan|no rules|"
       r"without (?:any )?(?:restrictions|limits|filters))"),
    _s("disable_safety", 4,
       r"\b(disable|bypass|turn off|skip|ignore)\b[^.\n]{0,30}\b(safety|guardrails?|approvals?|policy|policies|"
       r"filters?|security|governance)\b"),
    _s("exfiltrate", 4,
       r"\b(send|post|upload|forward|email|exfiltrate)\b[^.\n]{0,60}\b(api[ _-]?keys?|passwords?|secrets?|tokens?|"
       r"credentials?|private keys?)\b[^.\n]{0,60}\b(to|at)\b"),
    _s("fake_authority", 3,
       r"\b(i am|this is)\b[^.\n]{0,20}\b(the )?(admin|administrator|developer|system|anthropic|owner)\b[^.\n]{0,40}"
       r"\b(authorize|approved|override|grant)"),
    _s("delimiter_injection", 3, r"(?:^|\n)\s*(?:###\s*)?(?:system|assistant)\s*:\s*\S"),
    _s("tool_smuggling", 3, r"<\s*/?\s*(?:tool_call|function_call|system)\s*>"),
)

BLOCK_THRESHOLD = 5
FLAG_THRESHOLD = 3


@dataclass
class InjectionVerdict:
    verdict: str            # ALLOW | FLAG | BLOCK
    score: int
    signals: list[str]

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "score": self.score, "signals": self.signals}


def screen(text: str) -> InjectionVerdict:
    if not text:
        return InjectionVerdict("ALLOW", 0, [])
    hits = [s for s in SIGNALS if s.pattern.search(text)]
    score = sum(s.weight for s in hits)
    verdict = "BLOCK" if score >= BLOCK_THRESHOLD else "FLAG" if score >= FLAG_THRESHOLD else "ALLOW"
    return InjectionVerdict(verdict, score, [s.name for s in hits])
