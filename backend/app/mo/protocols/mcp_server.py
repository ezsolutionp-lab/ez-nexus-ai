"""
MO NEXUS OMEGA — MCP server (JSON-RPC 2.0).

Lets an external MCP client use MO's tools. It is a thin protocol adapter over the
ToolRegistry, so every call still passes scope, approval, credential, rate-limit and audit
checks under the *caller's* identity. It exposes nothing extra:

  - only the caller's tenant context is used (the HTTP layer authenticates first);
  - tools the caller lacks scope for are not listed;
  - peer-proxied tools (kind mcp / a2a) are never re-exported, which prevents relay loops;
  - approval-gated tools report APPROVAL_REQUIRED as a tool error, never run silently.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..tools.spec import ToolRegistry, ToolSpec, get_tool_registry

PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "mo-nexus-omega", "version": "1.0"}
from .peers import HIDDEN_KINDS_FOR_A2A as HIDDEN_KINDS

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def _visible(ctx: RequestContext, spec: ToolSpec) -> bool:
    if spec.kind in HIDDEN_KINDS:
        return False
    return ctx.is_admin or all(s in ctx.scopes for s in spec.required_scopes)


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_jsonrpc(db: Session, ctx: RequestContext, request: Any,
                   registry: Optional[ToolRegistry] = None) -> Optional[dict[str, Any]]:
    """Returns the response object, or None for a notification (which has no response)."""
    reg = registry or get_tool_registry()
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return _error(request.get("id") if isinstance(request, dict) else None, INVALID_REQUEST,
                      "Not a valid JSON-RPC 2.0 request.")
    rid, method = request.get("id"), request["method"]
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _error(rid, INVALID_PARAMS, "params must be an object.")
    if "id" not in request:
        return None

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        tools = [{"name": t.name, "description": t.description,
                  "inputSchema": t.input_schema or {"type": "object"}}
                 for t in reg.list() if _visible(ctx, t)]
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(args, dict):
            return _error(rid, INVALID_PARAMS, "tools/call needs a string 'name' and an object 'arguments'.")
        spec = reg.get(name)
        if spec is None or not _visible(ctx, spec):
            return _error(rid, INVALID_PARAMS, f"Unknown tool '{name}'.")
        result = reg.invoke(ctx, name, args)
        chain.record(db, ctx, action="mcp.server.tools_call", result_state=result.state,
                     resource_type="tool", resource_id=name, detail=result.detail or "",
                     payload={"arguments": args})
        if result.state.is_success:
            text = json.dumps(chain.redact(result.data), default=str)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": f"{result.state.value}: {result.detail}"}], "isError": True}}
    return _error(rid, METHOD_NOT_FOUND, f"Method '{method}' is not supported.")
