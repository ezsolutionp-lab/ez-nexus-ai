"""
MO NEXUS OMEGA — Voice intent resolution.

Turns a spoken command into a typed Intent with slots, a confidence score, and
the risk tier the action carries. Deterministic and rule-based, so it works with
no model provider configured and can be unit-tested exhaustively; a model
provider, when present, is used only to disambiguate what the rules could not
resolve — it never overrides a confident rule match.

Every intent declares the scope it needs and whether it is approval-gated, so
the governance decision is data attached to the intent rather than a branch
somewhere in a handler.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from ..approvals.engine import RiskTier


class IntentName(str, Enum):
    # System / observability
    SYSTEM_STATUS = "system.status"
    SYSTEM_CAPABILITIES = "system.capabilities"
    SAFE_MODE_ON = "system.safe_mode.enable"
    SAFE_MODE_OFF = "system.safe_mode.disable"
    AUDIT_VERIFY = "audit.verify"
    AUDIT_RECENT = "audit.recent"
    COST_REPORT = "cost.report"

    # Builder
    BUILD_PROJECT = "builder.create_project"
    LIST_PROJECTS = "builder.list_projects"
    DESCRIBE_PROJECT = "builder.describe_project"
    RUN_BUILD = "builder.build"
    SHOW_PREVIEW = "builder.preview"
    EXPORT_SOURCE = "builder.export"
    DEPLOY = "builder.deploy"
    CANCEL_DEPLOY = "builder.deploy.cancel"

    # Agents
    LIST_AGENTS = "agent.list"
    AGENT_STATUS = "agent.status"
    DISABLE_AGENT = "agent.disable"

    # Approvals
    LIST_APPROVALS = "approval.list"
    GRANT_APPROVAL = "approval.grant"

    # Tools / workforce
    LIST_TOOLS = "tool.list"

    # Conversation control
    HELP = "conversation.help"
    REPEAT = "conversation.repeat"
    CANCEL = "conversation.cancel"
    UNKNOWN = "conversation.unknown"


@dataclass(frozen=True)
class IntentSpec:
    """What an intent needs in order to run, as data."""

    name: IntentName
    summary: str
    required_scope: Optional[str] = None
    risk_tier: str = RiskTier.LOW
    requires_approval: bool = False
    requires_mfa: bool = False
    # Voice is never allowed to perform these, whatever the speaker's authority.
    voice_forbidden: bool = False
    forbidden_reason: str = ""
    slots: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


# The registry. `voice_forbidden` is the important column: some actions are
# deliberately unreachable by voice even for an administrator, because a spoken
# command is the weakest form of intent confirmation MO accepts.
INTENT_SPECS: dict[IntentName, IntentSpec] = {
    IntentName.SYSTEM_STATUS: IntentSpec(
        IntentName.SYSTEM_STATUS, "Report platform and tenant health.",
        required_scope="builder:read",
        examples=("check production health", "what's the system status", "how are we doing"),
    ),
    IntentName.SYSTEM_CAPABILITIES: IntentSpec(
        IntentName.SYSTEM_CAPABILITIES, "Report what MO can and cannot do right now.",
        required_scope="builder:read",
        examples=("what can you do", "list your capabilities", "what are you able to do"),
    ),
    IntentName.SAFE_MODE_ON: IntentSpec(
        IntentName.SAFE_MODE_ON, "Suspend all write operations for the tenant (kill switch).",
        required_scope="*", risk_tier=RiskTier.HIGH, requires_mfa=True,
        examples=("enable safe mode", "stop everything", "shut it down", "emergency stop"),
    ),
    IntentName.SAFE_MODE_OFF: IntentSpec(
        IntentName.SAFE_MODE_OFF, "Resume write operations for the tenant.",
        required_scope="*", risk_tier=RiskTier.HIGH, requires_approval=True, requires_mfa=True,
        examples=("disable safe mode", "resume operations"),
    ),
    IntentName.AUDIT_VERIFY: IntentSpec(
        IntentName.AUDIT_VERIFY, "Verify the tenant's audit hash chain.",
        required_scope="*",
        examples=("verify the audit log", "is the audit chain intact"),
    ),
    IntentName.AUDIT_RECENT: IntentSpec(
        IntentName.AUDIT_RECENT, "Read the most recent audit events.",
        required_scope="*", slots=("count",),
        examples=("what happened recently", "read the last ten audit events"),
    ),
    IntentName.COST_REPORT: IntentSpec(
        IntentName.COST_REPORT, "Report model spend and sandbox time.",
        required_scope="builder:read",
        examples=("what has this cost", "show me the spend", "how much have we spent"),
    ),
    IntentName.BUILD_PROJECT: IntentSpec(
        IntentName.BUILD_PROJECT, "Compile a spoken description into a project.",
        required_scope="builder:write", risk_tier=RiskTier.MEDIUM, slots=("description",),
        examples=("build a plumbing company website with online booking",
                  "create a CRM for a dental practice", "make me an invoicing app"),
    ),
    IntentName.LIST_PROJECTS: IntentSpec(
        IntentName.LIST_PROJECTS, "List this tenant's projects.",
        required_scope="builder:read",
        examples=("list my projects", "what projects do I have", "show me the projects"),
    ),
    IntentName.DESCRIBE_PROJECT: IntentSpec(
        IntentName.DESCRIBE_PROJECT, "Describe one project's state.",
        required_scope="builder:read", slots=("project",),
        examples=("tell me about the plumbing platform", "describe the last project"),
    ),
    IntentName.RUN_BUILD: IntentSpec(
        IntentName.RUN_BUILD, "Run the sandboxed build and generated tests.",
        required_scope="builder:write", risk_tier=RiskTier.MEDIUM, slots=("project",),
        examples=("run the tests", "build it", "run the build"),
    ),
    IntentName.SHOW_PREVIEW: IntentSpec(
        IntentName.SHOW_PREVIEW, "Create or show the preview.",
        required_scope="builder:write", slots=("project",),
        examples=("show me the preview", "open the preview"),
    ),
    IntentName.EXPORT_SOURCE: IntentSpec(
        IntentName.EXPORT_SOURCE, "Export the generated source.",
        required_scope="builder:read", slots=("project",),
        examples=("export the source", "give me the code", "download the project"),
    ),
    IntentName.DEPLOY: IntentSpec(
        IntentName.DEPLOY, "Request a deployment. Always approval-gated.",
        required_scope="builder:write", risk_tier=RiskTier.HIGH,
        requires_approval=True, requires_mfa=True, slots=("environment", "project"),
        examples=("deploy staging", "deploy to production", "ship it to staging"),
    ),
    IntentName.CANCEL_DEPLOY: IntentSpec(
        IntentName.CANCEL_DEPLOY, "Cancel a pending deployment request.",
        required_scope="builder:write", slots=("project",),
        examples=("stop the deployment", "cancel the deploy", "abort the rollout"),
    ),
    IntentName.LIST_AGENTS: IntentSpec(
        IntentName.LIST_AGENTS, "List agents and their status.",
        required_scope="builder:read", slots=("project",),
        examples=("list the agents", "what agents do I have"),
    ),
    IntentName.AGENT_STATUS: IntentSpec(
        IntentName.AGENT_STATUS, "Report one agent's test status.",
        required_scope="builder:read", slots=("agent",),
        examples=("what's the booking agent doing", "status of the dispatch agent"),
    ),
    IntentName.DISABLE_AGENT: IntentSpec(
        IntentName.DISABLE_AGENT, "Kill-switch an agent.",
        required_scope="*", risk_tier=RiskTier.HIGH, requires_mfa=True, slots=("agent",),
        examples=("disable the booking agent", "kill the dispatch agent"),
    ),
    IntentName.LIST_APPROVALS: IntentSpec(
        IntentName.LIST_APPROVALS, "List pending approvals.",
        required_scope="builder:read",
        examples=("what needs approval", "list pending approvals"),
    ),
    IntentName.GRANT_APPROVAL: IntentSpec(
        IntentName.GRANT_APPROVAL, "Approve a pending request.",
        required_scope="*", risk_tier=RiskTier.CRITICAL,
        voice_forbidden=True,
        forbidden_reason=(
            "Approving a high-impact action by voice is not permitted. A spoken "
            "command is the weakest confirmation MO accepts and cannot be "
            "attributed to a person without speaker verification, which is not "
            "configured. Approve it in the console instead."
        ),
        slots=("approval_id",),
        examples=("approve the deployment", "grant the approval"),
    ),
    IntentName.LIST_TOOLS: IntentSpec(
        IntentName.LIST_TOOLS, "List registered tools and their gating.",
        required_scope="builder:read",
        examples=("list the tools", "what tools are registered"),
    ),
    IntentName.HELP: IntentSpec(
        IntentName.HELP, "Explain what can be said.",
        examples=("help", "what can I say", "give me some examples"),
    ),
    IntentName.REPEAT: IntentSpec(
        IntentName.REPEAT, "Repeat the last response.",
        examples=("repeat that", "say that again", "what did you say"),
    ),
    IntentName.CANCEL: IntentSpec(
        IntentName.CANCEL, "Abandon the current exchange.",
        examples=("never mind", "cancel", "forget it", "stop"),
    ),
    IntentName.UNKNOWN: IntentSpec(
        IntentName.UNKNOWN, "Nothing matched.",
    ),
}


@dataclass
class Intent:
    name: IntentName
    confidence: float
    slots: dict[str, Any] = field(default_factory=dict)
    transcript: str = ""
    matched_pattern: str = ""
    provenance: str = "RULE_BASED"      # RULE_BASED | MODEL_ASSISTED
    alternatives: list[tuple[IntentName, float]] = field(default_factory=list)

    @property
    def spec(self) -> IntentSpec:
        return INTENT_SPECS[self.name]

    def to_dict(self) -> dict[str, Any]:
        spec = self.spec
        return {
            "intent": self.name.value,
            "confidence": round(self.confidence, 3),
            "slots": self.slots,
            "transcript": self.transcript,
            "provenance": self.provenance,
            "summary": spec.summary,
            "risk_tier": spec.risk_tier,
            "requires_approval": spec.requires_approval,
            "requires_mfa": spec.requires_mfa,
            "voice_forbidden": spec.voice_forbidden,
            "required_scope": spec.required_scope,
            "alternatives": [{"intent": n.value, "confidence": round(c, 3)}
                             for n, c in self.alternatives],
        }


# ── Grammar ──────────────────────────────────────────────────────────────────
#
# Each rule is (intent, regex, confidence, slot_extractor). Order matters only
# for tie-breaking; every rule is evaluated and the best score wins, with the
# runners-up reported as alternatives so a near-miss is visible rather than lost.

_ENVIRONMENTS = {
    "production": ("production", "prod", "live"),
    "staging": ("staging", "stage", "test environment"),
}


def _environment_slot(match: re.Match, text: str) -> dict[str, Any]:
    lowered = text.lower()
    for canonical, synonyms in _ENVIRONMENTS.items():
        if any(re.search(rf"\b{re.escape(s)}\b", lowered) for s in synonyms):
            return {"environment": canonical}
    return {}


def _description_slot(match: re.Match, text: str) -> dict[str, Any]:
    """Everything after the build verb is the description."""
    described = (match.groupdict().get("description") or "").strip(" .,")
    return {"description": described} if described else {}


def _count_slot(match: re.Match, text: str) -> dict[str, Any]:
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
             "twenty": 20, "fifty": 50, "hundred": 100}
    digits = re.search(r"\b(\d{1,3})\b", text)
    if digits:
        return {"count": int(digits.group(1))}
    for word, value in words.items():
        if re.search(rf"\b{word}\b", text.lower()):
            return {"count": value}
    return {}


def _named_slot(slot: str) -> Callable[[re.Match, str], dict[str, Any]]:
    def extract(match: re.Match, text: str) -> dict[str, Any]:
        value = (match.groupdict().get(slot) or "").strip(" .,")
        return {slot: value} if value else {}
    return extract


_Rule = tuple[IntentName, str, float, Optional[Callable[[re.Match, str], dict[str, Any]]]]

GRAMMAR: tuple[_Rule, ...] = (
    # Conversation control — checked with high confidence because they are short
    # and must not be swallowed by a broader rule.
    (IntentName.CANCEL, r"^(never ?mind|forget it|cancel that|nothing|no thanks)\b", 0.97, None),
    (IntentName.REPEAT, r"\b(repeat that|say that again|what did you say|come again)\b", 0.96, None),
    (IntentName.HELP, r"^(help|what can i say|what can you do|give me examples?)\b", 0.9, None),
    (IntentName.SYSTEM_CAPABILITIES, r"\b(what (are your |can you do)|list your )?capabilit(y|ies)\b", 0.92, None),
    (IntentName.SYSTEM_CAPABILITIES, r"\bwhat (can|are) you (do|able to do|capable of)\b", 0.88, None),

    # Deployment — before the generic build rules so "deploy" never reads as "build".
    (IntentName.CANCEL_DEPLOY,
     r"\b(stop|cancel|abort|halt)\b.{0,20}\b(deploy|deployment|rollout|release)\b", 0.96,
     _environment_slot),
    (IntentName.DEPLOY,
     r"\b(deploy|ship|release|push)\b.{0,30}\b(to\s+)?(production|prod|live|staging|stage)\b", 0.95,
     _environment_slot),
    (IntentName.DEPLOY, r"\b(deploy|ship it|go live)\b", 0.72, _environment_slot),

    # Safe mode / kill switch
    (IntentName.SAFE_MODE_ON,
     r"\b(enable|turn on|activate|engage)\b.{0,15}\bsafe ?mode\b", 0.97, None),
    (IntentName.SAFE_MODE_ON,
     r"\b(emergency stop|shut (it |everything )?down|stop everything|kill switch)\b", 0.93, None),
    (IntentName.SAFE_MODE_OFF,
     r"\b(disable|turn off|deactivate|lift)\b.{0,15}\bsafe ?mode\b", 0.97, None),
    (IntentName.SAFE_MODE_OFF, r"\bresume (operations|writes|normal)\b", 0.9, None),

    # Build pipeline
    (IntentName.RUN_BUILD, r"\brun\b.{0,15}\b(the )?(tests?|build|suite)\b", 0.95, None),
    (IntentName.RUN_BUILD, r"\b(rebuild|build it|compile it)\b", 0.88, None),
    (IntentName.SHOW_PREVIEW,
     r"\b(show|open|see|view)\b.{0,20}\bpreview\b", 0.95, None),
    (IntentName.EXPORT_SOURCE,
     r"\b(export|download|give me)\b.{0,20}\b(source|code|project|zip)\b", 0.93, None),

    # Project creation — the description slot is the rest of the utterance.
    (IntentName.BUILD_PROJECT,
     r"\b(?:build|create|make|generate|set ?up|spin ?up)\s+(?:me\s+)?(?:a|an|the)?\s*(?P<description>.+)",
     0.85, _description_slot),
    (IntentName.BUILD_PROJECT,
     r"\bi (?:want|need)\s+(?:a|an)?\s*(?P<description>.+)", 0.7, _description_slot),

    (IntentName.LIST_PROJECTS,
     r"\b(list|show|what)\b.{0,15}\bprojects?\b", 0.94, None),
    (IntentName.DESCRIBE_PROJECT,
     r"\b(tell me about|describe|what(?:'s| is) the status of)\s+(?:the\s+)?(?P<project>.+)",
     0.86, _named_slot("project")),

    # Agents
    (IntentName.DISABLE_AGENT,
     r"\b(disable|kill|stop|shut ?down)\b.{0,20}\b(?P<agent>[\w\s]+?)\s+agent\b", 0.95,
     _named_slot("agent")),
    (IntentName.LIST_AGENTS, r"\b(list|show|what)\b.{0,15}\bagents?\b", 0.93, None),
    (IntentName.AGENT_STATUS,
     r"\b(status of|what(?:'s| is))\b.{0,20}\b(?P<agent>[\w\s]+?)\s+agent\b", 0.88,
     _named_slot("agent")),

    # Approvals
    (IntentName.GRANT_APPROVAL,
     r"\b(approve|grant|authorise|authorize|sign off)\b", 0.94, None),
    (IntentName.LIST_APPROVALS,
     r"\b(what needs|list|show|pending)\b.{0,15}\bapprovals?\b", 0.94, None),

    # Observability
    (IntentName.AUDIT_VERIFY,
     r"\b(verify|check)\b.{0,20}\baudit\b", 0.95, None),
    (IntentName.AUDIT_RECENT,
     r"\b(recent|last|latest)\b.{0,20}\b(audit|events?|activity)\b", 0.9, _count_slot),
    (IntentName.AUDIT_RECENT, r"\bwhat happened\b", 0.75, _count_slot),
    (IntentName.COST_REPORT,
     r"\b(cost|spend|spent|billing|how much)\b", 0.9, None),
    (IntentName.LIST_TOOLS, r"\b(list|show|what)\b.{0,15}\btools?\b", 0.92, None),
    (IntentName.SYSTEM_STATUS,
     r"\b(check|show|what(?:'s| is))\b.{0,25}\b(health|status|healthy)\b", 0.94, None),
    (IntentName.SYSTEM_STATUS, r"\bhow are (we|things) (doing|going)\b", 0.8, None),
)


def resolve_intent(text: str, *, min_confidence: float = 0.6) -> Intent:
    """
    Score every grammar rule and return the best match.

    Returns UNKNOWN below `min_confidence` rather than forcing a guess — a
    misrouted voice command is worse than asking again.
    """
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return Intent(IntentName.UNKNOWN, 0.0, transcript=text or "")

    lowered = cleaned.lower()
    scored: list[tuple[float, IntentName, dict[str, Any], str]] = []

    for intent_name, pattern, confidence, extractor in GRAMMAR:
        match = re.search(pattern, lowered)
        if not match:
            continue
        slots: dict[str, Any] = {}
        if extractor is not None:
            # Extract against the original casing so slot values read naturally.
            original = re.search(pattern, cleaned, re.IGNORECASE) or match
            slots = extractor(original, cleaned)
        scored.append((confidence, intent_name, slots, pattern))

    if not scored:
        return Intent(IntentName.UNKNOWN, 0.0, transcript=cleaned)

    scored.sort(key=lambda row: row[0], reverse=True)
    best_confidence, best_name, best_slots, best_pattern = scored[0]

    alternatives: list[tuple[IntentName, float]] = []
    for confidence, name, _slots, _pattern in scored[1:]:
        if name != best_name and not any(name == a[0] for a in alternatives):
            alternatives.append((name, confidence))
    alternatives = alternatives[:3]

    if best_confidence < min_confidence:
        return Intent(IntentName.UNKNOWN, best_confidence, transcript=cleaned,
                      alternatives=[(best_name, best_confidence)] + alternatives)

    return Intent(
        name=best_name, confidence=best_confidence, slots=best_slots,
        transcript=cleaned, matched_pattern=best_pattern, alternatives=alternatives,
    )


def missing_slots(intent: Intent) -> list[str]:
    """Declared slots the utterance did not fill — what to ask a follow-up about."""
    return [s for s in intent.spec.slots if s not in intent.slots]


def help_examples(limit_per_intent: int = 1) -> list[dict[str, str]]:
    """Spoken examples, for the help intent and the console's hint list."""
    out = []
    for spec in INTENT_SPECS.values():
        if spec.name in (IntentName.UNKNOWN,) or not spec.examples:
            continue
        for example in spec.examples[:limit_per_intent]:
            out.append({"say": example, "does": spec.summary, "intent": spec.name.value})
    return out
