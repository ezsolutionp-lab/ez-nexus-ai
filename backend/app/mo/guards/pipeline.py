"""
MO NEXUS OMEGA — Input and output guards.

`guard_input` runs before text reaches a model or an agent; `guard_output` runs
before a model's answer reaches a user, a voice channel or another system. Both
write an audit record when they act, and neither fails open: a BLOCK verdict is a
POLICY_DENIED result, not a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..errors import MoResult, ResultState
from . import injection, pii


@dataclass
class GuardOutcome:
    text: str
    findings: list[pii.Finding] = field(default_factory=list)
    injection: Optional[injection.InjectionVerdict] = None
    blocked: bool = False
    reason: str = ""

    def to_result(self) -> MoResult:
        meta = {"pii": [f.to_dict() for f in self.findings],
                "injection": self.injection.to_dict() if self.injection else None}
        if self.blocked:
            return MoResult(ResultState.POLICY_DENIED, self.reason, meta=meta)
        return MoResult.ok({"text": self.text}, **meta)


# Severities that stop input outright rather than being redacted and passed on.
_BLOCK_INPUT_ON = {"CRITICAL"}


def guard_input(text: str, ctx: Optional[RequestContext] = None, db: Optional[Session] = None,
                *, allow_secrets: bool = False) -> GuardOutcome:
    verdict = injection.screen(text)
    redacted, findings = pii.redact(text)
    outcome = GuardOutcome(text=redacted, findings=findings, injection=verdict)

    secrets = [f for f in findings if f.severity in _BLOCK_INPUT_ON]
    if verdict.verdict == "BLOCK":
        outcome.blocked = True
        outcome.reason = f"Input blocked: prompt-injection signals {', '.join(verdict.signals)}."
    elif secrets and not allow_secrets:
        outcome.blocked = True
        kinds = sorted({f.kind for f in secrets})
        outcome.reason = f"Input blocked: it contains what looks like a secret ({', '.join(kinds)})."
    _audit(db, ctx, "guard.input", outcome)
    return outcome


def guard_output(text: str, ctx: Optional[RequestContext] = None, db: Optional[Session] = None) -> GuardOutcome:
    """Output is never blocked for PII — it is redacted — but leaked secrets are stripped and recorded."""
    redacted, findings = pii.redact(text)
    outcome = GuardOutcome(text=redacted, findings=findings)
    _audit(db, ctx, "guard.output", outcome)
    return outcome


def _count(action: str, outcome: GuardOutcome) -> None:
    from ..observability.metrics import metrics
    verdict = "blocked" if outcome.blocked else "redacted" if outcome.findings else \
        "flagged" if outcome.injection and outcome.injection.verdict != "ALLOW" else "clean"
    metrics.inc("mo_guard_actions_total", guard=action, outcome=verdict)


def _audit(db: Optional[Session], ctx: Optional[RequestContext], action: str, outcome: GuardOutcome) -> None:
    _count(action, outcome)
    acted = outcome.blocked or outcome.findings or (outcome.injection and outcome.injection.verdict != "ALLOW")
    if not (db and ctx and acted):
        return
    state = ResultState.POLICY_DENIED if outcome.blocked else ResultState.SUCCESS
    chain.record(
        db, ctx, action=action, result_state=state, detail=outcome.reason,
        payload={"kinds": sorted({f.kind for f in outcome.findings}),
                 "injection": outcome.injection.to_dict() if outcome.injection else None},
    )
