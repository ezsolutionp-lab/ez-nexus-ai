"""
MO NEXUS OMEGA — Tamper-evident audit chain.

Each record hashes its own content together with the previous record's hash,
per tenant. Editing or deleting any row breaks every hash after it, which
`verify_chain` detects and reports with the exact sequence number.

Sensitive values are redacted before the payload is hashed or stored.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..context import RequestContext
from ..db import AuditEvent
from ..errors import ResultState

GENESIS_HASH = "0" * 64

# Keys whose values never reach the audit store in cleartext.
_REDACT_KEYS = {
    "password", "hashed_password", "old_password", "new_password", "secret", "secret_key",
    "token", "access_token", "refresh_token", "api_key", "apikey", "authorization",
    "auth_token", "private_key", "credential", "credentials", "ssn", "mfa_secret",
    "twilio_auth_token", "anthropic_api_key", "openai_api_key", "smtp_password",
}
_REDACTED = "[REDACTED]"


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively replace sensitive values. Depth-capped to survive cycles."""
    if _depth > 12:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k.lower() in _REDACT_KEYS else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    return value


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(
    *, prev_hash: str, tenant_id: str, seq: int, occurred_at: datetime,
    actor_id: str, action: str, resource_type: Optional[str], resource_id: Optional[str],
    result_state: str, payload_json: Optional[str],
) -> str:
    material = "|".join([
        prev_hash, tenant_id, str(seq), occurred_at.isoformat(), actor_id, action,
        resource_type or "", resource_id or "", result_state, payload_json or "",
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record(
    db: Session,
    ctx: RequestContext,
    *,
    action: str,
    result_state: ResultState,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: str = "",
    payload: Optional[dict[str, Any]] = None,
    cost_usd: Optional[float] = None,
) -> AuditEvent:
    """Append one tamper-evident record. Always flushes so `seq` is stable."""
    last = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == ctx.tenant_id)
        .order_by(AuditEvent.seq.desc())
        .first()
    )
    seq = (last.seq + 1) if last else 1
    prev_hash = last.entry_hash if last else GENESIS_HASH
    occurred_at = datetime.utcnow()

    payload_json = _canonical(redact(payload)) if payload else None
    entry_hash = compute_hash(
        prev_hash=prev_hash, tenant_id=ctx.tenant_id, seq=seq, occurred_at=occurred_at,
        actor_id=ctx.actor_id, action=action, resource_type=resource_type,
        resource_id=resource_id, result_state=result_state.value, payload_json=payload_json,
    )

    event = AuditEvent(
        tenant_id=ctx.tenant_id, seq=seq, occurred_at=occurred_at,
        actor_id=ctx.actor_id, actor_type=ctx.actor_type, actor_label=ctx.actor_label,
        source_channel=ctx.source_channel, action=action,
        resource_type=resource_type, resource_id=resource_id,
        result_state=result_state.value, detail=detail or None,
        payload_json=payload_json, trace_id=ctx.trace_id, cost_usd=cost_usd,
        prev_hash=prev_hash, entry_hash=entry_hash,
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, tenant_id: str) -> dict[str, Any]:
    """Recompute every hash in order. Reports the first sequence that breaks."""
    rows: Iterable[AuditEvent] = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.seq.asc())
        .all()
    )
    prev = GENESIS_HASH
    checked = 0
    for row in rows:
        if row.prev_hash != prev:
            return {"valid": False, "checked": checked, "broken_at_seq": row.seq,
                    "reason": "prev_hash does not match the preceding record"}
        expected = compute_hash(
            prev_hash=row.prev_hash, tenant_id=row.tenant_id, seq=row.seq,
            occurred_at=row.occurred_at, actor_id=row.actor_id, action=row.action,
            resource_type=row.resource_type, resource_id=row.resource_id,
            result_state=row.result_state, payload_json=row.payload_json,
        )
        if expected != row.entry_hash:
            return {"valid": False, "checked": checked, "broken_at_seq": row.seq,
                    "reason": "record content does not match its stored hash"}
        prev = row.entry_hash
        checked += 1
    return {"valid": True, "checked": checked, "head_hash": prev}


def tenant_event_count(db: Session, tenant_id: str) -> int:
    return int(db.query(func.count(AuditEvent.id)).filter(AuditEvent.tenant_id == tenant_id).scalar() or 0)
