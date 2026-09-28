"""
MO NEXUS OMEGA — MCP client (Model Context Protocol over HTTP, JSON-RPC 2.0).

A real client: it performs `initialize`, `tools/list` and `tools/call` against a remote
server and reports what actually happened. It never echoes, never fabricates a tool
result, and maps every failure to a truthful MoResult state:

  no credential configured        CREDENTIAL_REQUIRED
  connection refused / DNS / 5xx  PROVIDER_UNAVAILABLE
  timeout                         TIMEOUT
  401 / 403                       POLICY_DENIED (the remote rejected our credential)
  JSON-RPC error / isError        FAILED, with the remote's message
  malformed response              FAILED

Both plain JSON and single-event `text/event-stream` responses are accepted, matching
the Streamable HTTP transport. Remote output is untrusted and size-capped.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

from ..errors import MoResult, ResultState
from .netguard import check_url

PROTOCOL_VERSION = "2025-03-26"
MAX_RESPONSE_BYTES = 1_000_000


class McpClient:
    def __init__(self, url: str, *, credential_env_var: Optional[str] = None, timeout: float = 15.0,
                 transport: Optional[httpx.BaseTransport] = None, client_name: str = "mo-nexus-omega"):
        self.url, self.env_var, self.timeout = url, credential_env_var, timeout
        self._transport = transport
        self._session_id: Optional[str] = None
        self._next_id = 0
        self._initialized = False
        self.client_name = client_name
        self.server_info: dict[str, Any] = {}

    # ── transport ───────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.env_var:
            h["Authorization"] = f"Bearer {os.environ[self.env_var].strip()}"
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    @staticmethod
    def _parse_body(resp: httpx.Response) -> Any:
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeded the size limit")
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype:
            data = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
            if not data:
                raise ValueError("event stream carried no data")
            return json.loads(data[-1])
        return json.loads(text)

    def _rpc(self, method: str, params: Optional[dict] = None, *, notify: bool = False) -> MoResult:
        if self.env_var and not os.getenv(self.env_var, "").strip():
            return MoResult.credential_required(f"MCP server {self.url}", self.env_var)
        blocked = check_url(self.url)
        if blocked:
            return MoResult(ResultState.POLICY_DENIED, blocked)
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._next_id += 1
            body["id"] = self._next_id
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport, follow_redirects=False) as http:
                resp = http.post(self.url, json=body, headers=self._headers())
        except httpx.TimeoutException:
            return MoResult(ResultState.TIMEOUT, f"MCP server did not answer '{method}' within {self.timeout}s.")
        except httpx.HTTPError as exc:
            return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"MCP server unreachable: {type(exc).__name__}: {exc}")
        if resp.status_code in (401, 403):
            return MoResult(ResultState.POLICY_DENIED, f"The MCP server rejected our credentials (HTTP {resp.status_code}).")
        if 300 <= resp.status_code < 400:
            return MoResult(ResultState.FAILED, "The MCP server redirected the request; redirects are not followed.")
        if resp.status_code >= 500:
            return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"MCP server error (HTTP {resp.status_code}).")
        if resp.status_code >= 400:
            return MoResult(ResultState.FAILED, f"MCP server refused the request (HTTP {resp.status_code}).")
        if sid := resp.headers.get("mcp-session-id"):
            self._session_id = sid
        if notify:
            return MoResult.ok({})
        try:
            msg = self._parse_body(resp)
        except (ValueError, json.JSONDecodeError) as exc:
            return MoResult(ResultState.FAILED, f"Malformed MCP response: {exc}")
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return MoResult(ResultState.FAILED, "The response was not a JSON-RPC 2.0 message.")
        if msg.get("id") != body["id"]:
            return MoResult(ResultState.FAILED, "The response id did not match the request id.")
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {}
            return MoResult(ResultState.FAILED, f"MCP error {err.get('code')}: {err.get('message', 'unknown error')}")
        if "result" not in msg:
            return MoResult(ResultState.FAILED, "The JSON-RPC response had neither result nor error.")
        return MoResult.ok({"result": msg["result"]})

    # ── protocol ────────────────────────────────────────────────────────────

    def initialize(self) -> MoResult:
        if self._initialized:
            return MoResult.ok({"server": self.server_info})
        r = self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": {"name": self.client_name, "version": "1.0"}})
        if not r.state.is_success:
            return r
        self.server_info = r.data["result"].get("serverInfo", {}) if isinstance(r.data["result"], dict) else {}
        self._rpc("notifications/initialized", notify=True)
        self._initialized = True
        return MoResult.ok({"server": self.server_info})

    def list_tools(self) -> MoResult:
        init = self.initialize()
        if not init.state.is_success:
            return init
        tools: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(20):                                  # bounded pagination
            r = self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            if not r.state.is_success:
                return r
            res = r.data["result"]
            if not isinstance(res, dict) or not isinstance(res.get("tools"), list):
                return MoResult(ResultState.FAILED, "tools/list returned no 'tools' array.")
            tools += [t for t in res["tools"] if isinstance(t, dict) and isinstance(t.get("name"), str)]
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return MoResult.ok({"tools": tools, "server": self.server_info})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MoResult:
        init = self.initialize()
        if not init.state.is_success:
            return init
        r = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if not r.state.is_success:
            return r
        res = r.data["result"]
        if not isinstance(res, dict):
            return MoResult(ResultState.FAILED, "tools/call returned a non-object result.")
        content = res.get("content", [])
        text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if res.get("isError"):
            return MoResult(ResultState.FAILED, text or "The remote tool reported an error.")
        return MoResult.ok({"text": text, "content": content, "structured": res.get("structuredContent")})
