"""
MO NEXUS OMEGA — Dependency provenance registry and SBOM ingestion.

Every third-party dependency is recorded with its version, source and licence. A recognised
permissive licence is approved automatically (attribution still required); unknown, copyleft
and proprietary licences are QUARANTINED until an administrator reviews them. `gate()` is what
a release scan uses: it fails while any listed dependency is not APPROVED.

The licence for `resolve_installed` comes from the package's own installed metadata; a
requirements line alone carries no licence, so an unresolved one stays UNKNOWN and quarantined.
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib import metadata as importlib_metadata
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..audit import chain
from ..context import RequestContext
from ..db import DependencyRecord
from ..errors import MoResult, ResultState
from .licenses import classify, initial_status

MAX_DEPENDENCIES = 5_000
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)\s*(?:\[[^\]]*\])?\s*(?:==|===|~=|>=|<=|>|<)?\s*([A-Za-z0-9.*+!_\-]*)")


def _resolve_license(name: str) -> tuple[Optional[str], Optional[str]]:
    try:
        md = importlib_metadata.metadata(name)
    except importlib_metadata.PackageNotFoundError:
        return None, None
    lic = (md.get("License-Expression") or "").strip()
    if not lic:
        classifiers = [c.split("::")[-1].strip() for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
        lic = classifiers[0] if classifiers else (md.get("License") or "").strip()
    if len(lic) > 200 or "\n" in lic:                    # a full licence text pasted into the field
        lic = ""
    return lic or None, md.get("Version")


def parse_requirements(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = _REQ.match(line)
        if m:
            out.append((m.group(1).lower().replace("_", "-"), m.group(2) or "unspecified"))
    return out


def parse_cyclonedx(doc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in doc.get("components", []) if isinstance(doc, dict) else []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        lics = []
        for l in c.get("licenses", []) or []:
            if isinstance(l, dict):
                lics.append((l.get("license") or {}).get("id") or (l.get("license") or {}).get("name") or l.get("expression"))
        out.append({"name": str(c["name"]), "version": str(c.get("version", "unspecified")),
                    "license": next((x for x in lics if x), None), "source": c.get("purl")})
    return out


def register(db: Session, ctx: RequestContext, *, name: str, version: str, source: Optional[str] = None,
             license: Optional[str] = None, usage: str = "", license_text: Optional[str] = None) -> DependencyRecord:
    lclass = classify(license)
    row = (db.query(DependencyRecord).filter(DependencyRecord.tenant_id == ctx.tenant_id, DependencyRecord.name == name,
                                             DependencyRecord.version == version).first())
    if row is None:
        row = DependencyRecord(tenant_id=ctx.tenant_id, created_by=ctx.actor_id, name=name, version=version,
                               status=initial_status(lclass))
        db.add(row)
    elif row.status == "APPROVED" and (license or None) != row.license:
        row.status = initial_status(lclass)                # the licence changed under an approval: re-review
        row.review_notes = "Licence changed after approval; re-review required."
    row.source, row.license, row.license_class = source or row.source, license or row.license, lclass
    row.usage = usage or row.usage
    row.attribution_required = True
    if license_text:
        row.license_text_hash = hashlib.sha256(license_text.encode()).hexdigest()
    db.flush()
    return row


def ingest_sbom(db: Session, ctx: RequestContext, *, requirements: Optional[str] = None,
                cyclonedx: Optional[dict] = None, resolve_installed: bool = False) -> MoResult:
    if (requirements is None) == (cyclonedx is None):
        return MoResult(ResultState.FAILED, "Provide exactly one of 'requirements' or 'cyclonedx'.")
    items: list[dict[str, Any]] = []
    if requirements is not None:
        for name, version in parse_requirements(requirements):
            item = {"name": name, "version": version, "license": None, "source": "requirements"}
            if resolve_installed:
                lic, installed = _resolve_license(name)
                item["license"] = lic
                if version == "unspecified" and installed:
                    item["version"] = installed
            items.append(item)
    else:
        items = parse_cyclonedx(cyclonedx)
    if not items:
        return MoResult(ResultState.FAILED, "No dependencies were found in that input.")
    if len(items) > MAX_DEPENDENCIES:
        return MoResult(ResultState.FAILED, f"At most {MAX_DEPENDENCIES} dependencies can be ingested at once.")
    rows = [register(db, ctx, name=i["name"], version=i["version"], license=i["license"], source=i["source"])
            for i in items]
    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    sbom_hash = hashlib.sha256(json.dumps(sorted((r.name, r.version, r.license or "") for r in rows)).encode()).hexdigest()
    chain.record(db, ctx, action="compliance.sbom_ingested", result_state=ResultState.SUCCESS,
                 resource_type="sbom", resource_id=sbom_hash[:16], detail=f"{len(rows)} dependencies")
    quarantined = sorted(f"{r.name}=={r.version}" for r in rows if r.status == "QUARANTINED")
    return MoResult.ok({"count": len(rows), "by_status": status_counts, "quarantined": quarantined[:200],
                        "sbom_hash": sbom_hash})


def review(db: Session, ctx: RequestContext, dependency_id: str, *, approve: bool, notes: str = "") -> MoResult:
    if not ctx.is_admin:
        return MoResult(ResultState.POLICY_DENIED, "Only an administrator can review a dependency.")
    row = db.get(DependencyRecord, dependency_id)
    if row is None or row.tenant_id != ctx.tenant_id:
        return MoResult(ResultState.FAILED, f"No such dependency '{dependency_id}'.")
    if approve and row.license_class == "UNKNOWN" and not notes.strip():
        return MoResult(ResultState.FAILED, "Approving a dependency with an unknown licence needs review notes.")
    if approve and row.license_class in ("STRONG_COPYLEFT", "PROPRIETARY") and not ctx.mfa_verified:
        return MoResult(ResultState.POLICY_DENIED, "Approving a copyleft or proprietary dependency needs an MFA session.")
    row.status, row.review_notes, row.reviewed_by = ("APPROVED" if approve else "REJECTED"), notes, ctx.actor_id
    db.flush()
    chain.record(db, ctx, action="compliance.dependency_reviewed", result_state=ResultState.SUCCESS,
                 resource_type="dependency", resource_id=row.id, detail=f"{row.name}=={row.version}: {row.status}")
    return MoResult.ok(dependency_dict(row))


def dependency_dict(r: DependencyRecord) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "version": r.version, "source": r.source, "license": r.license,
            "license_class": r.license_class, "status": r.status, "attribution_required": r.attribution_required,
            "review_notes": r.review_notes, "reviewed_by": r.reviewed_by}


def gate(db: Session, ctx: RequestContext) -> dict[str, Any]:
    """Pass only when this tenant has dependencies on record and none are quarantined or rejected."""
    rows = db.query(DependencyRecord).filter(DependencyRecord.tenant_id == ctx.tenant_id).all()
    blocked = sorted(f"{r.name}=={r.version} ({r.status})" for r in rows if r.status != "APPROVED")
    return {"passed": bool(rows) and not blocked, "count": len(rows), "blocked": blocked[:200],
            "reason": "No dependencies are recorded; ingest an SBOM first." if not rows else
                      ("" if not blocked else f"{len(blocked)} dependency(ies) not approved.")}
