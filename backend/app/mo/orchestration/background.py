"""
MO NEXUS OMEGA — background execution of orchestrated runs.

`submit` claims the run with a single conditional UPDATE (so two callers cannot both start it), queues it on a
bounded worker pool, and returns at once; the worker opens its own database session and commits at each checkpoint,
so `GET /runs/{id}` shows live progress. Approvals, autonomy and safe-mode are enforced exactly as for a synchronous
execute — the worker calls the same Orchestrator.

Limits: the pool lives in this process. A restart loses queued work; `recover_interrupted()` (called at startup)
marks such runs FAILED with an explicit "interrupted" note so they can be resumed, rather than leaving them stuck as
RUNNING. A step handler that ignores its timeout keeps its thread until it returns — Python cannot kill a thread.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import OrchestrationRun, Tenant
from ..errors import MoResult, ResultState
from .runner import Orchestrator

logger = logging.getLogger(__name__)

STARTABLE = ("PENDING", "AWAITING_APPROVAL", "PARTIAL", "FAILED")
_pool: Optional[ThreadPoolExecutor] = None


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=max(1, int(os.getenv("MO_RUN_WORKERS", "4"))), thread_name_prefix="mo-bg-run")
    return _pool


def shutdown(wait: bool = True) -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=wait)
        _pool = None


def submit(db: Session, session_factory: Callable[[], Session], ctx: RequestContext, run_id: str, *,
           parallelism: int = 1, retry_failed: bool = False) -> MoResult:
    run = db.get(OrchestrationRun, run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
        return MoResult(ResultState.FAILED, "No such run.")
    tenant = db.get(Tenant, ctx.tenant_id)
    if tenant is not None and tenant.safe_mode:
        return MoResult(ResultState.BLOCKED, "Safe mode is on for this tenant; runs cannot execute.")
    claimed = db.execute(update(OrchestrationRun)
                         .where(OrchestrationRun.id == run_id, OrchestrationRun.tenant_id == ctx.tenant_id,
                                OrchestrationRun.status.in_(STARTABLE))
                         .values(status="QUEUED")).rowcount
    if claimed != 1:
        return MoResult(ResultState.BLOCKED, f"The run is {run.status} and cannot be queued.")
    chain.record(db, ctx, action="run.queued", result_state=ResultState.SUCCESS, resource_type="run", resource_id=run_id,
                 detail=run.name)
    db.commit()
    _get_pool().submit(_work, session_factory, ctx, run_id, parallelism, retry_failed)
    return MoResult.ok({"run_id": run_id, "status": "QUEUED"}, background=True)


def _work(session_factory: Callable[[], Session], ctx: RequestContext, run_id: str, parallelism: int, retry_failed: bool) -> None:
    db = session_factory()
    try:
        Orchestrator(db, ctx, commit=True).execute(run_id, parallelism=parallelism, retry_failed=retry_failed)
        db.commit()
    except Exception as exc:                                     # a crashed worker must never leave a run looking alive
        logger.exception("background run %s crashed", run_id)
        db.rollback()
        run = db.get(OrchestrationRun, run_id)
        if run is not None:
            run.status, run.finished_at = "FAILED", datetime.utcnow()
            run.detail = f"The worker crashed: {type(exc).__name__}. Resume with execute."
            chain.record(db, ctx, action="run.worker_crashed", result_state=ResultState.FAILED, resource_type="run",
                         resource_id=run_id, detail=run.detail)
            db.commit()
    finally:
        db.close()


def recover_interrupted(db: Session) -> int:
    """At startup: runs left QUEUED or RUNNING by a previous process cannot still be running."""
    rows = db.query(OrchestrationRun).filter(OrchestrationRun.status.in_(("QUEUED", "RUNNING"))).all()
    for r in rows:
        r.status, r.finished_at = "FAILED", datetime.utcnow()
        r.detail = "Interrupted by a restart; completed steps are kept. Resume with execute."
    db.commit()
    return len(rows)
