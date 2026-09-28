"""
MO NEXUS OMEGA — Requirement engine.

Turns a plain-English prompt into a structured ProjectSpec: requirements,
assumptions, data models, pages, APIs, agents, workflows and integrations.

Two paths, and the difference is always visible in the output:

  RULE_BASED      deterministic catalogue matching. Always runs. No credentials.
  MODEL_ASSISTED  the rule-based spec plus model-derived extras.

When no model provider is configured the engine still produces a complete spec
and records `model_enrichment` as CREDENTIAL_REQUIRED. It never silently claims
a model shaped the requirements when none did.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..errors import MoResult, ResultState
from ..modelfabric.router import ModelRequest, ModelRouter, get_router
from .catalog import (
    DOMAIN_PROFILES, MODULES, MODULES_BY_KEY, AgentSpec, IntegrationSpec, ModelSpec,
    Module, PageSpec, RequirementSpec, WorkflowSpec,
)
from .intent import BuildIntent, TargetType


@dataclass
class Assumption:
    statement: str
    rationale: str
    impact: str = "LOW"          # LOW | MEDIUM | HIGH

    def to_dict(self) -> dict[str, Any]:
        return {"statement": self.statement, "rationale": self.rationale, "impact": self.impact}


@dataclass
class BlockingQuestion:
    """Asked only when proceeding either way would produce materially different work."""

    key: str
    question: str
    why_blocking: str

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "question": self.question, "why_blocking": self.why_blocking}


@dataclass
class ProjectSpec:
    """The compiler's structured view of a project, versioned per generation."""

    intent: BuildIntent
    domain: Optional[str] = None
    modules: list[str] = field(default_factory=list)
    requirements: list[RequirementSpec] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    questions: list[BlockingQuestion] = field(default_factory=list)
    models: list[ModelSpec] = field(default_factory=list)
    pages: list[PageSpec] = field(default_factory=list)
    agents: list[AgentSpec] = field(default_factory=list)
    workflows: list[WorkflowSpec] = field(default_factory=list)
    integrations: list[IntegrationSpec] = field(default_factory=list)
    provenance: str = "RULE_BASED"
    model_enrichment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "domain": self.domain,
            "modules": self.modules,
            "provenance": self.provenance,
            "model_enrichment": self.model_enrichment,
            "requirements": [
                {"category": r.category, "key": r.key, "statement": r.statement,
                 "acceptance": r.acceptance, "priority": r.priority}
                for r in self.requirements
            ],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "questions": [q.to_dict() for q in self.questions],
            "models": [m.to_dict() for m in self.models],
            "pages": [
                {"name": p.name, "route": p.route, "title": p.title, "kind": p.kind,
                 "requires_auth": p.requires_auth, "sections": list(p.sections)}
                for p in self.pages
            ],
            "agents": [
                {"name": a.name, "role": a.role, "purpose": a.purpose,
                 "instructions": a.instructions, "tools": list(a.tools),
                 "autonomy": a.autonomy, "approval_gates": list(a.approval_gates),
                 "capability": a.capability}
                for a in self.agents
            ],
            "workflows": [
                {"name": w.name, "trigger_type": w.trigger_type, "nodes": [dict(n) for n in w.nodes]}
                for w in self.workflows
            ],
            "integrations": [
                {"provider": i.provider, "capability": i.capability,
                 "auth_kind": i.auth_kind, "credential_env_var": i.credential_env_var}
                for i in self.integrations
            ],
        }

    @property
    def counts(self) -> dict[str, int]:
        return {
            "modules": len(self.modules), "requirements": len(self.requirements),
            "assumptions": len(self.assumptions), "models": len(self.models),
            "pages": len(self.pages), "agents": len(self.agents),
            "workflows": len(self.workflows), "integrations": len(self.integrations),
        }


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def detect_domain(prompt: str) -> Optional[tuple[str, str]]:
    """Return (domain_key, matched_signal) for the first matching domain profile."""
    norm = _normalise(prompt)
    for key, profile in DOMAIN_PROFILES.items():
        for signal in profile["signals"]:
            if signal in norm:
                return key, signal
    return None


def detect_modules(prompt: str) -> dict[str, str]:
    """Return {module_key: matched_signal} for modules explicitly named in the prompt."""
    norm = _normalise(prompt)
    found: dict[str, str] = {}
    for module in MODULES:
        for signal in module.signals:
            if signal in norm:
                found[module.key] = signal
                break
    return found


class RequirementEngine:
    """Deterministic first, model-enriched second — and it says which it did."""

    def __init__(self, router: Optional[ModelRouter] = None):
        self._router = router

    @property
    def router(self) -> ModelRouter:
        return self._router if self._router is not None else get_router()

    def analyse(self, intent: BuildIntent, *, use_model: bool = True) -> ProjectSpec:
        spec = self._rule_based(intent)
        if use_model:
            self._enrich(spec)
        return spec

    # ── deterministic path ───────────────────────────────────────────────────

    def _rule_based(self, intent: BuildIntent) -> ProjectSpec:
        explicit = detect_modules(intent.prompt)
        domain_hit = detect_domain(intent.prompt)
        spec = ProjectSpec(intent=intent, domain=domain_hit[0] if domain_hit else None)

        selected: dict[str, str] = dict(explicit)

        # Domain baseline — every inferred module becomes a recorded assumption.
        if domain_hit:
            domain_key, signal = domain_hit
            profile = DOMAIN_PROFILES[domain_key]
            inferred = [k for k in profile["modules"] if k not in explicit]
            for key in inferred:
                selected[key] = f"domain:{domain_key}"
            if inferred:
                spec.assumptions.append(Assumption(
                    statement=(
                        f"Included {len(inferred)} module(s) not named in the request: "
                        + ", ".join(MODULES_BY_KEY[k].label for k in inferred) + "."
                    ),
                    rationale=f"The prompt mentions '{signal}', which matches the "
                              f"{domain_key.replace('_', ' ')} profile. {profile['rationale']}",
                    impact="MEDIUM",
                ))

        # Target type implies structure even with no domain match.
        if intent.target_type in (TargetType.WEBSITE,) and "website" not in selected:
            selected["website"] = "target_type"
        if intent.target_type in (TargetType.SAAS, TargetType.WEB_APP) and "auth" not in selected:
            selected["auth"] = "target_type"
            spec.assumptions.append(Assumption(
                statement="Included authentication and roles.",
                rationale=f"Target type {intent.target_type.value} implies signed-in users.",
                impact="LOW",
            ))

        # Dependency closure — a portal without auth is not shippable.
        if {"customer_portal", "technician_workflow", "crm", "dispatch"} & set(selected):
            selected.setdefault("auth", "implied:protected-surface")
        if "payments" in selected:
            selected.setdefault("invoicing", "implied:payments-need-invoices")
        if "booking" in selected:
            selected.setdefault("notifications", "implied:booking-confirmation")

        spec.modules = sorted(selected)

        seen_req: set[str] = set()
        seen_model: set[str] = set()
        seen_page: set[str] = set()
        seen_agent: set[str] = set()
        seen_integration: set[str] = set()

        for key in spec.modules:
            module: Module = MODULES_BY_KEY[key]
            for r in module.requirements:
                if r.key not in seen_req:
                    seen_req.add(r.key)
                    spec.requirements.append(r)
            for m in module.models:
                if m.name not in seen_model:
                    seen_model.add(m.name)
                    spec.models.append(m)
            for p in module.pages:
                if p.route not in seen_page:
                    seen_page.add(p.route)
                    spec.pages.append(p)
            for a in module.agents:
                if a.name not in seen_agent:
                    seen_agent.add(a.name)
                    spec.agents.append(a)
            for w in module.workflows:
                spec.workflows.append(w)
            for i in module.integrations:
                token = f"{i.provider}:{i.capability}"
                if token not in seen_integration:
                    seen_integration.add(token)
                    spec.integrations.append(i)

        spec.requirements.extend(self._nonfunctional_baseline(intent))
        spec.questions = self._blocking_questions(intent, spec)
        return spec

    def _nonfunctional_baseline(self, intent: BuildIntent) -> list[RequirementSpec]:
        """Security and operations requirements every generated project carries."""
        base = [
            RequirementSpec("NONFUNCTIONAL", "ops.health",
                            "The service exposes liveness and readiness endpoints.",
                            "GET /health returns 200 with a status body.", "MUST"),
            RequirementSpec("NONFUNCTIONAL", "ops.structured_logs",
                            "Requests are logged with a correlation id.",
                            "Every log line carries request_id.", "SHOULD"),
            RequirementSpec("SECURITY", "sec.no_hardcoded_secrets",
                            "No secret is committed to the repository.",
                            "The secret scan finds no credential literal.", "MUST"),
            RequirementSpec("SECURITY", "sec.input_validation",
                            "All external input is schema-validated before use.",
                            "Malformed payloads return 422 without reaching the database.", "MUST"),
            RequirementSpec("SECURITY", "sec.parameterised_sql",
                            "Database access is parameterised through the ORM.",
                            "No string-formatted SQL appears in generated source.", "MUST"),
            RequirementSpec("SECURITY", "sec.rate_limit",
                            "Write and auth endpoints are rate limited.",
                            "Exceeding the limit returns 429.", "MUST"),
        ]
        if intent.security_level in ("ELEVATED", "REGULATED"):
            base.append(RequirementSpec(
                "COMPLIANCE", "sec.audit_trail",
                "Every state change is written to an append-only audit trail.",
                "Each mutation produces one audit record naming the actor.", "MUST"))
        if intent.data_classification == "RESTRICTED":
            base.append(RequirementSpec(
                "COMPLIANCE", "sec.restricted_data",
                "Restricted data is never sent to an unapproved model provider.",
                "Model calls carrying restricted data are POLICY_DENIED by default.", "MUST"))
        return base

    def _blocking_questions(self, intent: BuildIntent, spec: ProjectSpec) -> list[BlockingQuestion]:
        """Only questions where either answer changes what gets built."""
        questions: list[BlockingQuestion] = []
        if intent.deployment_target == "production":
            questions.append(BlockingQuestion(
                key="production_data_residency",
                question="Which region must production data reside in?",
                why_blocking="Region determines the infrastructure template and cannot be "
                             "changed after data is written.",
            ))
        if "payments" in spec.modules:
            questions.append(BlockingQuestion(
                key="payment_provider",
                question="Which payment provider should be used, and who holds the merchant account?",
                why_blocking="No payment adapter is implemented. Charging a customer through the "
                             "wrong provider is not reversible from inside the platform.",
            ))
        return questions

    # ── model-assisted enrichment ────────────────────────────────────────────

    def _enrich(self, spec: ProjectSpec) -> None:
        """Add model-derived requirements. Reports honestly when it cannot run."""
        router = self.router
        if not router.is_configured:
            result = router.missing_credential_result()
            spec.model_enrichment = {
                "state": result.state.value,
                "detail": result.detail,
                "applied": False,
                "note": "Specification is complete from the deterministic catalogue. "
                        "A configured model provider would add project-specific requirements.",
            }
            return

        prompt = (
            "You are refining a software requirements specification.\n\n"
            f"Request: {spec.intent.prompt}\n\n"
            f"Already covered: {', '.join(spec.modules) or 'nothing'}.\n"
            f"Existing requirement keys: {', '.join(r.key for r in spec.requirements)}\n\n"
            "Return ONLY a JSON object of the form "
            '{"requirements":[{"category":"FUNCTIONAL|NONFUNCTIONAL|SECURITY|DATA|COMPLIANCE",'
            '"key":"dotted.key","statement":"...","acceptance":"...","priority":"MUST|SHOULD|COULD"}],'
            '"assumptions":[{"statement":"...","rationale":"...","impact":"LOW|MEDIUM|HIGH"}]}\n'
            "Add at most 8 requirements that are specific to this request and not already covered. "
            "Do not restate the existing keys."
        )
        result: MoResult = router.complete(
            ModelRequest(prompt=prompt, capability="reasoning", max_tokens=2000,
                         data_classification=spec.intent.data_classification)
        )
        if not result.state.is_success:
            spec.model_enrichment = {
                "state": result.state.value, "detail": result.detail, "applied": False,
            }
            return

        parsed = _extract_json(result.data.get("text", ""))
        if parsed is None:
            spec.model_enrichment = {
                "state": ResultState.PARTIAL.value,
                "detail": "The model reply was not valid JSON; the deterministic specification stands unchanged.",
                "applied": False,
            }
            return

        existing = {r.key for r in spec.requirements}
        added = 0
        for item in parsed.get("requirements", [])[:8]:
            key = str(item.get("key", "")).strip()
            if not key or key in existing:
                continue
            spec.requirements.append(RequirementSpec(
                category=str(item.get("category", "FUNCTIONAL")).upper(),
                key=key,
                statement=str(item.get("statement", "")).strip(),
                acceptance=str(item.get("acceptance", "")).strip(),
                priority=str(item.get("priority", "SHOULD")).upper(),
            ))
            existing.add(key)
            added += 1
        for item in parsed.get("assumptions", [])[:5]:
            spec.assumptions.append(Assumption(
                statement=str(item.get("statement", "")).strip(),
                rationale=str(item.get("rationale", "")).strip(),
                impact=str(item.get("impact", "LOW")).upper(),
            ))

        spec.provenance = "MODEL_ASSISTED"
        spec.model_enrichment = {
            "state": ResultState.SUCCESS.value, "applied": True,
            "requirements_added": added,
            "provider": result.meta.get("provider"), "model": result.meta.get("model"),
            "cost_usd": result.meta.get("cost_usd"),
        }


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    text = re.sub(r"^```(?:json)?\s*", "", (text or "").strip())
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
