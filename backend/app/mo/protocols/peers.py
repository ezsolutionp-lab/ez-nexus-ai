"""
MO NEXUS OMEGA — Protocol peer registry.

A peer is a remote MCP server or A2A agent that a tenant administrator has chosen to trust
*for specific tools only*. Nothing a peer advertises is exposed unless it is on the
allow-list, and every exposed tool goes through the ToolRegistry like any other tool
(scope, approval, credential, rate-limit, audit, metrics).

Remote tool output is untrusted: it is screened for prompt injection, a BLOCK verdict
withholds it, and it never gains tool authority.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import ProtocolPeer
from ..errors import MoResult, ResultState
from ..guards.injection import screen
from ..tools.spec import ToolRegistry, ToolSpec, get_tool_registry
from .mcp_client import McpClient
from .netguard import check_url

PEER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,119}$")
PROTOCOLS = ("MCP", "A2A")
RISKS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
MAX_ALLOWED_TOOLS = 50
HIDDEN_KINDS_FOR_A2A = frozenset({"mcp", "a2a"})


def tool_name(tenant_id: str, peer: str, tool: str) -> str:
    return f"mcp.{tenant_id}.{peer}.{tool}"


def tenant_prefix(tenant_id: str) -> str:
    return f"mcp.{tenant_id}."


def _entries(row: ProtocolPeer) -> list[dict[str, Any]]:
    try:
        data = json.loads(row.allowed_tools_json or "[]")
    except json.JSONDecodeError:
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("name"), str)]


def _view(row: ProtocolPeer) -> dict[str, Any]:
    entries = _entries(row)
    return {"id": row.id, "name": row.name, "protocol": row.protocol, "url": row.url,
            "credential_env_var": row.credential_env_var, "risk_level": row.risk_level,
            "enabled": row.is_enabled, "last_error": row.last_error,
            "allowed_tools": [e["name"] for e in entries],
            "discovered_tools": [e["name"] for e in entries if "inputSchema" in e]}


def _make_handler(tenant_id: str, url: str, env_var: Optional[str], remote_name: str):
    def handler(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
        if ctx.tenant_id != tenant_id:
            return MoResult(ResultState.POLICY_DENIED, "This peer tool belongs to another tenant.")
        result = McpClient(url, credential_env_var=env_var).call_tool(remote_name, payload)
        if not result.state.is_success:
            return result
        text = result.data.get("text", "")
        verdict = screen(text)
        if verdict.verdict == "BLOCK":
            return MoResult(ResultState.BLOCKED,
                            "Remote tool output looked like a prompt-injection attempt and was withheld "
                            f"(signals: {', '.join(verdict.signals)}).",
                            meta={"injection_score": verdict.score})
        result.meta.update(untrusted=True, injection_verdict=verdict.verdict, injection_signals=verdict.signals)
        return result
    return handler


class PeerRegistry:
    def __init__(self, db: Session, ctx: RequestContext, registry: Optional[ToolRegistry] = None):
        self.db, self.ctx = db, ctx
        self.registry = registry or get_tool_registry()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _row(self, name: str) -> Optional[ProtocolPeer]:
        return (self.db.query(ProtocolPeer)
                .filter(ProtocolPeer.tenant_id == self.ctx.tenant_id, ProtocolPeer.name == name).first())

    def _admin_only(self) -> Optional[MoResult]:
        if not self.ctx.is_admin:
            return MoResult(ResultState.POLICY_DENIED, "Only an administrator can manage protocol peers.")
        return None

    def _unregister_all(self, row: ProtocolPeer) -> None:
        prefix = tool_name(row.tenant_id, row.name, "")
        for n in [n for n in self.registry.names() if n.startswith(prefix)]:
            self.registry.unregister(n)

    def _register_row(self, row: ProtocolPeer) -> list[str]:
        self._unregister_all(row)
        if row.protocol != "MCP" or not row.is_enabled:
            return []
        names = []
        for e in _entries(row):
            if "inputSchema" not in e or not TOOL_NAME_RE.match(e["name"]):
                continue
            schema = e["inputSchema"] if isinstance(e["inputSchema"], dict) else {}
            spec = ToolSpec(
                name=tool_name(row.tenant_id, row.name, e["name"]),
                description=f"[{row.name}] {e.get('description') or e['name']}",
                handler=_make_handler(row.tenant_id, row.url, row.credential_env_var, e["name"]),
                kind="mcp", risk_level=row.risk_level, required_scopes=("mcp:invoke",),
                input_schema=schema, credential_env_var=row.credential_env_var, timeout_seconds=30)
            self.registry.register(spec, replace=True)
            names.append(spec.name)
        return names

    # ── admin operations ────────────────────────────────────────────────────

    def add_peer(self, name: str, protocol: str, url: str, *, credential_env_var: Optional[str] = None,
                 allowed_tools: Optional[list[str]] = None, risk_level: str = "MEDIUM") -> MoResult:
        if (denied := self._admin_only()):
            return denied
        protocol = protocol.upper()
        if protocol not in PROTOCOLS:
            return MoResult(ResultState.FAILED, f"protocol must be one of {PROTOCOLS}.")
        if not PEER_NAME_RE.match(name):
            return MoResult(ResultState.FAILED, "Peer name must be 1-40 chars of a-z, 0-9, '_' or '-'.")
        if risk_level not in RISKS:
            return MoResult(ResultState.FAILED, f"risk_level must be one of {RISKS}.")
        if credential_env_var and not ENV_VAR_RE.match(credential_env_var):
            return MoResult(ResultState.FAILED, "credential_env_var must be an UPPER_SNAKE_CASE environment variable name.")
        if protocol == "A2A" and not credential_env_var:
            return MoResult(ResultState.FAILED, "A2A peers need a credential_env_var holding the shared signing secret.")
        allowed = list(dict.fromkeys(allowed_tools or []))
        if len(allowed) > MAX_ALLOWED_TOOLS or not all(isinstance(t, str) and TOOL_NAME_RE.match(t) for t in allowed):
            return MoResult(ResultState.FAILED, f"allowed_tools must be up to {MAX_ALLOWED_TOOLS} valid tool names.")
        if (problem := check_url(url)):
            return MoResult(ResultState.POLICY_DENIED, problem)
        if self._row(name) is not None:
            return MoResult(ResultState.BLOCKED, f"A peer named '{name}' already exists.")
        row = ProtocolPeer(tenant_id=self.ctx.tenant_id, created_by=self.ctx.actor_id, name=name,
                           protocol=protocol, url=url, credential_env_var=credential_env_var,
                           allowed_tools_json=json.dumps([{"name": t} for t in allowed]),
                           risk_level=risk_level)
        self.db.add(row)
        self.db.flush()
        chain.record(self.db, self.ctx, action="protocol.peer_added", result_state=ResultState.SUCCESS,
                     resource_type="protocol_peer", resource_id=row.id, detail=f"{protocol} {name}",
                     payload={"name": name, "protocol": protocol, "url": url, "allowed": allowed,
                              "risk_level": risk_level})
        return MoResult.ok(_view(row))

    def discover(self, name: str) -> MoResult:
        """Ask the remote MCP server what it offers and register only the allow-listed tools."""
        if (denied := self._admin_only()):
            return denied
        row = self._row(name)
        if row is None:
            return MoResult(ResultState.FAILED, f"No peer named '{name}'.")
        if row.protocol != "MCP":
            return MoResult(ResultState.FAILED, "Tool discovery applies to MCP peers only.")
        listing = McpClient(row.url, credential_env_var=row.credential_env_var).list_tools()
        if not listing.state.is_success:
            row.last_error = listing.detail
            self.db.flush()
            return listing
        remote = {t["name"]: t for t in listing.data["tools"]}
        entries, missing = [], []
        for e in _entries(row):
            t = remote.get(e["name"])
            if t is None:
                missing.append(e["name"])
                entries.append({"name": e["name"]})
                continue
            entries.append({"name": e["name"], "description": str(t.get("description", ""))[:500],
                            "inputSchema": t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}})
        row.allowed_tools_json = json.dumps(entries)
        row.last_error = None if not missing else f"Allow-listed tools not offered by the server: {', '.join(missing)}"
        self.db.flush()
        registered = self._register_row(row)
        chain.record(self.db, self.ctx, action="protocol.peer_discovered", result_state=ResultState.SUCCESS,
                     resource_type="protocol_peer", resource_id=row.id,
                     detail=f"{len(registered)} tool(s) registered",
                     payload={"registered": registered, "missing": missing,
                              "offered_but_not_allowed": sorted(set(remote) - {e['name'] for e in entries})})
        return MoResult.ok({"registered": registered, "missing": missing,
                            "offered_but_not_allowed": sorted(set(remote) - {e["name"] for e in entries}),
                            "server": listing.data["server"]})

    def set_enabled(self, name: str, enabled: bool) -> MoResult:
        if (denied := self._admin_only()):
            return denied
        row = self._row(name)
        if row is None:
            return MoResult(ResultState.FAILED, f"No peer named '{name}'.")
        row.is_enabled = enabled
        self.db.flush()
        self._register_row(row)
        chain.record(self.db, self.ctx, action="protocol.peer_enabled" if enabled else "protocol.peer_disabled",
                     result_state=ResultState.SUCCESS, resource_type="protocol_peer", resource_id=row.id,
                     detail=name)
        return MoResult.ok(_view(row))

    def remove_peer(self, name: str) -> MoResult:
        if (denied := self._admin_only()):
            return denied
        row = self._row(name)
        if row is None:
            return MoResult(ResultState.FAILED, f"No peer named '{name}'.")
        self._unregister_all(row)
        rid = row.id
        self.db.delete(row)
        self.db.flush()
        chain.record(self.db, self.ctx, action="protocol.peer_removed", result_state=ResultState.SUCCESS,
                     resource_type="protocol_peer", resource_id=rid, detail=name)
        return MoResult.ok({"removed": name})

    # ── reads ───────────────────────────────────────────────────────────────

    def list_peers(self) -> list[dict[str, Any]]:
        rows = (self.db.query(ProtocolPeer).filter(ProtocolPeer.tenant_id == self.ctx.tenant_id)
                .order_by(ProtocolPeer.name).all())
        return [_view(r) for r in rows]

    def get_peer(self, name: str) -> Optional[ProtocolPeer]:
        return self._row(name)

    def tools(self) -> list[dict[str, Any]]:
        """This tenant's registered peer tools — never another tenant's."""
        prefix = tenant_prefix(self.ctx.tenant_id)
        return [t.to_dict() for t in self.registry.list(kind="mcp") if t.name.startswith(prefix)]


def load_registered(db: Session, registry: Optional[ToolRegistry] = None) -> int:
    """Re-register discovered, enabled MCP peers after a restart. No network access."""
    reg = registry or get_tool_registry()
    count = 0
    for row in db.query(ProtocolPeer).filter(ProtocolPeer.is_enabled.is_(True), ProtocolPeer.protocol == "MCP").all():
        ctx = RequestContext(tenant_id=row.tenant_id, actor_id="system", actor_type="system")
        count += len(PeerRegistry(db, ctx, reg)._register_row(row))
    return count
