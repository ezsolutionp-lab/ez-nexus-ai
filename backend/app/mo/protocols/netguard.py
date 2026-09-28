"""
Outbound-URL safety for protocol peers.

A peer URL is attacker-influenced input (an admin can be phished, a tenant can be
compromised). Without a guard, "register an MCP server" becomes "make the platform
fetch http://169.254.169.254/". The guard requires https (http only for loopback in
development), resolves the host and rejects private, loopback, link-local, multicast
and reserved addresses. It runs at registration and again before each call, so a name
that later resolves somewhere internal is caught. It narrows the DNS-rebinding window;
it cannot close it completely without pinning the resolved address at connect time.

Set MO_PROTOCOL_ALLOW_PRIVATE=1 to permit private targets (e.g. an in-VPC MCP server).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Optional
from urllib.parse import urlparse


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
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast \
                or addr.is_reserved or addr.is_unspecified:
            if not private_ok:
                return f"'{parts.hostname}' resolves to a non-public address ({addr}); refusing to call it."
    return None
