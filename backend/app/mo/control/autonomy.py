"""
MO NEXUS OMEGA — Autonomy levels and shadow learning.

Autonomy decides how much MO may do *without a human present*. It is a restriction
layer on top of governance, never a bypass of it:

  level  name          MO may proceed unattended for
  ─────  ────────────  ─────────────────────────────────────────────
    0    OBSERVE       nothing — it can only watch and report
    1    SUGGEST       nothing — every step is proposed for a human to confirm
    2    ASSIST        LOW risk
    3    SUPERVISED    LOW and MEDIUM risk
    4    DELEGATED     LOW, MEDIUM and HIGH risk (HIGH still needs its approval)
    5    AUTONOMOUS    everything short of CRITICAL (CRITICAL always needs 2 approvals + MFA)

The tool registry's approval gates, the approvals engine, MFA and the tenant kill
switch keep working at every level. A high autonomy level cannot approve anything.

Levels move up only through evidence: MO runs in *shadow* (proposes, a human decides)
and is promoted one level at a time, and only while its proposals agree with the
human's decisions often enough, over enough samples. Levels move down immediately.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import AutonomyPolicy, ShadowRecord
from ..errors import MoResult, ResultState

LEVELS = {0: "OBSERVE", 1: "SUGGEST", 2: "ASSIST", 3: "SUPERVISED", 4: "DELEGATED", 5: "AUTONOMOUS"}
DEFAULT_LEVEL = 1
DEFAULT_MAX_LEVEL = 3
RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
# Highest risk that may proceed unattended, per level. -1 means none.
_UNATTENDED_UP_TO = {0: -1, 1: -1, 2: 0, 3: 1, 4: 2, 5: 2}

MIN_SAMPLES_FOR_PROMOTION = 20
MIN_AGREEMENT_FOR_PROMOTION = 0.95

ALLOW, CONFIRM, DENY = "ALLOW", "CONFIRM", "DENY"


class AutonomyManager:
    def __init__(self, db: Session, ctx: RequestContext):
        self.db, self.ctx = db, ctx

    # ── policy ──────────────────────────────────────────────────────────────

    def _policies(self) -> list[AutonomyPolicy]:
        return self.db.query(AutonomyPolicy).filter(AutonomyPolicy.tenant_id == self.ctx.tenant_id).all()

    def policy_for(self, subject: str) -> tuple[int, int, str]:
        """(level, max_level, matched_subject). Exact match, else the longest dotted/colon prefix, else default."""
        best: Optional[AutonomyPolicy] = None
        for p in self._policies():
            if subject == p.subject or subject.startswith(p.subject.rstrip(".:") + ".") \
                    or subject.startswith(p.subject.rstrip(".:") + ":"):
                if best is None or len(p.subject) > len(best.subject):
                    best = p
        if best is None:
            return DEFAULT_LEVEL, DEFAULT_MAX_LEVEL, "(default)"
        return best.level, best.max_level, best.subject

    def decide(self, subject: str, risk_level: str) -> tuple[str, str]:
        """(ALLOW|CONFIRM|DENY, reason) for running `subject` unattended at `risk_level`."""
        level, _, matched = self.policy_for(subject)
        if level == 0:
            return DENY, f"Autonomy for '{matched}' is OBSERVE: MO may watch and report but not act."
        ceiling = _UNATTENDED_UP_TO[level]
        if RISK_ORDER.get(risk_level, 3) <= ceiling:
            return ALLOW, f"Level {level} ({LEVELS[level]}) permits {risk_level} risk unattended."
        return CONFIRM, (f"Level {level} ({LEVELS[level]}) does not permit {risk_level} risk "
                         f"unattended; a human must confirm.")

    def set_policy(self, subject: str, level: int, *, max_level: Optional[int] = None,
                   reason: str = "") -> MoResult:
        if level not in LEVELS:
            return MoResult(ResultState.FAILED, "Autonomy level must be between 0 and 5.")
        if not self.ctx.is_admin:
            return MoResult(ResultState.POLICY_DENIED, "Only an administrator can set autonomy policy.")
        row = (self.db.query(AutonomyPolicy)
               .filter(AutonomyPolicy.tenant_id == self.ctx.tenant_id, AutonomyPolicy.subject == subject).first())
        current_level = row.level if row else DEFAULT_LEVEL
        cap = row.max_level if row else DEFAULT_MAX_LEVEL
        if max_level is not None:
            if max_level not in LEVELS:
                return MoResult(ResultState.FAILED, "max_level must be between 0 and 5.")
            if max_level > cap and not self.ctx.mfa_verified:
                return MoResult(ResultState.POLICY_DENIED, "Raising the autonomy ceiling requires an MFA-verified session.")
            cap = max_level
        if level > cap:
            return MoResult(ResultState.POLICY_DENIED,
                            f"Level {level} exceeds this subject's ceiling of {cap}. Raise the ceiling first (MFA required).")
        if level >= 4 and level > current_level and not self.ctx.mfa_verified:
            return MoResult(ResultState.POLICY_DENIED, "Levels 4 and 5 require an MFA-verified session.")
        if row is None:
            row = AutonomyPolicy(tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, subject=subject)
            self.db.add(row)
        row.level, row.max_level, row.reason = level, cap, reason or None
        self.db.flush()
        chain.record(self.db, self.ctx, action="autonomy.set", result_state=ResultState.SUCCESS,
                     resource_type="autonomy", resource_id=row.id, detail=f"{subject} -> {level}",
                     payload={"subject": subject, "from": current_level, "to": level, "ceiling": cap})
        return MoResult.ok({"subject": subject, "level": level, "name": LEVELS[level], "ceiling": cap})

    def demote(self, subject: str, reason: str) -> MoResult:
        """Automatic, immediate, one level down. Needs no admin: safety always moves the cautious way."""
        level, cap, matched = self.policy_for(subject)
        new = max(0, level - 1)
        row = (self.db.query(AutonomyPolicy)
               .filter(AutonomyPolicy.tenant_id == self.ctx.tenant_id, AutonomyPolicy.subject == subject).first())
        if row is None:
            row = AutonomyPolicy(tenant_id=self.ctx.tenant_id, created_by="system", subject=subject,
                                 level=new, max_level=cap)
            self.db.add(row)
        row.level, row.reason = new, f"auto-demoted: {reason}"
        self.db.flush()
        chain.record(self.db, self.ctx, action="autonomy.demoted", result_state=ResultState.SUCCESS,
                     resource_type="autonomy", resource_id=row.id, detail=reason,
                     payload={"subject": subject, "from": level, "to": new})
        return MoResult.ok({"subject": subject, "level": new})

    def list_policies(self) -> list[dict[str, Any]]:
        return [{"subject": p.subject, "level": p.level, "name": LEVELS[p.level], "ceiling": p.max_level,
                 "reason": p.reason} for p in sorted(self._policies(), key=lambda p: p.subject)]

    # ── shadow learning ─────────────────────────────────────────────────────

    def propose(self, subject: str, action: str, proposal: dict[str, Any]) -> MoResult:
        """MO records what it *would* do. Nothing is executed."""
        rec = ShadowRecord(tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, subject=subject,
                           action=action, proposal_json=json.dumps(chain.redact(proposal), default=str))
        self.db.add(rec)
        self.db.flush()
        return MoResult.ok({"shadow_id": rec.id, "executed": False})

    def record_decision(self, shadow_id: str, human: dict[str, Any], *, agreed: Optional[bool] = None) -> MoResult:
        rec = self.db.get(ShadowRecord, shadow_id)
        if rec is None or rec.tenant_id != self.ctx.tenant_id:
            return MoResult(ResultState.FAILED, "No such shadow record.")
        if rec.decided_at is not None:
            return MoResult(ResultState.BLOCKED, "A decision was already recorded for this proposal.")
        proposal = json.loads(rec.proposal_json)
        rec.human_json = json.dumps(chain.redact(human), default=str)
        rec.agreed = agreed if agreed is not None else _same(proposal, human)
        rec.decided_at = datetime.utcnow()
        self.db.flush()
        return MoResult.ok({"shadow_id": rec.id, "agreed": rec.agreed})

    def evidence(self, subject: str) -> dict[str, Any]:
        rows = (self.db.query(ShadowRecord)
                .filter(ShadowRecord.tenant_id == self.ctx.tenant_id, ShadowRecord.subject == subject,
                        ShadowRecord.decided_at.isnot(None)).all())
        agreed = sum(1 for r in rows if r.agreed)
        rate = agreed / len(rows) if rows else 0.0
        level, cap, _ = self.policy_for(subject)
        blockers = []
        if len(rows) < MIN_SAMPLES_FOR_PROMOTION:
            blockers.append(f"needs {MIN_SAMPLES_FOR_PROMOTION - len(rows)} more decided samples")
        if rate < MIN_AGREEMENT_FOR_PROMOTION:
            blockers.append(f"agreement {rate:.0%} is below {MIN_AGREEMENT_FOR_PROMOTION:.0%}")
        if level >= cap:
            blockers.append(f"already at the ceiling of level {cap}")
        return {"subject": subject, "samples": len(rows), "agreed": agreed, "agreement_rate": round(rate, 3),
                "level": level, "ceiling": cap, "eligible": not blockers, "blockers": blockers}

    def promote(self, subject: str) -> MoResult:
        """One level up, only with evidence. Refuses rather than rounding evidence up."""
        ev = self.evidence(subject)
        if not ev["eligible"]:
            return MoResult(ResultState.BLOCKED, "Promotion refused: " + "; ".join(ev["blockers"]) + ".", meta=ev)
        return self.set_policy(subject, ev["level"] + 1, reason=f"promoted on {ev['samples']} samples "
                                                              f"at {ev['agreement_rate']:.0%} agreement")


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
