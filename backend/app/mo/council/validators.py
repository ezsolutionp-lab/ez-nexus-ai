"""
MO NEXUS OMEGA — Validation council.

Independent checks on a piece of finished work. Which validators are mandatory depends on the
risk of what was done; a mandatory validator that cannot run FAILS (it does not quietly skip),
so missing evidence never counts as a pass.

  facts     claims are supported by supplied evidence (lexical grounding; see truth.verifier)
  code      Python source parses; with supplied tests they run under pytest in the build sandbox
            (process-level isolation unless MO_SANDBOX_MODE=container)
  security  no secret / PII in the output and no prompt-injection markers
  quality   the caller's acceptance criteria hold
  receipt   claimed work matches runtime receipts (exist, same tenant, succeeded, hash matches)
"""

from __future__ import annotations

import ast
import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..authority.policy import Risk
from ..context import RequestContext
from ..db import ExecutionReceipt
from ..evaluation.harness import _MISSING, _dig
from ..guards import injection, pii
from ..truth import verify_claims

VALIDATORS = ("facts", "code", "security", "quality", "receipt")
MANDATORY: dict[Risk, frozenset[str]] = {
    Risk.NONE: frozenset({"quality"}),
    Risk.READ: frozenset({"quality", "security"}),
    Risk.WRITE: frozenset({"quality", "security", "receipt"}),
    Risk.EXTERNAL: frozenset({"quality", "security", "receipt", "facts"}),
    Risk.SENSITIVE: frozenset(VALIDATORS),
}
MAX_CRITERIA = 100
MAX_RECEIPTS = 100


def _pass(name: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"validator": name, "status": "PASS", "detail": detail, **extra}


def _fail(name: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"validator": name, "status": "FAIL", "detail": detail, **extra}


def _skip(name: str, detail: str) -> dict[str, Any]:
    return {"validator": name, "status": "SKIPPED", "detail": detail}


def _text(output: Any) -> str:
    return output if isinstance(output, str) else json.dumps(output, sort_keys=True, default=str)


def check_quality(output: Any, acceptance: Optional[list]) -> dict[str, Any]:
    if not acceptance:
        return _skip("quality", "No acceptance criteria were supplied.")
    if not isinstance(acceptance, list) or len(acceptance) > MAX_CRITERIA:
        return _fail("quality", f"acceptance must be a list of at most {MAX_CRITERIA} criteria.")
    text, failed = _text(output), []
    for i, c in enumerate(acceptance):
        kind = c.get("type") if isinstance(c, dict) else None
        ok = None
        if kind == "contains":
            ok = str(c.get("value", "")) in text
        elif kind == "not_contains":
            ok = str(c.get("value", "")) not in text
        elif kind == "min_length":
            ok = isinstance(c.get("value"), int) and len(text) >= c["value"]
        elif kind in ("path_equals", "path_present") and isinstance(c.get("path"), str):
            got = _dig(output, c["path"]) if isinstance(output, (dict, list)) else _MISSING
            ok = got is not _MISSING and (kind == "path_present" or got == c.get("value"))
        if ok is None:
            failed.append(f"criterion {i} is malformed or of unknown type")
        elif not ok:
            failed.append(f"criterion {i} ({kind}) not met")
    return _fail("quality", "; ".join(failed), failed=len(failed)) if failed else \
        _pass("quality", f"{len(acceptance)} criteria met.")


def check_security(output: Any) -> dict[str, Any]:
    text = _text(output)
    findings = pii.scan(text)
    verdict = injection.screen(text)
    problems = []
    if findings:
        problems.append(f"{len(findings)} secret/PII finding(s), max severity {pii.max_severity(findings)}")
    if verdict.verdict != "ALLOW":
        problems.append(f"injection screen {verdict.verdict} ({', '.join(verdict.signals)})")
    return _fail("security", "; ".join(problems), findings=[f.kind for f in findings]) if problems else \
        _pass("security", "No secret, PII or injection markers found.")


def check_code(code: Optional[str], tests: Optional[str] = None) -> dict[str, Any]:
    """Syntax check; with `tests`, also run them with pytest in the build sandbox and report its isolation level."""
    if code is None:
        return _skip("code", "No code was supplied.")
    try:
        ast.parse(code)
        if tests is not None:
            ast.parse(tests)
    except SyntaxError as exc:
        return _fail("code", f"Syntax error at line {exc.lineno}: {exc.msg}")
    if tests is None:
        return _pass("code", "Parses as Python. Syntax only: no tests were supplied to run.")
    from ..sandbox import runner
    ws = runner.temp_workspace()
    try:
        (ws / "candidate.py").write_text(code)
        (ws / "test_candidate.py").write_text(tests)
        res = runner.run([runner.python_executable() if not runner.container_mode() else "python", "-m", "pytest", "-q",
                          "-p", "no:cacheprovider", "test_candidate.py"], ws,
                         runner.SandboxProfile(name="COUNCIL_TESTS", wall_timeout_seconds=60, cpu_seconds=30, memory_mb=512))
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)
    tail = " / ".join((res.stdout or res.stderr).strip().splitlines()[-3:])
    if res.timed_out:
        return _fail("code", "Tests timed out.", isolation=res.isolation_level)
    if not res.ok:
        return _fail("code", f"Tests failed (exit {res.exit_code}): {tail}", isolation=res.isolation_level)
    return _pass("code", f"Tests passed in a sandbox ({res.isolation_level}): {tail}", isolation=res.isolation_level)


def check_facts(answer: Optional[str], evidence: Optional[list]) -> dict[str, Any]:
    if answer is None:
        return _skip("facts", "No answer text was supplied.")
    if not evidence:
        return _fail("facts", "An answer was supplied without evidence to check it against.")
    try:
        r = verify_claims(answer, evidence)
    except ValueError as exc:
        return _fail("facts", f"Invalid input: {exc}")
    if r["abstain"]:
        return _fail("facts", "; ".join(r["reasons"]) or "Not sufficiently grounded.", groundedness=r["groundedness"])
    return _pass("facts", f"Groundedness {r['groundedness']:.0%}.", groundedness=r["groundedness"])


def check_receipts(db: Session, ctx: RequestContext, claimed: Optional[list]) -> dict[str, Any]:
    if not claimed:
        return _skip("receipt", "No receipts were claimed for this work.")
    if not isinstance(claimed, list) or len(claimed) > MAX_RECEIPTS:
        return _fail("receipt", f"claimed_receipts must be a list of at most {MAX_RECEIPTS}.")
    problems = []
    for c in claimed:
        rid = c.get("receipt_id") if isinstance(c, dict) else c
        row = db.get(ExecutionReceipt, rid) if isinstance(rid, str) else None
        if row is None or row.tenant_id != ctx.tenant_id:
            problems.append(f"receipt '{rid}' does not exist")
        elif not row.success:
            problems.append(f"receipt '{rid}' records a {row.state} outcome, not success")
        elif isinstance(c, dict) and c.get("output_hash") and c["output_hash"] != row.output_hash:
            problems.append(f"receipt '{rid}' output hash does not match the claim")
    return _fail("receipt", "; ".join(problems)) if problems else \
        _pass("receipt", f"{len(claimed)} receipt(s) match runtime records.")


def run_council(db: Session, ctx: RequestContext, *, risk: Risk = Risk.NONE, output: Any = None,
                acceptance: Optional[list] = None, answer: Optional[str] = None, evidence: Optional[list] = None,
                code: Optional[str] = None, tests: Optional[str] = None,
                claimed_receipts: Optional[list] = None) -> dict[str, Any]:
    ran = {
        "quality": check_quality(output, acceptance),
        "security": check_security(output),
        "code": check_code(code, tests),
        "facts": check_facts(answer, evidence),
        "receipt": check_receipts(db, ctx, claimed_receipts),
    }
    mandatory = set(MANDATORY[risk])
    # facts / code are conditional: they are required only when there is an answer or code to check.
    if answer is None:
        mandatory.discard("facts")
    if code is None:
        mandatory.discard("code")
    results = []
    for name in VALIDATORS:
        r = dict(ran[name])
        r["mandatory"] = name in mandatory
        if r["mandatory"] and r["status"] == "SKIPPED":
            r["status"], r["detail"] = "FAIL", "Mandatory validator could not run: " + r["detail"]
        results.append(r)
    # Any FAIL fails the council, and a mandatory validator must PASS (a skip was already turned into a FAIL).
    failed = sorted(r["validator"] for r in results if r["status"] == "FAIL" or (r["mandatory"] and r["status"] != "PASS"))
    return {"passed": not failed, "risk": risk.value, "mandatory": sorted(mandatory), "failed": failed,
            "results": results}
