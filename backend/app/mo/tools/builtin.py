"""
MO NEXUS OMEGA — Built-in tools.

These do real work against real systems. Where a capability needs an external
provider that is not configured, the tool declares `credential_env_var` and the
registry blocks the call with CREDENTIAL_REQUIRED before the handler runs — so
there is no code path that pretends an email was sent or a payment was taken.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..context import RequestContext
from ..errors import MoResult, ResultState
from .spec import RiskLevel, ToolRegistry, ToolSpec


def _echo(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    """Connectivity probe used by agent self-tests."""
    return MoResult.ok({"echo": payload.get("message", ""), "tenant_id": ctx.tenant_id})


def _slugify(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    text = payload["text"]
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]
    if not slug:
        return MoResult(ResultState.FAILED, f"'{text}' contains no slug-safe characters.")
    return MoResult.ok({"slug": slug})


def _json_validate(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    raw = payload["json_text"]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return MoResult(ResultState.FAILED, f"Invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}")
    return MoResult.ok({"parsed": parsed, "type": type(parsed).__name__})


def _http_fetch(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    """Outbound HTTP. MEDIUM risk: it leaves the process boundary."""
    import httpx

    url = payload["url"]
    if not url.startswith(("http://", "https://")):
        return MoResult(ResultState.FAILED, "URL must start with http:// or https://.")
    try:
        resp = httpx.get(url, timeout=payload.get("timeout_seconds", 10), follow_redirects=True)
    except Exception as exc:
        return MoResult(ResultState.FAILED, f"Request to {url} failed: {type(exc).__name__}: {exc}")
    if resp.status_code >= 400:
        return MoResult(
            ResultState.FAILED,
            f"{url} returned HTTP {resp.status_code}.",
            meta={"status_code": resp.status_code},
        )
    return MoResult.ok({"status_code": resp.status_code, "body": resp.text[:20000]})


def _send_email(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    """Real SMTP send. Unreachable without SMTP_PASSWORD — the registry blocks first."""
    from ...sms_email import send_email  # existing MO adapter

    ok = send_email(payload["to"], payload["subject"], payload["body"])
    if not ok:
        return MoResult(ResultState.FAILED, f"SMTP delivery to {payload['to']} failed.")
    return MoResult.ok({"delivered_to": payload["to"]})


def _send_sms(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    """Real Twilio send. Unreachable without TWILIO_AUTH_TOKEN."""
    from ...sms_email import send_sms

    ok = send_sms(payload["to"], payload["body"])
    if not ok:
        return MoResult(ResultState.FAILED, f"SMS delivery to {payload['to']} failed.")
    return MoResult.ok({"delivered_to": payload["to"]})


def _take_payment(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    """CRITICAL. No payment provider adapter is implemented, so this never runs."""
    return MoResult(
        ResultState.CREDENTIAL_REQUIRED,
        "No payment provider adapter is implemented. Configure one before charging a customer.",
        meta={"provider": "none"},
    )


BUILTIN_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="core.echo",
        description="Return the supplied message. Used by agent self-tests to prove tool wiring.",
        handler=_echo, risk_level=RiskLevel.LOW,
        input_schema={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        output_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
    ),
    ToolSpec(
        name="text.slugify",
        description="Convert text into a URL-safe slug.",
        handler=_slugify, risk_level=RiskLevel.LOW,
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
    ToolSpec(
        name="data.json_validate",
        description="Parse and validate a JSON document, reporting the exact parse error.",
        handler=_json_validate, risk_level=RiskLevel.LOW,
        input_schema={"type": "object", "properties": {"json_text": {"type": "string"}}, "required": ["json_text"]},
    ),
    ToolSpec(
        name="net.http_fetch",
        description="Fetch a URL over HTTP(S) and return the response body.",
        handler=_http_fetch, risk_level=RiskLevel.MEDIUM,
        required_scopes=("tool:net",), rate_limit_per_minute=30,
        input_schema={
            "type": "object",
            "properties": {"url": {"type": "string"}, "timeout_seconds": {"type": "integer"}},
            "required": ["url"],
        },
    ),
    ToolSpec(
        name="comms.send_email",
        description="Send an email through the configured SMTP provider.",
        handler=_send_email, risk_level=RiskLevel.MEDIUM,
        required_scopes=("tool:comms",), credential_env_var="SMTP_PASSWORD",
        rate_limit_per_minute=20,
        input_schema={
            "type": "object",
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"],
        },
    ),
    ToolSpec(
        name="comms.send_sms",
        description="Send an SMS through the configured Twilio account.",
        handler=_send_sms, risk_level=RiskLevel.MEDIUM,
        required_scopes=("tool:comms",), credential_env_var="TWILIO_AUTH_TOKEN",
        rate_limit_per_minute=20,
        input_schema={
            "type": "object",
            "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "body"],
        },
    ),
    ToolSpec(
        name="payments.charge",
        description="Charge a customer payment method.",
        handler=_take_payment, risk_level=RiskLevel.CRITICAL,
        required_scopes=("tool:payments",), credential_env_var="PAYMENTS_API_KEY",
        input_schema={
            "type": "object",
            "properties": {"amount_cents": {"type": "integer"}, "currency": {"type": "string"}},
            "required": ["amount_cents", "currency"],
        },
    ),
]


def register_builtin_tools(registry: ToolRegistry) -> int:
    for spec in BUILTIN_SPECS:
        registry.register(spec, replace=True)
    return len(BUILTIN_SPECS)
