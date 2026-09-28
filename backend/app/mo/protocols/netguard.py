"""
Outbound-URL safety for protocol peers.

A peer URL is attacker-influenced input (an admin can be phished, a tenant can be
compromised). Without a guard, "register an MCP server" becomes "make the platform
fetch http://169.254.169.254/". The guard requires https (http only for loopback in
development), resolves the host and rejects private, loopback, link-local, multicast
and reserved addresses. It runs at registration and again before each call, so a name
that later resolves somewhere internal is caught. `check_url` alone still leaves a
DNS-rebinding window between the check and the connection, so real calls go through
`pinned_client`: its transport resolves the host ONCE, validates every address it got, and connects
to that exact IP (Host header and TLS SNI/verification keep the original name). The name is never
resolved a second time, so a rebinding answer cannot redirect the connection. Redirects are not followed.

Set MO_PROTOCOL_ALLOW_PRIVATE=1 to permit private targets (e.g. an in-VPC MCP server).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, Optional
from urllib.parse import urlparse

import httpx


def allow_private() -> bool:
    return os.getenv("MO_PROTOCOL_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "yes")


def check_url(url: str) -> Optional[str]:
    """Return a reason the URL must not be called, or None if it is acceptable."""
    try:
        parts = urlparse(url)
    except ValueError:
        return "The URL is not valid."
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "Peer URLs must be http(s) with a host."
    if parts.username or parts.password:
        return "Credentials must not be embedded in the URL; use credential_env_var."
    private_ok = allow_private()
    if parts.scheme == "http" and not private_ok:
        return "Peer URLs must use https (set MO_PROTOCOL_ALLOW_PRIVATE=1 for local development)."
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"The host '{parts.hostname}' does not resolve."
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if _non_public(addr) and not private_ok:
            return f"'{parts.hostname}' resolves to a non-public address ({addr}); refusing to call it."
    return None


def _non_public(addr: "ipaddress._BaseAddress") -> bool:
    return (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
            or addr.is_reserved or addr.is_unspecified)


class BlockedAddress(httpx.ConnectError):
    """Raised (as a connection error) when a host resolves to an address the guard refuses."""


class PinnedTransport(httpx.BaseTransport):
    """Resolve once, validate every address, connect to that IP; the original name stays in Host and SNI."""

    def __init__(self, inner: Optional[httpx.BaseTransport] = None) -> None:
        self._inner = inner or httpx.HTTPTransport()

    def _resolve(self, host: str, port: int) -> str:
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
            addrs = [literal]
        except ValueError:
            try:
                infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            except socket.gaierror as exc:
                raise BlockedAddress(f"The host '{host}' does not resolve.") from exc
            addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
        if not allow_private():
            bad = next((a for a in addrs if _non_public(a)), None)
            if bad is not None:
                raise BlockedAddress(f"'{host}' resolves to a non-public address ({bad}); refusing to connect.")
        ranked = sorted(addrs, key=lambda a: a.version)              # prefer IPv4; every candidate was validated above
        return str(ranked[0])

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        host, port = url.host, url.port or (443 if url.scheme == "https" else 80)
        ip = self._resolve(host, port)
        netloc_ip = f"[{ip}]" if ":" in ip else ip
        new = httpx.Request(request.method, url.copy_with(host=netloc_ip), headers=request.headers, content=request.content,
                            extensions={**request.extensions, "sni_hostname": host})
        new.headers["Host"] = url.netloc.decode() if isinstance(url.netloc, bytes) else str(url.netloc)
        return self._inner.handle_request(new)

    def close(self) -> None:
        self._inner.close()


def pinned_client(*, timeout: float, transport: Optional[httpx.BaseTransport] = None, **kw: Any) -> httpx.Client:
    """An httpx client for outbound calls. A caller-supplied transport (tests) is used as-is; otherwise addresses are pinned."""
    kw.setdefault("follow_redirects", False)
    return httpx.Client(timeout=timeout, transport=transport if transport is not None else PinnedTransport(), **kw)
