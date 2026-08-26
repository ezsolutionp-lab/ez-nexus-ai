"""
MO NEXUS OMEGA — BuildIntent and the Builder's type system.

A BuildIntent is the compiler's only input. It carries the tenant and requester
so every downstream artifact inherits an owner, and it validates its own fields
so an unsupported target or stack is rejected at the door rather than halfway
through generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from ..context import RequestContext
from ..errors import MoError, ResultState


class BuildMode(str, Enum):
    NO_CODE = "NO_CODE"
    LOW_CODE = "LOW_CODE"
    FULL_CODE = "FULL_CODE"
    HYBRID = "HYBRID"


class TargetType(str, Enum):
    WEBSITE = "WEBSITE"
    WEB_APP = "WEB_APP"
    SAAS = "SAAS"
    MOBILE_APP = "MOBILE_APP"
    DESKTOP_APP = "DESKTOP_APP"
    API = "API"
    MICROSERVICE = "MICROSERVICE"
    AI_AGENT = "AI_AGENT"
    AGENT_WORKFORCE = "AGENT_WORKFORCE"
    WORKFLOW = "WORKFLOW"
    INTERNAL_TOOL = "INTERNAL_TOOL"
    CUSTOM_PLATFORM = "CUSTOM_PLATFORM"


class CompilerStage(str, Enum):
    """Ordered stages. Each produces a structured, versioned artifact."""

    INTENT = "INTENT"
    REQUIREMENTS = "REQUIREMENTS"
    FUNCTIONAL_SPEC = "FUNCTIONAL_SPEC"
    NONFUNCTIONAL_SPEC = "NONFUNCTIONAL_SPEC"
    ARCHITECTURE = "ARCHITECTURE"
    DATA_MODEL = "DATA_MODEL"
    API_MODEL = "API_MODEL"
    UI_MODEL = "UI_MODEL"
    AGENT_MODEL = "AGENT_MODEL"
    WORKFLOW_MODEL = "WORKFLOW_MODEL"
    INTEGRATION_MODEL = "INTEGRATION_MODEL"
    INFRASTRUCTURE_MODEL = "INFRASTRUCTURE_MODEL"
    TEST_MODEL = "TEST_MODEL"
    SECURITY_MODEL = "SECURITY_MODEL"
    DEPLOYMENT_MODEL = "DEPLOYMENT_MODEL"

    @classmethod
    def ordered(cls) -> list["CompilerStage"]:
        return list(cls)


# Stacks with an implemented generator. Nothing else may be requested — claiming
# an adapter that does not exist is exactly the failure mode this guards.
IMPLEMENTED_STACKS: frozenset[str] = frozenset({"fastapi_react"})

# Declared-but-unimplemented adapters, surfaced honestly to callers.
PLANNED_STACKS: frozenset[str] = frozenset({
    "nextjs_fastapi", "django_react", "nestjs_react", "flutter_fastapi", "spring_react",
})


def slugify(text: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:max_length].rstrip("-")) or "project"


@dataclass
class BuildIntent:
    """What the requester asked for, plus the authority under which to build it."""

    prompt: str
    tenant_id: str
    requested_by: str
    project_id: Optional[str] = None
    name: Optional[str] = None
    source_channel: str = "API"
    build_mode: BuildMode = BuildMode.FULL_CODE
    target_type: TargetType = TargetType.WEB_APP
    target_platform: str = "web"
    preferred_stack: str = "fastapi_react"
    constraints: dict[str, Any] = field(default_factory=dict)
    budget_usd: Optional[float] = None
    deadline: Optional[str] = None
    security_level: str = "STANDARD"          # STANDARD | ELEVATED | REGULATED
    data_classification: str = "INTERNAL"
    deployment_target: str = "preview"        # preview | staging | production

    def __post_init__(self) -> None:
        if not (self.prompt or "").strip():
            raise MoError(ResultState.FAILED, "A build intent needs a prompt describing what to build.")
        if len(self.prompt) > 20_000:
            raise MoError(ResultState.FAILED, "Prompt exceeds the 20,000 character limit.")
        if isinstance(self.build_mode, str):
            self.build_mode = BuildMode(self.build_mode)
        if isinstance(self.target_type, str):
            self.target_type = TargetType(self.target_type)
        if self.preferred_stack not in IMPLEMENTED_STACKS:
            if self.preferred_stack in PLANNED_STACKS:
                raise MoError(
                    ResultState.BLOCKED,
                    f"Stack '{self.preferred_stack}' is planned but has no generator yet. "
                    f"Implemented stacks: {', '.join(sorted(IMPLEMENTED_STACKS))}.",
                    planned=True,
                )
            raise MoError(
                ResultState.FAILED,
                f"Unknown stack '{self.preferred_stack}'. "
                f"Implemented: {', '.join(sorted(IMPLEMENTED_STACKS))}.",
            )
        if self.deployment_target not in {"preview", "staging", "production"}:
            raise MoError(ResultState.FAILED, f"Unknown deployment target '{self.deployment_target}'.")
        if not self.name:
            self.name = _derive_name(self.prompt)

    @property
    def slug(self) -> str:
        return slugify(self.name or self.prompt)

    @classmethod
    def from_request(cls, ctx: RequestContext, payload: dict[str, Any]) -> "BuildIntent":
        """Build an intent from an HTTP/voice payload, pinned to the caller's tenant.

        The tenant and requester come from the authenticated context, never from
        the request body — otherwise a caller could build into another tenant.
        """
        allowed = {
            "prompt", "name", "build_mode", "target_type", "target_platform",
            "preferred_stack", "constraints", "budget_usd", "deadline",
            "security_level", "deployment_target",
        }
        kwargs = {k: v for k, v in payload.items() if k in allowed and v is not None}
        return cls(
            tenant_id=ctx.tenant_id,
            requested_by=ctx.actor_id,
            source_channel=ctx.source_channel,
            data_classification=ctx.data_classification,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "tenant_id": self.tenant_id,
            "requested_by": self.requested_by, "source_channel": self.source_channel,
            "prompt": self.prompt, "name": self.name, "slug": self.slug,
            "build_mode": self.build_mode.value, "target_type": self.target_type.value,
            "target_platform": self.target_platform, "preferred_stack": self.preferred_stack,
            "constraints": self.constraints, "budget_usd": self.budget_usd,
            "deadline": self.deadline, "security_level": self.security_level,
            "data_classification": self.data_classification,
            "deployment_target": self.deployment_target,
        }


_NAME_STOPWORDS = {
    "build", "me", "a", "an", "the", "please", "create", "make", "with", "for",
    "and", "that", "has", "have", "including", "include", "app", "application",
}


def _derive_name(prompt: str) -> str:
    """Take a readable project name from the opening clause of the prompt."""
    head = re.split(r"[.\n,]|\bwith\b|\bthat\b|\bincluding\b", prompt.strip(), maxsplit=1)[0]
    words = [w for w in re.findall(r"[A-Za-z0-9]+", head) if w.lower() not in _NAME_STOPWORDS]
    if not words:
        return "MO Project"
    return " ".join(w.capitalize() for w in words[:6])
