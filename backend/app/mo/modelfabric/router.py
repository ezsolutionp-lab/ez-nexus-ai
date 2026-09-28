"""
MO NEXUS OMEGA — Model Fabric.

One router in front of every model provider. Nothing in MO instantiates a
provider SDK directly, which is what makes fallback, budgets, health and
data-classification routing enforceable rather than per-call-site conventions.

When no provider can serve a request the router returns CREDENTIAL_REQUIRED or
PROVIDER_UNAVAILABLE. It never returns a fabricated completion, and it never
returns an error string dressed up as a result.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..errors import MoResult, ResultState


@dataclass
class ModelRequest:
    prompt: str
    system: str = ""
    max_tokens: int = 1024
    temperature: float = 0.2
    capability: str = "general"          # general | code | reasoning | extraction
    data_classification: str = "INTERNAL"
    max_cost_usd: float = 0.50
    timeout_seconds: int = 60


@dataclass
class ModelResponse:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


@dataclass
class ProviderHealth:
    name: str
    configured: bool
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_success_at: Optional[float] = None
    opened_at: Optional[float] = None       # circuit breaker

    circuit_threshold: int = 3
    circuit_cooldown_seconds: int = 60

    @property
    def circuit_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at >= self.circuit_cooldown_seconds:
            return False                     # half-open: allow one probe
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.last_error = None
        self.opened_at = None
        self.last_success_at = time.time()

    def record_failure(self, error: str) -> None:
        self.consecutive_failures += 1
        self.last_error = error
        if self.consecutive_failures >= self.circuit_threshold:
            self.opened_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "configured": self.configured,
            "circuit_open": self.circuit_open,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
        }


class ModelAdapter(ABC):
    """Provider adapter. Implementations must never invent a response."""

    name: str = "adapter"
    credential_env_var: str = ""
    allows_restricted_data: bool = False
    supported_capabilities: frozenset[str] = frozenset({"general"})

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def complete(self, request: ModelRequest) -> ModelResponse: ...


class AnthropicAdapter(ModelAdapter):
    """Claude via the Anthropic SDK. Raises on failure — never returns a stub."""

    name = "anthropic"
    credential_env_var = "ANTHROPIC_API_KEY"
    allows_restricted_data = False
    supported_capabilities = frozenset({"general", "code", "reasoning", "extraction"})

    # Model ids are configurable so a model change is a config change, not a code change.
    MODELS = {
        "general": os.getenv("MO_MODEL_GENERAL", "claude-haiku-4-5-20251001"),
        "code": os.getenv("MO_MODEL_CODE", "claude-sonnet-5"),
        "reasoning": os.getenv("MO_MODEL_REASONING", "claude-sonnet-5"),
        "extraction": os.getenv("MO_MODEL_EXTRACTION", "claude-haiku-4-5-20251001"),
    }
    # USD per 1M tokens. Used for budget accounting only; not billed.
    PRICING = {
        "claude-haiku-4-5-20251001": (1.00, 5.00),
        "claude-sonnet-5": (3.00, 15.00),
    }

    def is_configured(self) -> bool:
        return bool(os.getenv(self.credential_env_var, "").strip())

    def _price(self, model: str, in_tok: int, out_tok: int) -> float:
        rate = self.PRICING.get(model)
        if not rate:
            return 0.0                       # unknown pricing is reported as unknown, not guessed
        return (in_tok / 1_000_000) * rate[0] + (out_tok / 1_000_000) * rate[1]

    def complete(self, request: ModelRequest) -> ModelResponse:
        import anthropic

        model = self.MODELS.get(request.capability, self.MODELS["general"])
        client = anthropic.Anthropic(
            api_key=os.environ[self.credential_env_var], timeout=request.timeout_seconds
        )
        started = time.perf_counter()
        msg = client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system or "You are an MO NEXUS OMEGA engineering agent.",
            messages=[{"role": "user", "content": request.prompt}],
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        in_tok = getattr(msg.usage, "input_tokens", 0)
        out_tok = getattr(msg.usage, "output_tokens", 0)
        return ModelResponse(
            text=text, provider=self.name, model=model,
            input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=self._price(model, in_tok, out_tok), latency_ms=latency_ms,
        )


class OpenAIAdapter(ModelAdapter):
    name = "openai"
    credential_env_var = "OPENAI_API_KEY"
    supported_capabilities = frozenset({"general", "code", "extraction"})

    def is_configured(self) -> bool:
        return bool(os.getenv(self.credential_env_var, "").strip())

    def complete(self, request: ModelRequest) -> ModelResponse:
        from openai import OpenAI

        model = os.getenv("MO_OPENAI_MODEL", "gpt-4o-mini")
        client = OpenAI(api_key=os.environ[self.credential_env_var], timeout=request.timeout_seconds)
        started = time.perf_counter()
        resp = client.chat.completions.create(
            model=model, max_tokens=request.max_tokens, temperature=request.temperature,
            messages=(
                ([{"role": "system", "content": request.system}] if request.system else [])
                + [{"role": "user", "content": request.prompt}]
            ),
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = resp.usage
        return ModelResponse(
            text=resp.choices[0].message.content or "",
            provider=self.name, model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
            cost_usd=0.0,                     # pricing not tracked for this provider yet
            latency_ms=latency_ms,
        )


@dataclass
class Budget:
    """Per-scope spend ceiling. Exceeded budgets block, they do not warn."""

    limit_usd: float
    spent_usd: float = 0.0
    tokens_used: int = 0
    calls: int = 0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def would_exceed(self, estimate_usd: float) -> bool:
        return (self.spent_usd + estimate_usd) > self.limit_usd

    def charge(self, resp: ModelResponse) -> None:
        self.spent_usd += resp.cost_usd
        self.tokens_used += resp.input_tokens + resp.output_tokens
        self.calls += 1


class ModelRouter:
    """Selects a provider by capability, data classification, health and budget."""

    def __init__(self, adapters: Optional[list[ModelAdapter]] = None):
        self._adapters: list[ModelAdapter] = adapters if adapters is not None else [
            AnthropicAdapter(), OpenAIAdapter()
        ]
        self._health: dict[str, ProviderHealth] = {
            a.name: ProviderHealth(name=a.name, configured=a.is_configured())
            for a in self._adapters
        }

    # ── introspection ────────────────────────────────────────────────────────

    def refresh_health(self) -> None:
        for a in self._adapters:
            self._health[a.name].configured = a.is_configured()

    def health(self) -> dict[str, Any]:
        self.refresh_health()
        return {
            "providers": [h.to_dict() for h in self._health.values()],
            "any_configured": any(h.configured for h in self._health.values()),
        }

    @property
    def is_configured(self) -> bool:
        self.refresh_health()
        return any(h.configured for h in self._health.values())

    def missing_credential_result(self) -> MoResult:
        env_vars = sorted({a.credential_env_var for a in self._adapters})
        return MoResult(
            ResultState.CREDENTIAL_REQUIRED,
            "No model provider is configured. Set one of: " + ", ".join(env_vars) + ".",
            meta={"env_vars": env_vars},
        )

    # ── routing ──────────────────────────────────────────────────────────────

    def _candidates(self, request: ModelRequest) -> list[ModelAdapter]:
        out = []
        for a in self._adapters:
            h = self._health[a.name]
            if not a.is_configured():
                continue
            if request.capability not in a.supported_capabilities:
                continue
            if request.data_classification == "RESTRICTED" and not a.allows_restricted_data:
                continue
            if h.circuit_open:
                continue
            out.append(a)
        return out

    def complete(self, request: ModelRequest, budget: Optional[Budget] = None) -> MoResult:
        """Run a completion and record it in the metrics registry."""
        import time as _time

        from ..observability.tracing import record_model_call

        started = _time.perf_counter()
        result = self._complete(request, budget)
        record_model_call(result, (_time.perf_counter() - started) * 1000)
        return result

    def _complete(self, request: ModelRequest, budget: Optional[Budget] = None) -> MoResult:
        """Run a completion. Returns a truthful MoResult, never a fabricated body."""
        self.refresh_health()

        if budget and budget.remaining_usd <= 0:
            return MoResult(
                ResultState.BLOCKED,
                f"Model budget exhausted (${budget.spent_usd:.4f} of ${budget.limit_usd:.2f} spent).",
                meta={"spent_usd": budget.spent_usd, "limit_usd": budget.limit_usd},
            )

        candidates = self._candidates(request)
        if not candidates:
            configured = [a for a in self._adapters if a.is_configured()]
            if not configured:
                return self.missing_credential_result()
            if request.data_classification == "RESTRICTED":
                return MoResult(
                    ResultState.POLICY_DENIED,
                    "No configured provider is approved for RESTRICTED data.",
                    meta={"data_classification": "RESTRICTED"},
                )
            return MoResult(
                ResultState.PROVIDER_UNAVAILABLE,
                "Every configured provider is unavailable "
                f"(capability={request.capability}, circuits open).",
                meta=self.health(),
            )

        errors: list[str] = []
        for adapter in candidates:
            health = self._health[adapter.name]
            try:
                resp = adapter.complete(request)
            except Exception as exc:                     # provider failure is recorded, not hidden
                health.record_failure(f"{type(exc).__name__}: {exc}")
                errors.append(f"{adapter.name}: {type(exc).__name__}: {exc}")
                continue
            health.record_success()
            if budget:
                budget.charge(resp)
            return MoResult.ok(
                {"text": resp.text},
                provider=resp.provider, model=resp.model,
                input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                cost_usd=resp.cost_usd, latency_ms=resp.latency_ms,
            )

        return MoResult(
            ResultState.PROVIDER_UNAVAILABLE,
            "All candidate providers failed: " + "; ".join(errors),
            meta={"errors": errors},
        )


_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_router() -> None:
    """Test hook — drops cached provider health."""
    global _router
    _router = None
