"""
MO NEXUS OMEGA — Deployment adapters.

Nothing deploys unless an operator selects an adapter with MO_DEPLOY_ADAPTER, and even then only after the
existing approval gate has been passed. With no adapter selected, execute_deployment reports
CREDENTIAL_REQUIRED and nothing leaves the system — that default is unchanged.

  export-bundle  Writes a versioned, checksummed ZIP of the generated project (Dockerfile and compose files
                 included) under MO_DEPLOY_ARTIFACT_DIR. Nothing is launched. Result: PARTIAL.
  deploy-hook    POSTs a signed payload to the deploy-hook URL the operator configured for the environment
                 (MO_DEPLOY_HOOK_STAGING_URL / MO_DEPLOY_HOOK_PRODUCTION_URL; hosts such as Railway, Vercel,
                 Render and Netlify offer these). The SSRF guard applies. A 2xx means the host ACCEPTED the
                 trigger; MO does not watch the host's build, so the result is PARTIAL, never SUCCESS.

There is deliberately no adapter that talks to a cloud provider's management API: that needs provider-specific
credentials and project wiring MO cannot verify from here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from ..context import RequestContext
from ..db import BuilderDeployment, BuilderProject
from ..errors import MoResult, ResultState
from ..protocols.netguard import check_url, pinned_client
from .export import export_zip

transport: Optional[httpx.BaseTransport] = None          # tests inject a mock


class DeployAdapter(ABC):
    name = "abstract"
    description = ""

    @abstractmethod
    def deploy(self, db: Session, ctx: RequestContext, project: BuilderProject,
               deployment: BuilderDeployment) -> MoResult: ...

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


class ExportBundleAdapter(DeployAdapter):
    name = "export-bundle"
    description = "Writes a checksummed deployable ZIP; launches nothing."

    def deploy(self, db, ctx, project, deployment) -> MoResult:
        built = export_zip(db, ctx, project)
        if not built.state.is_success:
            return built
        data: bytes = built.meta["archive"]
        root = Path(os.getenv("MO_DEPLOY_ARTIFACT_DIR", "./mo_deployments")).resolve()
        target = root / ctx.tenant_id / project.id
        target.mkdir(parents=True, exist_ok=True)
        stem = f"{deployment.environment}-v{deployment.version}-{deployment.id[:8]}"
        digest = hashlib.sha256(data).hexdigest()
        (target / f"{stem}.zip").write_bytes(data)
        (target / f"{stem}.json").write_text(json.dumps({
            "project_id": project.id, "version": deployment.version, "environment": deployment.environment,
            "deployment_id": deployment.id, "sha256": digest, "bytes": len(data),
            "created_at": datetime.utcnow().isoformat() + "Z", "launched": False}, indent=2))
        return MoResult(ResultState.PARTIAL,
                        f"Deployment bundle written ({len(data)} bytes, sha256 {digest[:12]}…). Nothing was launched: "
                        "run the bundle's docker-compose or hand it to your host.",
                        data={"bundle": str(target / f"{stem}.zip"), "sha256": digest, "bytes": len(data), "launched": False})


class DeployHookAdapter(DeployAdapter):
    name = "deploy-hook"
    description = "Triggers the operator's deploy hook for the environment; the host's build is not tracked."

    def deploy(self, db, ctx, project, deployment) -> MoResult:
        var = f"MO_DEPLOY_HOOK_{deployment.environment.upper()}_URL"
        url = os.getenv(var, "").strip()
        if not url:
            return MoResult.credential_required(f"deploy hook for {deployment.environment}", var)
        if (blocked := check_url(url)):
            return MoResult(ResultState.POLICY_DENIED, blocked)
        body = json.dumps({"project_id": project.id, "project": project.name, "version": deployment.version,
                           "environment": deployment.environment, "deployment_id": deployment.id,
                           "requested_by": deployment.requested_by}, sort_keys=True).encode()
        headers = {"Content-Type": "application/json"}
        secret = os.getenv("MO_DEPLOY_HOOK_SECRET", "").strip()
        if secret:
            headers["X-MO-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            with pinned_client(timeout=20.0, transport=transport) as http:
                resp = http.post(url, content=body, headers=headers)
        except httpx.TimeoutException:
            return MoResult(ResultState.TIMEOUT, "The deploy hook did not answer within 20s; the trigger may or may not have landed.")
        except httpx.HTTPError as exc:
            return MoResult(ResultState.DEPLOYMENT_FAILED, f"The deploy hook is unreachable: {type(exc).__name__}.")
        if 200 <= resp.status_code < 300:
            return MoResult(ResultState.PARTIAL,
                            f"The host accepted the deploy trigger (HTTP {resp.status_code}). MO does not track the host's "
                            "build, so completion is unconfirmed.", data={"triggered": True, "http_status": resp.status_code})
        return MoResult(ResultState.DEPLOYMENT_FAILED, f"The deploy hook answered HTTP {resp.status_code}; nothing was deployed.")


ADAPTERS: dict[str, type[DeployAdapter]] = {a.name: a for a in (ExportBundleAdapter, DeployHookAdapter)}


def selected_adapter() -> Optional[DeployAdapter]:
    name = os.getenv("MO_DEPLOY_ADAPTER", "").strip()
    return ADAPTERS[name]() if name in ADAPTERS else None


def adapter_status() -> dict[str, Any]:
    chosen = os.getenv("MO_DEPLOY_ADAPTER", "").strip()
    return {"adapters_implemented": sorted(ADAPTERS), "active": chosen if chosen in ADAPTERS else None,
            "misconfigured": bool(chosen) and chosen not in ADAPTERS,
            "note": "Deploys are approval-gated. With no adapter selected (MO_DEPLOY_ADAPTER) nothing is deployed and the "
                    "step reports CREDENTIAL_REQUIRED. Adapters never report SUCCESS for a deploy they cannot confirm."}
