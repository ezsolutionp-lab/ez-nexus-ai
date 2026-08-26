"""
MO NEXUS OMEGA — Durable event fabric.

Events are written to the database first, then dispatched. A subscriber that
raises does not lose the event: the row stays undelivered, records the error and
moves to the dead-letter queue after the retry ceiling. Replay reads from the
store, so a restart loses nothing that was accepted.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..context import RequestContext
from ..db import EventRecord

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 5

Subscriber = Callable[[str, dict[str, Any], "EventRecord"], None]
_subscribers: dict[str, list[Subscriber]] = {}


def subscribe(topic: str, fn: Subscriber) -> None:
    _subscribers.setdefault(topic, []).append(fn)


def clear_subscribers() -> None:
    _subscribers.clear()


def publish(
    db: Session,
    ctx: RequestContext,
    topic: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    source: str = "",
) -> EventRecord:
    """Persist an event, then attempt delivery. Persistence happens first."""
    record = EventRecord(
        tenant_id=ctx.tenant_id,
        created_by=ctx.actor_id,
        topic=topic,
        payload_json=json.dumps(payload or {}, default=str),
        source=source or ctx.source_channel,
        trace_id=ctx.trace_id,
    )
    db.add(record)
    db.flush()
    _deliver(db, record)
    return record


def _deliver(db: Session, record: EventRecord) -> None:
    subs = _subscribers.get(record.topic, []) + _subscribers.get("*", [])
    if not subs:
        record.delivered = True
        db.flush()
        return
    payload = json.loads(record.payload_json or "{}")
    errors: list[str] = []
    for fn in subs:
        try:
            fn(record.topic, payload, record)
        except Exception as exc:
            errors.append(f"{getattr(fn, '__name__', fn)}: {type(exc).__name__}: {exc}")
    record.delivery_attempts += 1
    if errors:
        record.last_error = "; ".join(errors)[:2000]
        record.delivered = False
        if record.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
            record.dead_lettered = True
            logger.error("Event %s dead-lettered after %d attempts", record.id, record.delivery_attempts)
    else:
        record.delivered = True
        record.last_error = None
    db.flush()


def redeliver_pending(db: Session, tenant_id: str, limit: int = 100) -> dict[str, int]:
    """Retry undelivered, non-dead-lettered events. Safe to run repeatedly."""
    rows = (
        db.query(EventRecord)
        .filter(
            EventRecord.tenant_id == tenant_id,
            EventRecord.delivered.is_(False),
            EventRecord.dead_lettered.is_(False),
        )
        .order_by(EventRecord.created_at.asc())
        .limit(limit)
        .all()
    )
    delivered = 0
    for row in rows:
        _deliver(db, row)
        if row.delivered:
            delivered += 1
    return {"attempted": len(rows), "delivered": delivered}


def replay(db: Session, tenant_id: str, topic: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
    q = db.query(EventRecord).filter(EventRecord.tenant_id == tenant_id)
    if topic:
        q = q.filter(EventRecord.topic == topic)
    rows = q.order_by(EventRecord.created_at.asc()).limit(limit).all()
    return [
        {
            "id": r.id, "topic": r.topic, "payload": json.loads(r.payload_json or "{}"),
            "delivered": r.delivered, "attempts": r.delivery_attempts,
            "dead_lettered": r.dead_lettered, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def dead_letters(db: Session, tenant_id: str) -> list[EventRecord]:
    return (
        db.query(EventRecord)
        .filter(EventRecord.tenant_id == tenant_id, EventRecord.dead_lettered.is_(True))
        .order_by(EventRecord.created_at.desc())
        .all()
    )
