"""
MO NEXUS OMEGA — Sensitive-data detection and redaction.

Detection is pattern based and says so: it finds structured secrets and
identifiers, it does not understand context. Credit-card candidates must pass
the Luhn checksum so an order number is not reported as a card. Anything found
can be redacted before text reaches a model, a log or a voice reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int
    severity: str       # LOW | MEDIUM | HIGH | CRITICAL

    def to_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end, "severity": self.severity}


def luhn_valid(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("PRIVATE_KEY", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "CRITICAL"),
    ("AWS_ACCESS_KEY", r"\bAKIA[0-9A-Z]{16}\b", "CRITICAL"),
    ("API_KEY", r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b", "CRITICAL"),
    ("GITHUB_TOKEN", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", "CRITICAL"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b", "HIGH"),
    ("BEARER_TOKEN", r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}", "HIGH"),
    ("SSN", r"\b\d{3}-\d{2}-\d{4}\b", "HIGH"),
    ("EMAIL", r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "MEDIUM"),
    ("PHONE", r"(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)", "MEDIUM"),
    ("IPV4", r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b", "LOW"),
)
_COMPILED = [(k, re.compile(p), s) for k, p, s in _PATTERNS]
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")

SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def scan(text: str) -> list[Finding]:
    """Return non-overlapping findings, most severe kept on overlap."""
    if not text:
        return []
    found: list[Finding] = []
    for m in _CARD.finditer(text):
        if luhn_valid(m.group()):
            found.append(Finding("CREDIT_CARD", m.start(), m.end(), "CRITICAL"))
    for kind, rx, sev in _COMPILED:
        for m in rx.finditer(text):
            found.append(Finding(kind, m.start(), m.end(), sev))
    found.sort(key=lambda f: (f.start, -SEVERITY_ORDER[f.severity]))
    out: list[Finding] = []
    for f in found:
        if out and f.start < out[-1].end:
            if SEVERITY_ORDER[f.severity] > SEVERITY_ORDER[out[-1].severity]:
                out[-1] = f
            continue
        out.append(f)
    return out


def redact(text: str) -> tuple[str, list[Finding]]:
    """Replace every finding with a typed placeholder, e.g. [REDACTED:EMAIL]."""
    findings = scan(text)
    if not findings:
        return text, []
    parts: list[str] = []
    cursor = 0
    for f in findings:
        parts.append(text[cursor:f.start])
        parts.append(f"[REDACTED:{f.kind}]")
        cursor = f.end
    parts.append(text[cursor:])
    return "".join(parts), findings


def max_severity(findings: list[Finding]) -> str:
    if not findings:
        return "NONE"
    return max(findings, key=lambda f: SEVERITY_ORDER[f.severity]).severity
