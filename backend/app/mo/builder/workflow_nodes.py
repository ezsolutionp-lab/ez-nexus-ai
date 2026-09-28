"""
MO NEXUS OMEGA — executors for the workflow node types that need more than a one-liner.

Agent      a governed model call (input/output guards, budget, CREDENTIAL_REQUIRED without a provider)
API        an outbound HTTP call through the SSRF guard; anything other than GET needs a granted approval
Webhook    an outbound signed POST; always an external side effect, so always approval-gated
Database   get / put / delete / list in a tenant-scoped key-value store (mo_kv)
Transform  a fixed set of declarative operations; there is no eval and no code execution
Human Task raises a real approval and stops until a person decides it
Subworkflow runs another workflow of the same tenant (depth-limited, cycle-checked)
Switch / Loop / Parallel  control flow over nested node lists. Parallel branches are isolated from each
           other and merged afterwards; they run one after another in this build, not on threads
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
from typing import Any, Callable, Optional

import httpx

from ..approvals import engine as approvals
from ..db import BuilderWorkflow, KeyValueEntry
from ..errors import MoResult, ResultState
from ..guards import pipeline
from ..protocols.netguard import check_url, pinned_client

MAX_STEPS = 500
MAX_DEPTH = 5
MAX_LOOP = 100
MAX_KV_VALUE = 64 * 1024
MAX_KV_KEYS = 1000
MAX_RESPONSE = 1_000_000
_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
_FORBIDDEN_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}
_MISSING = object()


def get_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit() and -len(cur) <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
    return cur


def render(value: Any, context: dict[str, Any]) -> Any:
    """Substitute {{path}} in strings (recursively). A string that is exactly one placeholder keeps its type."""
    if isinstance(value, str):
        m = _TEMPLATE.fullmatch(value.strip())
        if m:
            got = get_path(context, m.group(1))
            return None if got is _MISSING else got
        return _TEMPLATE.sub(lambda mm: "" if (g := get_path(context, mm.group(1))) is _MISSING else str(g), value)
    if isinstance(value, list):
        return [render(v, context) for v in value]
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    return value


def _fail(detail: str, state: ResultState = ResultState.FAILED, **data: Any) -> MoResult:
    return MoResult(state, detail, data=data or None)


class Env:
    """Shared, mutable state of one workflow run (including nested runs)."""

    def __init__(self, db, ctx, tools, workflow, context_data, approval_id, transport, run_workflow):
        self.db, self.ctx, self.tools, self.workflow = db, ctx, tools, workflow
        self.context, self.approval_id, self.transport = context_data, approval_id, transport
        self.run_workflow = run_workflow          # callable(row, env, depth) -> MoResult, for Subworkflow
        self.steps = 0
        self.depth = 0
        self.visited: list[str] = [workflow.id]

    def granted(self) -> bool:
        return approvals.is_granted(self.db, self.ctx, self.approval_id)


# ── HTTP ────────────────────────────────────────────────────────────────────

def _http(env: Env, node: dict, *, method: str, signed: bool) -> MoResult:
    url = render(node.get("url", ""), env.context)
    if not isinstance(url, str) or not url:
        return _fail("The node needs a 'url'.")
    if method != "GET" and not env.granted():
        return MoResult(ResultState.APPROVAL_REQUIRED,
                        f"A {method} call is an external side effect and needs a granted approval before it runs.")
    if (blocked := check_url(url)):
        return MoResult(ResultState.POLICY_DENIED, blocked)
    headers = {}
    for k, v in (node.get("headers") or {}).items():
        if str(k).lower() in _FORBIDDEN_HEADERS:
            return _fail(f"Header '{k}' cannot be set in a node; use credential_env_var.")
        headers[str(k)] = str(render(v, env.context))
    cred = node.get("credential_env_var")
    if cred:
        secret = os.getenv(cred, "").strip()
        if not secret:
            return MoResult.credential_required(f"{node.get('id', 'API node')}", cred)
        headers["Authorization"] = f"Bearer {secret}"
    body = render(node.get("body"), env.context) if "body" in node else None
    content = None
    if body is not None:
        content = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        headers.setdefault("Content-Type", "application/json")
    if signed:
        key_var = node.get("secret_env_var", "")
        key = os.getenv(key_var, "").strip() if key_var else ""
        if not key:
            return MoResult.credential_required("webhook signing secret", key_var or "(secret_env_var not set)")
        headers["X-MO-Signature"] = "sha256=" + hmac.new(key.encode(), content or b"", hashlib.sha256).hexdigest()
    timeout = min(float(node.get("timeout_seconds", 10)), 15.0)
    try:
        with pinned_client(timeout=timeout, transport=env.transport) as http:
            resp = http.request(method, url, headers=headers, content=content)
    except httpx.TimeoutException:
        return MoResult(ResultState.TIMEOUT, f"{method} {url} timed out after {timeout}s.")
    except httpx.HTTPError as exc:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"{method} {url} failed: {type(exc).__name__}")
    if len(resp.content) > MAX_RESPONSE:
        return _fail("The response exceeded the size limit and was discarded.")
    if resp.status_code >= 500:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"The remote answered HTTP {resp.status_code}.")
    if resp.status_code in (401, 403):
        return MoResult(ResultState.POLICY_DENIED, f"The remote rejected the call (HTTP {resp.status_code}).")
    if resp.status_code >= 400:
        return _fail(f"The remote answered HTTP {resp.status_code}.", status_code=resp.status_code)
    try:
        payload: Any = resp.json()
    except ValueError:
        payload = resp.text[:20_000]
    return MoResult.ok({"status_code": resp.status_code, "body": payload}, untrusted=True)


def run_api(env: Env, node: dict) -> MoResult:
    method = str(node.get("method", "GET")).upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return _fail(f"Unsupported method '{method}'.")
    return _http(env, node, method=method, signed=False)


def run_webhook(env: Env, node: dict) -> MoResult:
    return _http(env, node, method="POST", signed=True)


# ── model ───────────────────────────────────────────────────────────────────

def run_agent(env: Env, node: dict) -> MoResult:
    from ..modelfabric.router import ModelRequest, get_router
    prompt = render(node.get("prompt", ""), env.context)
    if not isinstance(prompt, str) or not prompt.strip():
        return _fail("The Agent node needs a 'prompt'.")
    guarded = pipeline.guard_input(prompt, env.ctx, env.db)
    if guarded.blocked:
        return MoResult(ResultState.POLICY_DENIED, guarded.reason)
    req = ModelRequest(prompt=guarded.text, system=str(node.get("system", "")), capability=node.get("capability", "general"),
                       max_tokens=min(int(node.get("max_tokens", 800)), 4000), max_cost_usd=float(node.get("max_cost_usd", 0.10)),
                       data_classification=env.ctx.data_classification)
    res = get_router().complete(req)
    if not res.state.is_success:
        return res
    out = pipeline.guard_output(str(res.data.get("text", "") if isinstance(res.data, dict) else res.data), env.ctx, env.db)
    if out.blocked:
        return MoResult(ResultState.POLICY_DENIED, out.reason)
    return MoResult.ok({"text": out.text}, untrusted=True)


# ── data ────────────────────────────────────────────────────────────────────

def run_database(env: Env, node: dict) -> MoResult:
    op = node.get("operation")
    ns = str(render(node.get("namespace", f"wf:{env.workflow.id}"), env.context))[:80]
    key = render(node.get("key", ""), env.context)
    q = env.db.query(KeyValueEntry).filter(KeyValueEntry.tenant_id == env.ctx.tenant_id, KeyValueEntry.namespace == ns)
    if op == "list":
        rows = q.order_by(KeyValueEntry.key).limit(200).all()
        return MoResult.ok({"keys": [r.key for r in rows], "count": len(rows)})
    if not isinstance(key, str) or not key or len(key) > 200:
        return _fail("key must be 1-200 characters.")
    row = q.filter(KeyValueEntry.key == key).first()
    if op == "get":
        return MoResult.ok({"key": key, "found": row is not None, "value": json.loads(row.value_json) if row else None})
    if op == "delete":
        if row is not None:
            env.db.delete(row)
            env.db.flush()
        return MoResult.ok({"key": key, "deleted": row is not None})
    if op == "put":
        value = render(node.get("value"), env.context)
        raw = json.dumps(value, default=str)
        if len(raw) > MAX_KV_VALUE:
            return _fail(f"The value exceeds {MAX_KV_VALUE} bytes.")
        if row is None:
            if q.count() >= MAX_KV_KEYS:
                return _fail(f"A namespace holds at most {MAX_KV_KEYS} keys.")
            env.db.add(KeyValueEntry(tenant_id=env.ctx.tenant_id, created_by=env.ctx.actor_id, namespace=ns, key=key, value_json=raw))
        else:
            row.value_json = raw
        env.db.flush()
        return MoResult.ok({"key": key, "stored": True})
    return _fail("operation must be one of get, put, delete, list.")


def _op_set(ctx: dict, o: dict) -> None:
    ctx[o["key"]] = render(o.get("value"), ctx)


def _op_copy(ctx: dict, o: dict) -> None:
    got = get_path(ctx, o["from"])
    if got is _MISSING:
        raise ValueError(f"copy: '{o['from']}' does not exist")
    ctx[o["to"]] = copy.deepcopy(got)


def _op_rename(ctx: dict, o: dict) -> None:
    if o["from"] not in ctx:
        raise ValueError(f"rename: '{o['from']}' does not exist")
    ctx[o["to"]] = ctx.pop(o["from"])


def _op_delete(ctx: dict, o: dict) -> None:
    ctx.pop(o["key"], None)


def _op_pick(ctx: dict, o: dict) -> None:
    keys = o["keys"]
    for k in [k for k in ctx if k not in keys]:
        del ctx[k]


def _unary(fn: Callable[[Any], Any]):
    def op(ctx: dict, o: dict) -> None:
        got = get_path(ctx, o["from"])
        if got is _MISSING:
            raise ValueError(f"'{o['from']}' does not exist")
        ctx[o.get("to", o["from"])] = fn(got)
    return op


def _sum(v: Any) -> Any:
    if not isinstance(v, list) or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        raise ValueError("sum needs a list of numbers")
    return sum(v)


def _join(v: Any) -> str:
    if not isinstance(v, list):
        raise ValueError("join needs a list")
    return ", ".join(str(x) for x in v)


TRANSFORMS: dict[str, Callable[[dict, dict], None]] = {
    "set": _op_set, "copy": _op_copy, "rename": _op_rename, "delete": _op_delete, "pick": _op_pick,
    "upper": _unary(lambda v: str(v).upper()), "lower": _unary(lambda v: str(v).lower()),
    "strip": _unary(lambda v: str(v).strip()), "to_int": _unary(int), "to_float": _unary(float),
    "len": _unary(lambda v: len(v)), "sum": _unary(_sum), "join": _unary(_join),
}


def run_transform(env: Env, node: dict) -> MoResult:
    ops = node.get("operations")
    if not isinstance(ops, list) or not ops or len(ops) > 100:
        return _fail("operations must be a list of 1-100 operations.")
    work = copy.deepcopy(env.context)
    try:
        for o in ops:
            fn = TRANSFORMS.get(o.get("op")) if isinstance(o, dict) else None
            if fn is None:
                return _fail(f"Unknown transform operation {o!r}. Allowed: {', '.join(sorted(TRANSFORMS))}.")
            fn(work, o)
    except (KeyError, ValueError, TypeError) as exc:
        return _fail(f"Transform failed: {type(exc).__name__}: {exc}")
    env.context.clear()
    env.context.update(work)                       # applied only when every operation succeeded
    return MoResult.ok({"operations": len(ops)})


# ── people & composition ────────────────────────────────────────────────────

def run_human_task(env: Env, node: dict) -> MoResult:
    if env.granted():
        return MoResult.ok({"completed": True})
    if env.approval_id:
        return MoResult(ResultState.PENDING_APPROVAL, "The human task has not been completed yet.",
                        meta={"approval_id": env.approval_id})
    req = approvals.request_approval(env.db, env.ctx, action="workflow.human_task", resource_type="workflow",
                                     resource_id=env.workflow.id, risk_tier="MEDIUM",
                                     reason=str(render(node.get("instruction", "A person must complete this step."), env.context))[:500])
    return MoResult(ResultState.PENDING_APPROVAL, "Waiting for a person to complete this task.",
                    data={"approval_id": req.id}, meta={"approval_id": req.id})


def run_subworkflow(env: Env, node: dict) -> MoResult:
    wid = node.get("workflow_id")
    if not isinstance(wid, str) or not wid:
        return _fail("The Subworkflow node needs a 'workflow_id'.")
    if env.depth >= MAX_DEPTH:
        return _fail(f"Subworkflows may nest at most {MAX_DEPTH} deep.")
    if wid in env.visited:
        return _fail(f"Subworkflow cycle detected at '{wid}'.")
    row = env.db.get(BuilderWorkflow, wid)
    if row is None or row.tenant_id != env.ctx.tenant_id:
        return _fail(f"No such workflow '{wid}'.")
    env.visited.append(wid)
    env.depth += 1
    try:
        return env.run_workflow(row, env)
    finally:
        env.depth -= 1
        env.visited.pop()
