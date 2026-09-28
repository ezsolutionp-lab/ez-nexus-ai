"""
MO NEXUS OMEGA — Canonical result states and error type.

Rule (Master Build Directive §0, §37, §38): a failure is never reported as a
success. Every MO operation returns one of these states, and callers that
cannot complete their work must pick the state that is actually true.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ResultState(str, Enum):
    """Standard MO result states. Never convert a failure into SUCCESS."""

    # Core states
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CREDENTIAL_REQUIRED = "CREDENTIAL_REQUIRED"
    POLICY_DENIED = "POLICY_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"

    # Builder pipeline states
    BUILD_FAILED = "BUILD_FAILED"
    TEST_FAILED = "TEST_FAILED"
    SECURITY_FAILED = "SECURITY_FAILED"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DEPLOYMENT_FAILED = "DEPLOYMENT_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"

    @property
    def is_success(self) -> bool:
        return self is ResultState.SUCCESS

    @property
    def is_terminal_failure(self) -> bool:
        return self in {
            ResultState.FAILED,
            ResultState.BUILD_FAILED,
            ResultState.TEST_FAILED,
            ResultState.SECURITY_FAILED,
            ResultState.DEPENDENCY_FAILED,
            ResultState.DEPLOYMENT_FAILED,
        }


class MoResult:
    """
    A result envelope that cannot silently claim success.

    `state` is authoritative. `detail` explains a non-success state in terms a
    human can act on. `data` carries the payload only when work actually ran.
    """

    __slots__ = ("state", "detail", "data", "meta")

    def __init__(
        self,
        state: ResultState,
        detail: str = "",
        data: Optional[dict[str, Any]] = None,
        meta: Optional[dict[str, Any]] = None,
    ):
        if not isinstance(state, ResultState):
            raise TypeError(f"state must be a ResultState, got {type(state)!r}")
        if state is not ResultState.SUCCESS and not detail:
            raise ValueError(f"{state.value} requires a detail explaining why")
        self.state = state
        self.detail = detail
        self.data = data or {}
        self.meta = meta or {}

    @classmethod
    def ok(cls, data: Optional[dict[str, Any]] = None, **meta: Any) -> "MoResult":
        return cls(ResultState.SUCCESS, "", data, meta or None)

    @classmethod
    def credential_required(cls, provider: str, env_var: str) -> "MoResult":
        return cls(
            ResultState.CREDENTIAL_REQUIRED,
            f"{provider} is not configured. Set {env_var} to enable this capability.",
            meta={"provider": provider, "env_var": env_var},
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state.value, "ok": self.state.is_success}
        if self.detail:
            out["detail"] = self.detail
        if self.data:
            out["data"] = self.data
        if self.meta:
            out["meta"] = self.meta
        return out

    def __repr__(self) -> str:
        return f"MoResult({self.state.value}, {self.detail!r})"


class MoError(Exception):
    """Raised when an MO operation cannot proceed. Carries a truthful state."""

    def __init__(self, state: ResultState, detail: str, **meta: Any):
        super().__init__(f"{state.value}: {detail}")
        self.state = state
        self.detail = detail
        self.meta = meta

    def as_result(self) -> MoResult:
        return MoResult(self.state, self.detail, meta=self.meta or None)


# HTTP status mapping — used by the API layer so wire responses stay honest.
HTTP_STATUS_FOR_STATE: dict[ResultState, int] = {
    ResultState.SUCCESS: 200,
    ResultState.PARTIAL: 207,
    ResultState.FAILED: 500,
    ResultState.BLOCKED: 409,
    ResultState.PENDING_APPROVAL: 202,
    ResultState.APPROVAL_REQUIRED: 202,
    ResultState.CREDENTIAL_REQUIRED: 424,
    ResultState.POLICY_DENIED: 403,
    ResultState.RATE_LIMITED: 429,
    ResultState.TIMEOUT: 504,
    ResultState.CANCELLED: 499,
    ResultState.BUILD_FAILED: 422,
    ResultState.TEST_FAILED: 422,
    ResultState.SECURITY_FAILED: 422,
    ResultState.DEPENDENCY_FAILED: 422,
    ResultState.DEPLOYMENT_FAILED: 500,
    ResultState.PROVIDER_UNAVAILABLE: 503,
}
