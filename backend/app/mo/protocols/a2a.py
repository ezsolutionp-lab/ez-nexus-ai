"""
MO NEXUS OMEGA — Agent-to-Agent (A2A) tasking.

Two MO-compatible agents exchange *signed* task envelopes over HTTPS. This is a
deliberately small protocol, not the full public A2A spec: it authenticates the peer with
an HMAC-SHA256 over a canonical body, rejects stale or replayed messages, and runs the
task through the ToolRegistry under a restricted identity.

  Inbound  a task runs only if the peer is registered + enabled, the signature verifies,
           the timestamp is inside the replay window, the nonce is unused, and the tool is
           on that peer's allow-list. It executes with NO scopes and never as admin, so
           it can reach only tools that declare no required scope, and approval-gated
           tools report APPROVAL_REQUIRED. A peer can never widen its own reach.
  Outbound the reply must itself be signed; an unsigned or mis-signed reply is FAILED.

Replay nonces live in the database (mo_a2a_nonces), so every worker sharing the database rejects a
replayed message; the store is bounded per tenant and old rows are purged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..errors import MoResult, ResultState
from ..tools.spec import ToolRegistry, get_tool_registry
from .netguard import check_url
from .peers import HIDDEN_KINDS_FOR_A2A, PeerRegistry, _entries

REPLAY_WINDOW_SECONDS = 300
MAX_NONCES = 10_000
MAX_RESPONSE_BYTES = 1_000_000


def _canonical(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def sign(secret: str, body: dict[str, Any]) -> str:
    return hmac.new(secret.encode(), _canonical(body), hashlib.sha256).hexdigest()


def verify(secret: str, body: dict[str, Any], signature: str) -> bool:
    return isinstance(signature, str) and hmac.compare_digest(sign(secret, body), signature)


def claim_nonce(db: Session, tenant_id: str, peer: str, nonce: str, now: float) -> bool:
    """Record a nonce in the database so every worker sees it. False means it was already used (a replay)."""
    from datetime import datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from ..db import A2ANonce
    seen = datetime.utcfromtimestamp(now)
    db.query(A2ANonce).filter(A2ANonce.seen_at < seen - timedelta(seconds=REPLAY_WINDOW_SECONDS * 2)).delete()
    if db.query(A2ANonce).filter(A2ANonce.tenant_id == tenant_id).count() >= MAX_NONCES:
        return False
    try:
        with db.begin_nested():
            db.add(A2ANonce(tenant_id=tenant_id, peer=peer, nonce=nonce, seen_at=seen))
        return True
    except IntegrityError:
        return False


def agent_card(ctx: RequestContext, registry: Optional[ToolRegistry] = None) -> dict[str, Any]:
    reg = registry or get_tool_registry()
    skills = [{"name": t.name, "description": t.description, "risk_level": t.risk_level,
               "requires_approval": t.requires_approval}
              for t in reg.list() if t.kind not in HIDDEN_KINDS_FOR_A2A and not t.required_scopes]
    return {"name": "mo-nexus-omega", "protocol": "mo-a2a/1", "auth": "hmac-sha256",
            "replay_window_seconds": REPLAY_WINDOW_SECONDS,
            "note": "Inbound tasks run with no scopes; only scope-free tools on a peer's allow-list are reachable.",
            "skills": skills}


def build_envelope(secret: str, peer: str, tool: str, payload: dict[str, Any], *,
                   now: Optional[float] = None) -> dict[str, Any]:
    body = {"peer": peer, "timestamp": int(now if now is not None else time.time()),
            "nonce": secrets.token_hex(16), "task": {"tool": tool, "input": payload}}
    return {**body, "signature": sign(secret, body)}


# ── inbound ─────────────────────────────────────────────────────────────────

def receive_task(db: Session, ctx: RequestContext, envelope: Any, *, now: Optional[float] = None,
                 registry: Optional[ToolRegistry] = None) -> MoResult:
    reg = registry or get_tool_registry()
    now = now if now is not None else time.time()

    def refuse(state: ResultState, detail: str, peer: str = "?") -> MoResult:
        chain.record(db, ctx, action="a2a.inbound_refused", result_state=state, resource_type="a2a_peer",
                     resource_id=peer, detail=detail)
        return MoResult(state, detail)

    if not isinstance(envelope, dict) or not all(k in envelope for k in ("peer", "timestamp", "nonce", "task", "signature")):
        return refuse(ResultState.FAILED, "Malformed A2A envelope.")
    peer_name = str(envelope["peer"])
    row = PeerRegistry(db, ctx, reg).get_peer(peer_name)
    if row is None or row.protocol != "A2A":
        return refuse(ResultState.POLICY_DENIED, "Unknown A2A peer.", peer_name)
    if not row.is_enabled:
        return refuse(ResultState.POLICY_DENIED, "This A2A peer is disabled.", peer_name)
    secret = os.getenv(row.credential_env_var or "", "").strip()
    if not secret:
        return MoResult.credential_required(f"A2A peer {peer_name}", row.credential_env_var or "(unset)")
    body = {k: envelope[k] for k in ("peer", "timestamp", "nonce", "task")}
    if not verify(secret, body, envelope["signature"]):
        return refuse(ResultState.POLICY_DENIED, "Signature verification failed.", peer_name)
    try:
        age = abs(now - int(envelope["timestamp"]))
    except (TypeError, ValueError):
        return refuse(ResultState.FAILED, "Timestamp is not an integer.", peer_name)
    if age > REPLAY_WINDOW_SECONDS:
        return refuse(ResultState.POLICY_DENIED, f"Message is outside the {REPLAY_WINDOW_SECONDS}s replay window.", peer_name)
    if not claim_nonce(db, ctx.tenant_id, peer_name, str(envelope["nonce"])[:128], now):
        return refuse(ResultState.POLICY_DENIED, "Replayed nonce.", peer_name)

    task = envelope["task"]
    tool, args = (task.get("tool"), task.get("input") or {}) if isinstance(task, dict) else (None, None)
    if not isinstance(tool, str) or not isinstance(args, dict):
        return refuse(ResultState.FAILED, "task needs a string 'tool' and an object 'input'.", peer_name)
    if tool not in {e["name"] for e in _entries(row)}:
        return refuse(ResultState.POLICY_DENIED, f"Tool '{tool}' is not on this peer's allow-list.", peer_name)
    spec = reg.get(tool)
    if spec is None or spec.kind in HIDDEN_KINDS_FOR_A2A:
        return refuse(ResultState.FAILED, f"No such local tool '{tool}'.", peer_name)

    peer_ctx = RequestContext(tenant_id=ctx.tenant_id, actor_id=f"a2a:{peer_name}", actor_type="agent",
                              actor_label=f"A2A peer {peer_name}", is_admin=False, scopes=frozenset(),
                              source_channel=ctx.source_channel, data_classification=ctx.data_classification,
                              trace_id=ctx.trace_id, ip_address=ctx.ip_address)
    result = reg.invoke(peer_ctx, tool, args)
    chain.record(db, peer_ctx, action="a2a.inbound_task", result_state=result.state, resource_type="tool",
                 resource_id=tool, detail=result.detail or "", payload={"peer": peer_name, "input": args})
    return result


def sign_reply(secret: str, nonce: str, result: MoResult) -> dict[str, Any]:
    body = {"nonce": nonce, "state": result.state.value, "detail": result.detail,
            "data": chain.redact(result.data)}
    return {**body, "signature": sign(secret, body)}


# ── outbound ────────────────────────────────────────────────────────────────

def send_task(db: Session, ctx: RequestContext, peer_name: str, tool: str, payload: dict[str, Any], *,
              timeout: float = 20.0, transport: Optional[httpx.BaseTransport] = None) -> MoResult:
    row = PeerRegistry(db, ctx).get_peer(peer_name)
    if row is None or row.protocol != "A2A":
        return MoResult(ResultState.FAILED, f"No A2A peer named '{peer_name}'.")
    if not row.is_enabled:
        return MoResult(ResultState.POLICY_DENIED, "This A2A peer is disabled.")
    secret = os.getenv(row.credential_env_var or "", "").strip()
    if not secret:
        return MoResult.credential_required(f"A2A peer {peer_name}", row.credential_env_var or "(unset)")
    if (blocked := check_url(row.url)):
        return MoResult(ResultState.POLICY_DENIED, blocked)
    env = build_envelope(secret, peer_name, tool, payload)
    try:
        with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as http:
            resp = http.post(row.url, json=env)
    except httpx.TimeoutException:
        return MoResult(ResultState.TIMEOUT, f"A2A peer did not answer within {timeout}s.")
    except httpx.HTTPError as exc:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"A2A peer unreachable: {type(exc).__name__}: {exc}")
    if resp.status_code in (401, 403):
        return MoResult(ResultState.POLICY_DENIED, f"The A2A peer rejected the task (HTTP {resp.status_code}).")
    if resp.status_code >= 500:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"A2A peer error (HTTP {resp.status_code}).")
    if resp.status_code != 200:
        return MoResult(ResultState.FAILED, f"A2A peer answered HTTP {resp.status_code}.")
    try:
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeded the size limit")
        reply = resp.json()
        body = {k: reply[k] for k in ("nonce", "state", "detail", "data")}
        signature = reply["signature"]
    except (ValueError, KeyError, TypeError):
        return MoResult(ResultState.FAILED, "The A2A reply was malformed or unsigned.")
    if body["nonce"] != env["nonce"] or not verify(secret, body, signature):
        return MoResult(ResultState.FAILED, "The A2A reply failed signature verification; it was discarded.")
    try:
        state = ResultState(body["state"])
    except ValueError:
        return MoResult(ResultState.FAILED, f"The A2A reply carried unknown state '{body['state']}'.")
    chain.record(db, ctx, action="a2a.outbound_task", result_state=state, resource_type="a2a_peer",
                 resource_id=peer_name, detail=body["detail"] or "", payload={"tool": tool})
    if state.is_success:
        return MoResult.ok(body["data"] if isinstance(body["data"], dict) else {}, untrusted=True, peer=peer_name)
    return MoResult(state, body["detail"] or f"Peer reported {state.value}.", meta={"peer": peer_name})
