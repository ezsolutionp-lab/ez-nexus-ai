"""
MO NEXUS OMEGA — Capability policy (MO-owned).

Decides, for a tool + action + declared risk, whether the call is denied outright, needs
strong confirmation, needs ordinary approval, or may proceed. The deny-list and the finance
table are code, not tenant configuration and not prompts: no agent, tenant setting or grant
can lift them. Callers can only *raise* the risk they declare — the gateway takes the higher of
the declared risk and the risk derived from the tool's own registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Risk(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"
    SENSITIVE = "sensitive"


_RISK_ORDER = {Risk.NONE: 0, Risk.READ: 1, Risk.WRITE: 2, Risk.EXTERNAL: 3, Risk.SENSITIVE: 4}
# ToolSpec.risk_level -> the least risk the gateway will accept for that tool.
TOOL_RISK_FLOOR = {"LOW": Risk.NONE, "MEDIUM": Risk.WRITE, "HIGH": Risk.EXTERNAL, "CRITICAL": Risk.SENSITIVE}
# Risk -> the approval tier MO's approval engine applies.
TIER_FOR_RISK = {Risk.READ: "MEDIUM", Risk.WRITE: "MEDIUM", Risk.EXTERNAL: "HIGH", Risk.SENSITIVE: "CRITICAL"}

FORBIDDEN_ACTIONS = frozenset({
    "withdraw_funds", "change_withdrawal_whitelist", "export_credentials",
    "disable_audit", "mint_admin", "bypass_approval", "modify_policy", "escalate_privilege",
})

# Finance: enforced here, server-side, not in prompts.
FINANCE_POLICY = {
    "read_balances": "approval",
    "read_market_data": "approval_if_account_access",
    "place_order": "strong_confirmation",
    "cancel_order": "strong_confirmation",
    "withdraw_funds": "DENY",
    "change_withdrawal_whitelist": "DENY",
    "export_credentials": "DENY",
}

ALLOW, APPROVAL, STRONG_CONFIRM, DENY = "ALLOW", "APPROVAL", "STRONG_CONFIRM", "DENY"


@dataclass(frozen=True)
class Decision:
    verdict: str
    risk: Risk
    tier: str | None
    reason: str

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "risk": self.risk.value, "tier": self.tier, "reason": self.reason}


def higher(a: Risk, b: Risk) -> Risk:
    return a if _RISK_ORDER[a] >= _RISK_ORDER[b] else b


def effective_risk(declared: Risk, tool_risk_level: str | None) -> Risk:
    return higher(declared, TOOL_RISK_FLOOR.get(tool_risk_level or "", Risk.NONE))


def decide(tool: str, action: str, risk: Risk, *, account_access: bool = False) -> Decision:
    name = action.lower()
    if name in FORBIDDEN_ACTIONS or FINANCE_POLICY.get(name) == "DENY":
        return Decision(DENY, risk, None, f"'{action}' is forbidden by MO policy and cannot be authorised.")
    finance = FINANCE_POLICY.get(name)
    if finance == "strong_confirmation":
        return Decision(STRONG_CONFIRM, higher(risk, Risk.SENSITIVE), "CRITICAL",
                        f"'{action}' needs two-party, multi-factor confirmation.")
    if finance == "approval":
        return Decision(APPROVAL, higher(risk, Risk.READ), TIER_FOR_RISK[higher(risk, Risk.READ)],
                        f"'{action}' needs approval.")
    if finance == "approval_if_account_access" and account_access:
        return Decision(APPROVAL, higher(risk, Risk.READ), TIER_FOR_RISK[higher(risk, Risk.READ)],
                        f"'{action}' with account access needs approval.")
    if risk == Risk.NONE:
        return Decision(ALLOW, risk, None, "No side effects; no approval needed.")
    return Decision(APPROVAL, risk, TIER_FOR_RISK[risk], f"{risk.value} actions need approval.")
