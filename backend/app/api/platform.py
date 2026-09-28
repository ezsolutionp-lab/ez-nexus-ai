"""
MO NEXUS OMEGA — platform API: knowledge, memory, orchestration, autonomy, protocols,
domain intelligence, evaluation, observability and the capability manifest.

Everything sits behind mo_router(), so each route is authenticated, rate limited and runs
under the caller's RequestContext. Nothing here can grant approval: rollback and tool
calls never accept a client-supplied approval flag.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..mo import manifest as _manifest
from ..mo.context import RequestContext
from ..mo.control.autonomy import AutonomyManager
from ..mo.control.reversible import ReversibleLog, dry_run
from ..mo.errors import HTTP_STATUS_FOR_STATE, MoResult, ResultState
from ..mo.evaluation import harness, suites
from ..mo.knowledge.service import KnowledgeService
from ..mo.memory.store import MemoryStore
from ..mo.observability.metrics import metrics
from ..mo.observability.tracing import tracer
from ..mo.orchestration.runner import Orchestrator
from ..mo.protocols import a2a, mcp_server
from ..mo.protocols.peers import PeerRegistry
from ..mo.security.zero_trust import mo_router, resolve_context
from ..mo.tools.spec import get_tool_registry

PREFIX = "/api/mo/platform"
router = mo_router(PREFIX, ["mo-platform"], bucket="write")
read_router = mo_router(PREFIX, ["mo-platform"], bucket="read")
ALL_ROUTERS = [read_router, router]


# ── helpers ─────────────────────────────────────────────────────────────────

def _not_found(detail: str) -> bool:
    d = detail.lower()
    return d.startswith("no such") or (d.startswith("no ") and " named " in d)


def _respond(result: MoResult, *, created: bool = False) -> Response:
    """Render an MoResult honestly: the HTTP status follows the result state."""
    if result.state.is_success:
        status = 201 if created else HTTP_STATUS_FOR_STATE.get(result.state, 200)
    elif result.state == ResultState.CANCELLED and result.meta.get("run_id"):
        status = 200                       # a requested cancellation that took effect
    elif result.state == ResultState.FAILED:
        status = 404 if _not_found(result.detail) else 422
    elif result.state == ResultState.POLICY_DENIED and "another tenant" in result.detail:
        status = 404
    else:
        status = HTTP_STATUS_FOR_STATE.get(result.state, 400)
    return JSONResponse(status_code=status, content=jsonable_encoder(result.to_dict()))


def _read(ctx: RequestContext) -> None:
    ctx.require_scope("builder:read")


def _write(ctx: RequestContext) -> None:
    ctx.require_scope("builder:write")


def _guarded(fn):
    """Turn a MoError raised by a scope check into the right HTTP response."""
    from functools import wraps

    from ..mo.errors import MoError

    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except MoError as exc:
            return _respond(exc.as_result())
    return wrapper


def _route(rt, method: str, path: str, **kw):
    def deco(fn):
        return getattr(rt, method)(path, **kw)(_guarded(fn))
    return deco


# ── request models ──────────────────────────────────────────────────────────

class DocIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=200_000)
    source: Optional[str] = Field(default=None, max_length=500)
    classification: str = Field(default="INTERNAL", max_length=20)
    allowed_scopes: Optional[list[str]] = Field(default=None, max_length=20)


class QueryIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)


class MemoryIn(BaseModel):
    kind: str = Field(max_length=20)
    content: str = Field(min_length=1, max_length=8000)
    key: Optional[str] = Field(default=None, max_length=200)
    importance: float = Field(default=0.5, ge=0, le=1)
    shared: bool = False
    tags: Optional[list[str]] = Field(default=None, max_length=20)


class RecallIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kinds: Optional[list[str]] = Field(default=None, max_length=6)
    top_k: int = Field(default=5, ge=1, le=20)


class EraseIn(BaseModel):
    confirm: bool = False


class ExecuteIn(BaseModel):
    parallelism: int = Field(default=1, ge=1, le=8)
    retry_failed: bool = False


class PolicyIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    level: int = Field(ge=0, le=5)
    max_level: Optional[int] = Field(default=None, ge=0, le=5)
    reason: str = Field(default="", max_length=500)


class ShadowIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=200)
    proposal: dict[str, Any] = Field(default_factory=dict)


class DecisionIn(BaseModel):
    human: dict[str, Any] = Field(default_factory=dict)
    agreed: Optional[bool] = None


class SubjectIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)


class DryRunIn(BaseModel):
    tool: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class PeerIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    protocol: str = Field(max_length=10)
    url: str = Field(min_length=1, max_length=500)
    credential_env_var: Optional[str] = Field(default=None, max_length=100)
    allowed_tools: Optional[list[str]] = Field(default=None, max_length=100)
    risk_level: str = Field(default="MEDIUM", max_length=10)


class A2ASendIn(BaseModel):
    peer: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class EvalIn(BaseModel):
    suite: str = Field(min_length=1, max_length=100)


# ── knowledge ───────────────────────────────────────────────────────────────

@_route(router, "post", "/knowledge/docs")
def ingest_doc(body: DocIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = KnowledgeService(db, ctx).ingest(body.title, body.text, source=body.source,
                                           classification=body.classification,
                                           allowed_scopes=body.allowed_scopes)
    db.commit()
    return _respond(res, created=True)


@_route(read_router, "get", "/knowledge/docs")
def list_docs(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return {"documents": KnowledgeService(db, ctx).list_docs()}


@_route(router, "delete", "/knowledge/docs/{doc_id}")
def delete_doc(doc_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = KnowledgeService(db, ctx).delete(doc_id)
    db.commit()
    return _respond(res)


@_route(read_router, "post", "/knowledge/search")
def search_docs(body: QueryIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return {"results": KnowledgeService(db, ctx).search(body.query, top_k=body.top_k)}


@_route(read_router, "post", "/knowledge/answer")
def answer(body: QuestionIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    res = KnowledgeService(db, ctx).answer(body.question, top_k=body.top_k)
    db.commit()
    return _respond(res)


# ── memory ──────────────────────────────────────────────────────────────────

@_route(router, "post", "/memory")
def remember(body: MemoryIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = MemoryStore(db, ctx).remember(body.kind, body.content, key=body.key, importance=body.importance,
                                        shared=body.shared, tags=body.tags)
    db.commit()
    return _respond(res, created=True)


@_route(read_router, "post", "/memory/recall")
def recall(body: RecallIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    out = MemoryStore(db, ctx).recall(body.query, kinds=body.kinds, top_k=body.top_k)
    db.commit()
    return {"memories": out}


@_route(read_router, "get", "/memory/stats")
def memory_stats(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return MemoryStore(db, ctx).stats()


@_route(router, "post", "/memory/consolidate")
def consolidate(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = MemoryStore(db, ctx).consolidate()
    db.commit()
    return _respond(res)


@_route(router, "post", "/memory/erase")
def erase_memory(body: EraseIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    if not body.confirm:
        return _respond(MoResult(ResultState.BLOCKED, "Erasing all of your memory needs confirm=true."))
    res = MemoryStore(db, ctx).forget_all()
    db.commit()
    return _respond(res)


@_route(router, "delete", "/memory/{memory_id}")
def forget(memory_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = MemoryStore(db, ctx).forget(memory_id)
    db.commit()
    return _respond(res)


# ── orchestration runs ──────────────────────────────────────────────────────

@_route(router, "post", "/runs")
def create_run(plan: dict[str, Any] = Body(...), ctx: RequestContext = Depends(resolve_context),
               db: Session = Depends(get_db)):
    _write(ctx)
    return _respond(Orchestrator(db, ctx, commit=True).create(plan), created=True)


@_route(read_router, "get", "/runs")
def list_runs(limit: int = Query(50, ge=1, le=200), ctx: RequestContext = Depends(resolve_context),
              db: Session = Depends(get_db)):
    _read(ctx)
    return {"runs": Orchestrator(db, ctx).list_runs(limit)}


@_route(read_router, "get", "/runs/{run_id}")
def get_run(run_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    out = Orchestrator(db, ctx).describe(run_id)
    if not out:
        raise HTTPException(404, {"state": "FAILED", "detail": "No such run."})
    return out


@_route(router, "post", "/runs/{run_id}/execute")
def execute_run(run_id: str, body: ExecuteIn = ExecuteIn(), ctx: RequestContext = Depends(resolve_context),
                db: Session = Depends(get_db)):
    _write(ctx)
    return _respond(Orchestrator(db, ctx, commit=True).execute(
        run_id, parallelism=body.parallelism, retry_failed=body.retry_failed))


@_route(router, "post", "/runs/{run_id}/cancel")
def cancel_run(run_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    return _respond(Orchestrator(db, ctx, commit=True).cancel(run_id))


# ── autonomy and shadow learning ────────────────────────────────────────────

@_route(read_router, "get", "/autonomy")
def get_autonomy(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    from ..mo.control.autonomy import DEFAULT_LEVEL, DEFAULT_MAX_LEVEL, LEVELS
    return {"levels": LEVELS, "default_level": DEFAULT_LEVEL, "default_ceiling": DEFAULT_MAX_LEVEL,
            "policies": AutonomyManager(db, ctx).list_policies()}


@_route(router, "put", "/autonomy")
def set_autonomy(body: PolicyIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = AutonomyManager(db, ctx).set_policy(body.subject, body.level, max_level=body.max_level,
                                              reason=body.reason)
    db.commit()
    return _respond(res)


@_route(router, "post", "/autonomy/shadow")
def shadow_propose(body: ShadowIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = AutonomyManager(db, ctx).propose(body.subject, body.action, body.proposal)
    db.commit()
    return _respond(res, created=True)


@_route(router, "post", "/autonomy/shadow/{shadow_id}/decision")
def shadow_decide(shadow_id: str, body: DecisionIn, ctx: RequestContext = Depends(resolve_context),
                  db: Session = Depends(get_db)):
    _write(ctx)
    res = AutonomyManager(db, ctx).record_decision(shadow_id, body.human, agreed=body.agreed)
    db.commit()
    return _respond(res)


@_route(read_router, "get", "/autonomy/evidence")
def autonomy_evidence(subject: str = Query(..., min_length=1, max_length=200),
                      ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return AutonomyManager(db, ctx).evidence(subject)


@_route(router, "post", "/autonomy/promote")
def autonomy_promote(body: SubjectIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = AutonomyManager(db, ctx).promote(body.subject)
    db.commit()
    return _respond(res)


# ── dry-run and rollback ────────────────────────────────────────────────────

@_route(router, "post", "/control/dry-run")
def control_dry_run(body: DryRunIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    return dry_run(db, ctx, body.tool, body.payload)


@_route(read_router, "get", "/control/reversible")
def list_reversible(status: Optional[str] = Query(None, max_length=20),
                    ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return {"actions": ReversibleLog(db, ctx).list(status)}


@_route(router, "post", "/control/rollback/{reversible_id}")
def rollback(reversible_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    # approval_granted is never taken from the client: a HIGH-risk undo answers APPROVAL_REQUIRED.
    res = ReversibleLog(db, ctx).rollback(reversible_id, approval_granted=False)
    db.commit()
    return _respond(res)


# ── protocols: MCP and A2A ──────────────────────────────────────────────────

@_route(read_router, "get", "/protocols/peers")
def list_peers(ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return {"peers": PeerRegistry(db, ctx).list_peers()}


@_route(router, "post", "/protocols/peers")
def add_peer(body: PeerIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = PeerRegistry(db, ctx).add_peer(body.name, body.protocol, body.url,
                                         credential_env_var=body.credential_env_var,
                                         allowed_tools=body.allowed_tools, risk_level=body.risk_level)
    db.commit()
    return _respond(res, created=True)


@_route(router, "post", "/protocols/peers/{name}/discover")
def discover_peer(name: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = PeerRegistry(db, ctx).discover(name)
    db.commit()
    return _respond(res)


@_route(router, "post", "/protocols/peers/{name}/enable")
def enable_peer(name: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = PeerRegistry(db, ctx).set_enabled(name, True)
    db.commit()
    return _respond(res)


@_route(router, "post", "/protocols/peers/{name}/disable")
def disable_peer(name: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = PeerRegistry(db, ctx).set_enabled(name, False)
    db.commit()
    return _respond(res)


@_route(router, "delete", "/protocols/peers/{name}")
def remove_peer(name: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = PeerRegistry(db, ctx).remove_peer(name)
    db.commit()
    return _respond(res)


@_route(router, "post", "/protocols/mcp")
def mcp_endpoint(request: dict[str, Any] = Body(...), ctx: RequestContext = Depends(resolve_context),
                 db: Session = Depends(get_db)):
    """MCP server (JSON-RPC 2.0). Tools run under the caller's own context and governance."""
    _read(ctx)
    out = mcp_server.handle_jsonrpc(db, ctx, request)
    db.commit()
    if out is None:
        return Response(status_code=202)
    return out


@_route(read_router, "get", "/protocols/a2a/card")
def a2a_card(ctx: RequestContext = Depends(resolve_context)):
    _read(ctx)
    return a2a.agent_card(ctx)


@_route(router, "post", "/protocols/a2a/inbound")
def a2a_inbound(envelope: dict[str, Any] = Body(...), ctx: RequestContext = Depends(resolve_context),
                db: Session = Depends(get_db)):
    """Signed peer task. The caller still needs a tenant token; the HMAC proves which peer sent it."""
    _write(ctx)
    res = a2a.receive_task(db, ctx, envelope)
    db.commit()
    return _respond(res)


@_route(router, "post", "/protocols/a2a/send")
def a2a_send(body: A2ASendIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    res = a2a.send_task(db, ctx, body.peer, body.tool, body.payload)
    db.commit()
    return _respond(res)


# ── domain intelligence ─────────────────────────────────────────────────────

@_route(read_router, "get", "/domain/tools")
def domain_tools(ctx: RequestContext = Depends(resolve_context)):
    _read(ctx)
    return {"tools": [{"name": t.name, "description": t.description, "risk_level": t.risk_level,
                       "input_schema": t.input_schema}
                      for t in get_tool_registry().list() if t.name.startswith("domain.")]}


@_route(router, "post", "/domain/{tool}")
def run_domain_tool(tool: str, payload: dict[str, Any] = Body(default_factory=dict),
                    ctx: RequestContext = Depends(resolve_context)):
    _write(ctx)
    name = tool if tool.startswith("domain.") else f"domain.{tool}"
    if get_tool_registry().get(name) is None:
        raise HTTPException(404, {"state": "FAILED", "detail": f"No domain tool named '{name}'."})
    return _respond(get_tool_registry().invoke(ctx, name, payload))


# ── evaluation ──────────────────────────────────────────────────────────────

@_route(read_router, "get", "/evals/suites")
def eval_suites(ctx: RequestContext = Depends(resolve_context)):
    _read(ctx)
    out = []
    for n in suites.suite_names():
        s = suites.get_suite(n)
        out.append({"name": s.name, "cases": len(s.cases), "threshold": s.threshold})
    return {"suites": out}


@_route(router, "post", "/evals/run")
def eval_run(body: EvalIn, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _write(ctx)
    suite = suites.get_suite(body.suite)
    if suite is None:
        raise HTTPException(404, {"state": "FAILED", "detail": f"No suite named '{body.suite}'."})
    res = harness.run_suite(db, ctx, suite)
    db.commit()
    return _respond(res)


@_route(read_router, "get", "/evals/runs")
def eval_runs(suite: Optional[str] = Query(None, max_length=100), limit: int = Query(50, ge=1, le=200),
              ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    return {"runs": harness.list_runs(db, ctx, suite, limit)}


@_route(read_router, "get", "/evals/runs/{run_id}")
def eval_run_detail(run_id: str, ctx: RequestContext = Depends(resolve_context), db: Session = Depends(get_db)):
    _read(ctx)
    out = harness.get_run(db, ctx, run_id)
    if out is None:
        raise HTTPException(404, {"state": "FAILED", "detail": "No such evaluation run."})
    return out


# ── observability and manifest ──────────────────────────────────────────────

@_route(read_router, "get", "/observability/metrics")
def prometheus_metrics(ctx: RequestContext = Depends(resolve_context)):
    """Process-wide metrics span every tenant, so only an administrator may read them."""
    if not ctx.is_admin:
        return _respond(MoResult(ResultState.POLICY_DENIED, "Platform metrics are administrator-only."))
    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


@_route(read_router, "get", "/observability/traces")
def traces(trace_id: Optional[str] = Query(None, max_length=100), limit: int = Query(100, ge=1, le=500),
           tree: bool = False, ctx: RequestContext = Depends(resolve_context)):
    _read(ctx)
    if tree:
        if not trace_id:
            raise HTTPException(422, {"state": "FAILED", "detail": "tree=true needs a trace_id."})
        return {"trace": tracer.tree(ctx.tenant_id, trace_id)}
    return {"spans": tracer.traces(ctx.tenant_id, trace_id=trace_id, limit=limit)}


@_route(read_router, "get", "/manifest")
def capability_manifest(ctx: RequestContext = Depends(resolve_context)):
    """Feature-by-feature account of what is implemented, partial, credential-gated or planned."""
    _read(ctx)
    return _manifest.manifest()
