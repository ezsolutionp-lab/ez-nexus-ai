"""
Public market data (no account, no credential): the latest ticker for a trading pair from Kraken's public API.

This is READ-ONLY public data. There is no order, balance or withdrawal capability anywhere in MO's connectors; account
connectors (balances, orders) are deliberately not built. Override the base URL with MO_MARKET_DATA_URL. The result
is untrusted third-party data and is not investment advice.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

import httpx

from ..context import RequestContext
from ..errors import MoResult, ResultState
from ..protocols.netguard import check_url, pinned_client
from ..tools.spec import RiskLevel, ToolRegistry, ToolSpec

transport: Optional[httpx.BaseTransport] = None
_PAIR = re.compile(r"^[A-Za-z0-9]{3,12}$")


def _f(v: Any) -> float:
    return float(v)


def ticker(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
    pair = payload.get("pair", "")
    if not isinstance(pair, str) or not _PAIR.match(pair):
        return MoResult(ResultState.FAILED, "pair must be 3-12 letters or digits, for example XBTUSD.")
    base = os.getenv("MO_MARKET_DATA_URL", "https://api.kraken.com/0/public/Ticker")
    if (blocked := check_url(base)):
        return MoResult(ResultState.POLICY_DENIED, blocked)
    try:
        with pinned_client(timeout=10.0, transport=transport) as http:
            resp = http.get(base, params={"pair": pair})
    except httpx.TimeoutException:
        return MoResult(ResultState.TIMEOUT, "The market-data service did not answer in time.")
    except httpx.HTTPError as exc:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"The market-data service is unreachable: {type(exc).__name__}.")
    if resp.status_code == 429:
        return MoResult(ResultState.RATE_LIMITED, "The market-data service is rate limiting this address.")
    if resp.status_code != 200:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"The market-data service answered HTTP {resp.status_code}.")
    try:
        body = resp.json()
        if body.get("error"):
            return MoResult(ResultState.FAILED, "The market-data service rejected the request: " + "; ".join(map(str, body["error"]))[:200])
        (name, t), = body["result"].items()
        out = {"pair": name, "ask": _f(t["a"][0]), "bid": _f(t["b"][0]), "last": _f(t["c"][0]), "volume_24h": _f(t["v"][1]),
               "high_24h": _f(t["h"][1]), "low_24h": _f(t["l"][1]), "open_today": _f(t["o"]), "source": "kraken-public"}
    except (ValueError, KeyError, IndexError, TypeError):
        return MoResult(ResultState.FAILED, "The market-data service returned an unexpected body.")
    out["spread"] = round(out["ask"] - out["bid"], 8)
    return MoResult.ok(out, untrusted=True, note="Public data; not investment advice.")


def register_market_tools(registry: ToolRegistry) -> None:
    if registry.get("finance.market_ticker"):
        return
    registry.register(ToolSpec(
        name="finance.market_ticker", description="Latest public ticker for a trading pair (read-only; no account access).",
        handler=ticker, risk_level=RiskLevel.LOW, required_scopes=("domain:run",), rate_limit_per_minute=30, timeout_seconds=15,
        input_schema={"type": "object", "additionalProperties": False, "properties": {"pair": {"type": "string"}}, "required": ["pair"]}))


def register_vision_tool(registry: ToolRegistry) -> None:
    if registry.get("vision.analyze"):
        return
    from .. import perception

    def handler(ctx: RequestContext, payload: dict[str, Any]) -> MoResult:
        return perception.analyze(payload.get("image_b64"), ocr=bool(payload.get("ocr", True)))
    registry.register(ToolSpec(
        name="vision.analyze", description="Measure an image (size, brightness, sharpness, colours) and read printed text if OCR is installed.",
        handler=handler, risk_level=RiskLevel.LOW, required_scopes=("domain:run",), rate_limit_per_minute=30, timeout_seconds=30,
        input_schema={"type": "object", "additionalProperties": False,
                      "properties": {"image_b64": {"type": "string"}, "ocr": {"type": "boolean"}}, "required": ["image_b64"]}))
