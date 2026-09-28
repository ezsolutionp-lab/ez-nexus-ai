"""
MO NEXUS OMEGA — OpenID Connect sign-in (SSO).

Verifies an ID token issued by the operator's identity provider and maps it to a local user. Nothing
is trusted by default:

  * only asymmetric algorithms (RS256/ES256 family) are accepted; HS* is refused, which closes the
    classic algorithm-confusion attack
  * signature, `iss`, `aud` and `exp` are all required; the key comes from the issuer's JWKS by `kid`
  * the email claim must be present and `email_verified` must be true
  * an unknown user is created only when MO_OIDC_AUTO_PROVISION=1, as a NON-admin; administrator rights
    come from a group claim listed in MO_OIDC_ADMIN_GROUPS, never from the token's own say-so alone

Configure with MO_OIDC_ISSUER, MO_OIDC_AUDIENCE and (optionally) MO_OIDC_JWKS_URL. Unit-tested against
locally generated keys; it has not been run against a live identity provider.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
import jwt

from ..errors import MoResult, ResultState
from ..protocols.netguard import check_url

ALLOWED_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256")
JWKS_TTL_SECONDS = 600
MAX_JWKS_BYTES = 200_000

transport: Optional[httpx.BaseTransport] = None          # tests inject a mock
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass
class OidcConfig:
    issuer: str
    audience: str
    jwks_url: str
    admin_groups: frozenset[str]
    groups_claim: str
    tenant_claim: str
    auto_provision: bool

    @classmethod
    def from_env(cls) -> Optional["OidcConfig"]:
        issuer, audience = os.getenv("MO_OIDC_ISSUER", "").strip(), os.getenv("MO_OIDC_AUDIENCE", "").strip()
        if not (issuer and audience):
            return None
        return cls(issuer=issuer, audience=audience,
                   jwks_url=os.getenv("MO_OIDC_JWKS_URL", "").strip() or issuer.rstrip("/") + "/.well-known/jwks.json",
                   admin_groups=frozenset(g.strip() for g in os.getenv("MO_OIDC_ADMIN_GROUPS", "").split(",") if g.strip()),
                   groups_claim=os.getenv("MO_OIDC_GROUPS_CLAIM", "groups"),
                   tenant_claim=os.getenv("MO_OIDC_TENANT_CLAIM", "tenant_id"),
                   auto_provision=os.getenv("MO_OIDC_AUTO_PROVISION", "") == "1")


def reset_cache() -> None:
    _jwks_cache.clear()


def _jwks(cfg: OidcConfig, *, force: bool = False) -> dict[str, Any]:
    cached = _jwks_cache.get(cfg.jwks_url)
    if cached and not force and time.time() - cached[0] < JWKS_TTL_SECONDS:
        return cached[1]
    if (blocked := check_url(cfg.jwks_url)):
        raise RuntimeError(blocked)
    with httpx.Client(timeout=10.0, transport=transport, follow_redirects=False) as http:
        resp = http.get(cfg.jwks_url)
    if resp.status_code != 200 or len(resp.content) > MAX_JWKS_BYTES:
        raise RuntimeError(f"the identity provider's key set is unavailable (HTTP {resp.status_code})")
    doc = resp.json()
    if not isinstance(doc, dict) or not isinstance(doc.get("keys"), list):
        raise RuntimeError("the identity provider's key set is malformed")
    _jwks_cache[cfg.jwks_url] = (time.time(), doc)
    return doc


def verify_id_token(token: str, cfg: Optional[OidcConfig] = None) -> MoResult:
    cfg = cfg or OidcConfig.from_env()
    if cfg is None:
        return MoResult.credential_required("OpenID Connect sign-in", "MO_OIDC_ISSUER / MO_OIDC_AUDIENCE")
    if not isinstance(token, str) or token.count(".") != 2 or len(token) > 8000:
        return MoResult(ResultState.POLICY_DENIED, "That is not a valid ID token.")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return MoResult(ResultState.POLICY_DENIED, "That is not a valid ID token.")
    if header.get("alg") not in ALLOWED_ALGS:
        return MoResult(ResultState.POLICY_DENIED, f"Signing algorithm '{header.get('alg')}' is not accepted.")
    kid = header.get("kid")
    try:
        keys = _jwks(cfg)["keys"]
        jwk = next((k for k in keys if k.get("kid") == kid), None)
        if jwk is None:                                   # the provider may have rotated keys: refetch once
            keys = _jwks(cfg, force=True)["keys"]
            jwk = next((k for k in keys if k.get("kid") == kid), None)
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        return MoResult(ResultState.PROVIDER_UNAVAILABLE, f"Could not fetch the identity provider's keys: {exc}")
    if jwk is None:
        return MoResult(ResultState.POLICY_DENIED, "The token was signed with an unknown key.")
    try:
        key = jwt.PyJWK(jwk).key
        claims = jwt.decode(token, key, algorithms=list(ALLOWED_ALGS), audience=cfg.audience, issuer=cfg.issuer,
                            options={"require": ["exp", "iss", "aud", "sub"]}, leeway=30)
    except jwt.ExpiredSignatureError:
        return MoResult(ResultState.POLICY_DENIED, "The ID token has expired.")
    except jwt.PyJWTError as exc:
        return MoResult(ResultState.POLICY_DENIED, f"The ID token was rejected: {type(exc).__name__}.")
    email = str(claims.get("email", "")).strip().lower()
    if not email or claims.get("email_verified") is not True:
        return MoResult(ResultState.POLICY_DENIED, "The token has no verified email address.")
    groups = claims.get(cfg.groups_claim, [])
    groups = groups if isinstance(groups, list) else [groups]
    return MoResult.ok({"email": email, "name": str(claims.get("name", ""))[:200], "subject": claims["sub"],
                        "is_admin": bool(cfg.admin_groups & {str(g) for g in groups}),
                        "tenant_id": str(claims.get(cfg.tenant_claim, "")) or None,
                        "auto_provision": cfg.auto_provision})
