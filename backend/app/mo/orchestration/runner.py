"""
MO NEXUS OMEGA — Orchestration runner.

Executes a validated DAG of governed steps with real checkpointing:

  * Every step goes through ToolRegistry.invoke under the caller's own context, so
    scopes, MFA, approvals, credentials, rate limits and input schemas all apply.
    The runner adds no privileges.
  * Autonomy levels restrict unattended execution. A step the level does not permit
    (or any HIGH/CRITICAL tool, or a `gate`) parks in AWAITING_APPROVAL behind a real
    approval request; the run continues on independent branches and finishes as
    AWAITING_APPROVAL until a human decides and the run is resumed.
  * Each step is checkpointed. SUCCEEDED steps are never re-executed on resume. A step
    that was RUNNING when the process died is marked FAILED (its side effects are
    unknown) and only re-runs when the caller asks for retry_failed.
  * Budget is enforced between steps; timeouts and retries apply per step. Retries
    happen only for transient states (TIMEOUT, RATE_LIMITED, PROVIDER_UNAVAILABLE).
  * A dependency that did not succeed causes its dependents to be SKIPPED with a
    reason. The run's final state is derived from the steps — never assumed.

Tool handlers run on worker threads so a step can be timed out; the database session
is only ever touched from the calling thread. A timed-out handler cannot be killed
(Python has no safe thread cancel), so it is reported as TIMEOUT and abandoned.
"""

from __future__ import annotations

import contextvars
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..approvals import engine as approvals
from ..audit import chain
from ..context import RequestContext
from ..control.autonomy import ALLOW, DENY, RISK_ORDER, AutonomyManager
from ..db import OrchestrationRun, OrchestrationStep, Tenant
from ..errors import MoResult, ResultState
from ..observability.metrics import metrics
from ..observability.tracing import tracer
from ..tools.spec import get_tool_registry
from .spec import resolve_templates, validate_plan

TRANSIENT = {ResultState.TIMEOUT, ResultState.RATE_LIMITED, ResultState.PROVIDER_UNAVAILABLE}
MAX_OUTPUT_CHARS = 50_000
TERMINAL_STEP = {"SUCCEEDED", "FAILED", "SKIPPED", "CANCELLED"}


def _store_output(data: dict[str, Any]) -> str:
    safe = chain.redact(data)
    text = json.dumps(safe, default=str)
    if len(text) > MAX_OUTPUT_CHARS:
        return json.dumps({"_truncated": True, "preview": text[:2000]})
    return text


class Orchestrator:
    def __init__(self, db: Session, ctx: RequestContext, *, commit: bool = False,
                 sleep: Callable[[float], None] = time.sleep):
        self.db, self.ctx, self._sleep = db, ctx, sleep
        self._checkpoint = db.commit if commit else db.flush

    # ── lifecycle ───────────────────────────────────────────────────────────

    def create(self, plan: dict[str, Any]) -> MoResult:
        problem = validate_plan(plan)
        if problem:
            return MoResult(ResultState.FAILED, problem)
        level = AutonomyManager(self.db, self.ctx).policy_for(plan["name"])[0]
        run = OrchestrationRun(
            tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, name=plan["name"].strip(),
            status="PENDING", spec_json=json.dumps(plan, default=str),
            budget_usd=float(plan.get("budget_usd", 1.0)), autonomy_level=level, trace_id=self.ctx.trace_id)
        self.db.add(run)
        self.db.flush()
        for s in plan["steps"]:
            self.db.add(OrchestrationStep(
                tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, run_id=run.id, step_key=s["key"],
                kind=s.get("kind", "tool"), target=s.get("target") or f"gate:{s['key']}",
                depends_on_json=json.dumps(s.get("depends_on", []))))
        chain.record(self.db, self.ctx, action="run.created", result_state=ResultState.SUCCESS,
                     resource_type="run", resource_id=run.id, detail=run.name,
                     payload={"steps": len(plan["steps"]), "budget_usd": run.budget_usd})
        self._checkpoint()
        return MoResult.ok({"run_id": run.id, "status": run.status, "steps": len(plan["steps"])})

    def cancel(self, run_id: str) -> MoResult:
        run = self._run(run_id)
        if run is None:
            return MoResult(ResultState.FAILED, "No such run.")
        if run.status in ("SUCCEEDED", "FAILED", "PARTIAL", "CANCELLED"):
            return MoResult(ResultState.BLOCKED, f"The run already finished as {run.status}.")
        for st in self._steps(run_id):
            if st.status in ("PENDING", "AWAITING_APPROVAL"):
                st.status, st.detail = "CANCELLED", "Run cancelled."
        run.status, run.finished_at, run.detail = "CANCELLED", datetime.utcnow(), "Cancelled by request."
        chain.record(self.db, self.ctx, action="run.cancelled", result_state=ResultState.CANCELLED,
                     resource_type="run", resource_id=run.id, detail=run.name)
        self._checkpoint()
        return MoResult(ResultState.CANCELLED, "Run cancelled.", meta={"run_id": run.id})

    def execute(self, run_id: str, *, parallelism: int = 1, retry_failed: bool = False) -> MoResult:
        """Run (or resume) a run. Idempotent for completed steps."""
        run = self._run(run_id)
        if run is None:
            return MoResult(ResultState.FAILED, "No such run.")
        if run.status == "CANCELLED":
            return MoResult(ResultState.BLOCKED, "The run was cancelled.")
        tenant = self.db.get(Tenant, self.ctx.tenant_id)
        if tenant is not None and tenant.safe_mode:
            return MoResult(ResultState.BLOCKED, "Safe mode is on for this tenant; runs cannot execute.")
        if run.status == "RUNNING":
            return MoResult(ResultState.BLOCKED, "The run is already running.")

        plan = json.loads(run.spec_json)
        defs = {s["key"]: s for s in plan["steps"]}
        self._prepare_resume(run_id, retry_failed)
        run.status, run.started_at = "RUNNING", run.started_at or datetime.utcnow()
        run.finished_at = None
        self._checkpoint()

        pool = ThreadPoolExecutor(max_workers=max(1, min(parallelism, 16)), thread_name_prefix="mo-run")
        try:
            with tracer.span(f"run:{run.name}", self.ctx, run_id=run.id):
                self._loop(run, defs, pool)
        finally:
            pool.shutdown(wait=False)
        return self._finish(run)

    # ── internals ───────────────────────────────────────────────────────────

    def _run(self, run_id: str) -> Optional[OrchestrationRun]:
        run = self.db.get(OrchestrationRun, run_id)
        return run if run is not None and run.tenant_id == self.ctx.tenant_id else None

    def _steps(self, run_id: str) -> list[OrchestrationStep]:
        return (self.db.query(OrchestrationStep)
                .filter(OrchestrationStep.run_id == run_id, OrchestrationStep.tenant_id == self.ctx.tenant_id)
                .order_by(OrchestrationStep.created_at, OrchestrationStep.step_key).all())

    def _prepare_resume(self, run_id: str, retry_failed: bool) -> None:
        for st in self._steps(run_id):
            if st.status == "RUNNING":
                st.status, st.result_state = "FAILED", ResultState.FAILED.value
                st.detail = "Interrupted while running; side effects are unknown, so it was not re-run automatically."
            if st.status == "FAILED" and retry_failed:
                st.status, st.attempts, st.detail = "PENDING", 0, None
            elif st.status == "SKIPPED":
                st.status, st.detail = "PENDING", None
            elif st.status == "AWAITING_APPROVAL":
                st.status = "PENDING"           # re-evaluated: approval may now be granted

    def _outputs(self, steps: list[OrchestrationStep]) -> dict[str, Any]:
        return {s.step_key: json.loads(s.output_json) for s in steps if s.status == "SUCCEEDED" and s.output_json}

    def _loop(self, run: OrchestrationRun, defs: dict[str, dict], pool: ThreadPoolExecutor) -> None:
        while True:
            self.db.refresh(run)
            if run.status == "CANCELLED":
                return
            steps = self._steps(run.id)
            by_key = {s.step_key: s for s in steps}
            ready: list[OrchestrationStep] = []
            progressed = False
            for st in steps:
                if st.status != "PENDING":
                    continue
                deps = json.loads(st.depends_on_json)
                bad = [d for d in deps if by_key[d].status in ("FAILED", "SKIPPED", "CANCELLED")]
                if bad:
                    st.status, st.result_state = "SKIPPED", ResultState.DEPENDENCY_FAILED.value
                    st.detail = f"Skipped because dependency '{bad[0]}' did not succeed."
                    metrics.inc("mo_run_steps_total", kind=st.kind, state="SKIPPED")
                    progressed = True
                elif all(by_key[d].status == "SUCCEEDED" for d in deps):
                    ready.append(st)
                elif any(by_key[d].status == "AWAITING_APPROVAL" for d in deps):
                    pass                                    # blocked behind a human, not failed
            if not ready:
                if progressed:
                    self._checkpoint()
                    continue
                return
            outputs = self._outputs(steps)
            runnable: list[tuple[OrchestrationStep, dict, Any]] = []
            for st in ready:
                if self._exhausted(run):
                    st.status, st.result_state = "SKIPPED", ResultState.BLOCKED.value
                    st.detail = f"Run budget exhausted (${run.spent_usd:.4f} of ${run.budget_usd:.2f})."
                    metrics.inc("mo_run_steps_total", kind=st.kind, state="SKIPPED")
                    continue
                gated = self._gate(run, st, defs[st.step_key])
                if gated is not None:
                    continue
                runnable.append((st, defs[st.step_key], outputs))
            self._checkpoint()
            if not runnable:
                # Everything ready was parked or skipped; loop again to propagate skips.
                if any(s.status == "PENDING" and self._deps_ok_or_dead(s, by_key) for s in self._steps(run.id)):
                    continue
                return
            self._run_level(run, runnable, pool)
            self._checkpoint()
            if any(s.status == "FAILED" and defs[s.step_key].get("on_failure") == "abort" for s in self._steps(run.id)):
                for s in self._steps(run.id):
                    if s.status in ("PENDING", "AWAITING_APPROVAL"):
                        s.status, s.detail = "CANCELLED", "Run aborted after a step marked on_failure=abort failed."
                run.detail = "Aborted after an on_failure=abort step failed."
                self._checkpoint()
                return

    @staticmethod
    def _exhausted(run: OrchestrationRun) -> bool:
        spent = run.spent_usd or 0.0
        return spent >= run.budget_usd if run.budget_usd > 0 else spent > 0

    @staticmethod
    def _deps_ok_or_dead(st: OrchestrationStep, by_key: dict[str, OrchestrationStep]) -> bool:
        return any(by_key[d].status in ("FAILED", "SKIPPED", "CANCELLED") for d in json.loads(st.depends_on_json))

    def _gate(self, run: OrchestrationRun, st: OrchestrationStep, sdef: dict) -> Optional[str]:
        """Return None if the step may run now, else the reason it was parked or denied."""
        if st.kind == "gate":
            tier, subject = sdef.get("risk", "MEDIUM"), f"gate:{st.step_key}"
            needs_human, why = True, sdef.get("reason", "Human approval gate.")
        else:
            spec = get_tool_registry().get(st.target)
            if spec is None:
                st.status, st.result_state = "FAILED", ResultState.FAILED.value
                st.detail = f"Tool '{st.target}' is no longer registered."
                return st.detail
            verdict, why = AutonomyManager(self.db, self.ctx).decide(st.target, spec.risk_level)
            if verdict == DENY:
                st.status, st.result_state = "FAILED", ResultState.POLICY_DENIED.value
                st.detail = why
                metrics.inc("mo_run_steps_total", kind=st.kind, state="POLICY_DENIED")
                return why
            needs_human = spec.requires_approval or verdict != ALLOW
            # LOW-tier approvals auto-approve; a confirmation the autonomy level demands must be a real human decision.
            tier = spec.risk_level if RISK_ORDER.get(spec.risk_level, 1) >= RISK_ORDER["MEDIUM"] else "MEDIUM"
        if not needs_human:
            return None
        if st.approval_id and approvals.is_granted(self.db, self.ctx, st.approval_id):
            return None
        if st.approval_id:
            from ..db import ApprovalRequest
            req = self.db.get(ApprovalRequest, st.approval_id)
            if req is not None and req.status in ("REJECTED", "REVOKED", "EXPIRED"):
                st.status, st.result_state = "FAILED", ResultState.POLICY_DENIED.value
                st.detail = f"Approval {req.status.lower()}."
                metrics.inc("mo_run_steps_total", kind=st.kind, state="POLICY_DENIED")
                return st.detail
            st.status, st.detail = "AWAITING_APPROVAL", f"Waiting for approval {st.approval_id}."
            return st.detail
        req = approvals.request_approval(
            self.db, self.ctx, action=f"run.step:{st.target}", resource_type="run_step", resource_id=st.id,
            reason=f"Run '{run.name}' step '{st.step_key}': {why}", risk_tier=tier,
            payload={"run_id": run.id, "step": st.step_key})
        st.approval_id, st.status = req.id, "AWAITING_APPROVAL"
        st.detail = f"Waiting for approval {req.id}."
        if req.status == "APPROVED":                        # cannot happen for MEDIUM+, but never assume
            st.status = "PENDING"
            return None
        metrics.inc("mo_run_steps_total", kind=st.kind, state="AWAITING_APPROVAL")
        return st.detail

    def _run_level(self, run: OrchestrationRun, runnable: list, pool: ThreadPoolExecutor) -> None:
        jobs = []
        for st, sdef, outputs in runnable:
            if st.kind == "gate":
                self._complete(run, st, MoResult.ok({"approved": True, "approval_id": st.approval_id}), 0.0)
                continue
            try:
                payload = resolve_templates(sdef.get("input", {}), outputs)
            except KeyError as exc:
                self._complete(run, st, MoResult(ResultState.FAILED, f"Could not resolve input: {exc}"), 0.0)
                continue
            st.status = "RUNNING"
            st.attempts = (st.attempts or 0) + 1
            jobs.append((st, sdef, payload))
        self._checkpoint()
        futures = []
        for st, sdef, payload in jobs:
            approved = bool(st.approval_id) and approvals.is_granted(self.db, self.ctx, st.approval_id)
            futures.append((st, sdef, payload, pool.submit(
                contextvars.copy_context().run, self._invoke_with_retry, st.target, payload, approved, sdef)))
        for st, sdef, payload, fut in futures:
            started = time.perf_counter()
            timeout = sdef.get("timeout_s")
            try:
                # The retry loop enforces the per-attempt timeout; this bound only guards a wedged worker.
                result, attempts = fut.result(timeout=(timeout * (sdef.get("retries", 0) + 1) + 5) if timeout else None)
            except FutureTimeout:
                result, attempts = MoResult(ResultState.TIMEOUT, f"Step exceeded {timeout}s and was abandoned."), st.attempts
            st.attempts = attempts
            self._complete(run, st, result, (time.perf_counter() - started) * 1000)

    def _invoke_with_retry(self, target: str, payload: dict, approved: bool, sdef: dict) -> tuple[MoResult, int]:
        retries, timeout = int(sdef.get("retries", 0)), sdef.get("timeout_s")
        backoff = float(sdef.get("backoff_s", 0.0))
        attempts, result = 0, MoResult(ResultState.FAILED, "not run")
        registry = get_tool_registry()
        for attempt in range(retries + 1):
            attempts = attempt + 1
            if timeout:
                inner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mo-step")
                try:
                    fut = inner.submit(contextvars.copy_context().run, registry.invoke, self.ctx, target, payload,
                                       approval_granted=approved)
                    result = fut.result(timeout=timeout)
                except FutureTimeout:
                    result = MoResult(ResultState.TIMEOUT, f"Step exceeded {timeout}s and was abandoned.")
                finally:
                    inner.shutdown(wait=False)
            else:
                result = registry.invoke(self.ctx, target, payload, approval_granted=approved)
            if result.state.is_success or result.state not in TRANSIENT or attempt == retries:
                break
            self._sleep(backoff * (2 ** attempt))
        return result, attempts

    def _complete(self, run: OrchestrationRun, st: OrchestrationStep, result: MoResult, ms: float) -> None:
        st.result_state, st.duration_ms = result.state.value, int(ms)
        cost = float(result.meta.get("cost_usd", 0.0) or 0.0) if isinstance(result.meta, dict) else 0.0
        run.spent_usd = (run.spent_usd or 0.0) + cost
        if result.state.is_success:
            st.status, st.detail = "SUCCEEDED", None
            st.output_json = _store_output(result.data)
        elif result.state is ResultState.APPROVAL_REQUIRED and not st.approval_id:
            st.status, st.detail = "FAILED", result.detail
        else:
            st.status, st.detail = "FAILED", result.detail
            if result.data:
                st.output_json = _store_output(result.data)
        metrics.inc("mo_run_steps_total", kind=st.kind, state=st.status)
        metrics.observe("mo_run_step_duration_ms", ms, kind=st.kind)
        if st.status == "FAILED" and st.kind != "gate":
            # Repeated tool failure lowers the subject's autonomy; policy/credential gates are not the tool's fault.
            if result.state not in (ResultState.POLICY_DENIED, ResultState.CREDENTIAL_REQUIRED,
                                    ResultState.APPROVAL_REQUIRED, ResultState.RATE_LIMITED):
                AutonomyManager(self.db, self.ctx).demote(st.target, f"step failed in run '{run.name}'")

    def _finish(self, run: OrchestrationRun) -> MoResult:
        self.db.refresh(run)
        steps = self._steps(run.id)
        states = [s.status for s in steps]
        if run.status == "CANCELLED":
            final = "CANCELLED"
        elif any(s == "AWAITING_APPROVAL" for s in states):
            final = "AWAITING_APPROVAL"
        elif all(s == "SUCCEEDED" for s in states):
            final = "SUCCEEDED"
        elif any(s == "SUCCEEDED" for s in states):
            final = "PARTIAL"
        else:
            final = "FAILED"
        if run.status != "CANCELLED":
            run.status = final
        if final != "AWAITING_APPROVAL":
            run.finished_at = datetime.utcnow()
        if final not in ("SUCCEEDED", "CANCELLED") and not run.detail:
            parts = [f"{s.step_key}: {s.detail}" for s in steps if s.status in ("FAILED", "SKIPPED", "AWAITING_APPROVAL") and s.detail]
            run.detail = "; ".join(parts[:5]) or final
        metrics.inc("mo_runs_total", state=final)
        state = {"SUCCEEDED": ResultState.SUCCESS, "PARTIAL": ResultState.PARTIAL,
                 "AWAITING_APPROVAL": ResultState.PENDING_APPROVAL, "CANCELLED": ResultState.CANCELLED}.get(final, ResultState.FAILED)
        chain.record(self.db, self.ctx, action="run.finished", result_state=state, resource_type="run",
                     resource_id=run.id, detail=f"{run.name}: {final}", cost_usd=run.spent_usd,
                     payload={"steps": {s.step_key: s.status for s in steps}})
        self._checkpoint()
        data = self.describe(run.id)
        if state is ResultState.SUCCESS:
            return MoResult.ok(data)
        return MoResult(state, run.detail or final, data=data)

    def describe(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        if run is None:
            return {}
        return {"run_id": run.id, "name": run.name, "status": run.status, "budget_usd": run.budget_usd,
                "spent_usd": round(run.spent_usd or 0.0, 6), "autonomy_level": run.autonomy_level,
                "detail": run.detail, "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "steps": [{"key": s.step_key, "kind": s.kind, "target": s.target, "status": s.status,
                           "result_state": s.result_state, "attempts": s.attempts, "detail": s.detail,
                           "approval_id": s.approval_id, "duration_ms": s.duration_ms,
                           "depends_on": json.loads(s.depends_on_json),
                           "output": json.loads(s.output_json) if s.output_json else None}
                          for s in self._steps(run_id)]}

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = (self.db.query(OrchestrationRun).filter(OrchestrationRun.tenant_id == self.ctx.tenant_id)
                .order_by(OrchestrationRun.created_at.desc()).limit(limit).all())
        return [{"run_id": r.id, "name": r.name, "status": r.status, "spent_usd": round(r.spent_usd or 0.0, 6),
                 "budget_usd": r.budget_usd} for r in rows]
