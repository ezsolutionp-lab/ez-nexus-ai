"""
MO NEXUS OMEGA — Build/test pipeline.

Materialises generated files into the project workspace, then runs the real
toolchain inside BUILD_SANDBOX: syntax compile, static analysis, generated
tests. Each stage's actual exit code decides the result. A stage that cannot
run because its tool is absent is reported as SKIPPED with the reason — it is
never counted as a pass.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..errors import MoResult, ResultState
from ..sandbox import runner
from .codegen.fastapi_react import GeneratedFile


@dataclass
class StageOutcome:
    name: str
    state: str
    detail: str
    exit_code: Optional[int] = None
    duration_ms: int = 0
    stdout_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "state": self.state, "detail": self.detail,
            "exit_code": self.exit_code, "duration_ms": self.duration_ms,
            "stdout_tail": self.stdout_tail,
        }


def materialise(files: list[GeneratedFile], workspace: Path) -> dict[str, Any]:
    """Write generated files to disk. Returns a manifest with a tree hash."""
    workspace = Path(workspace)
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    written: list[str] = []
    for f in sorted(files, key=lambda x: x.path):
        target = workspace / f.path
        if not str(target.resolve()).startswith(str(workspace.resolve())):
            raise ValueError(f"Refusing to write outside the workspace: {f.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
        written.append(f.path)

    # Python packages need __init__.py to be importable.
    for directory in {(workspace / p).parent for p in written if p.endswith(".py")}:
        init = directory / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")

    tree_material = "".join(f"{f.path}:{f.sha256}" for f in sorted(files, key=lambda x: x.path))
    return {
        "workspace": str(workspace),
        "file_count": len(written),
        "files": written,
        "tree_sha256": hashlib.sha256(tree_material.encode()).hexdigest(),
    }


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def run_build(workspace: Path, *, profile: Optional[runner.SandboxProfile] = None) -> tuple[ResultState, list[StageOutcome], dict[str, Any]]:
    """
    Run the build stages in the sandbox. Returns (overall_state, stages, metrics).

    Stages: compile → static analysis → generated tests.
    """
    workspace = Path(workspace)
    # A build-time SECRET_KEY: the generated app refuses to import without one,
    # and that refusal is itself a generated test. This value is ephemeral, exists
    # only for the duration of the sandboxed build, and never reaches an artifact.
    profile = profile or runner.SandboxProfile(
        name="BUILD_SANDBOX",
        wall_timeout_seconds=180,
        extra_env={"SECRET_KEY": secrets.token_urlsafe(32), "DATABASE_URL": "sqlite:///./build.db"},
    )
    py = runner.python_executable()
    stages: list[StageOutcome] = []
    total_ms = 0
    peak_rss = 0

    # 1. Compile every generated Python file — proves the output is real code.
    compile_res = runner.run(
        [py, "-m", "compileall", "-q", "."], workspace, profile,
    )
    total_ms += compile_res.duration_ms
    peak_rss = max(peak_rss, compile_res.peak_rss_kb or 0)
    stages.append(StageOutcome(
        "compile",
        "PASSED" if compile_res.ok else "FAILED",
        "All generated Python compiles." if compile_res.ok
        else f"compileall exited {compile_res.exit_code}.",
        compile_res.exit_code, compile_res.duration_ms, _tail(compile_res.stderr or compile_res.stdout),
    ))
    if not compile_res.ok:
        return ResultState.BUILD_FAILED, stages, {"duration_ms": total_ms, "peak_rss_kb": peak_rss}

    # 2. Static analysis — AST-level checks for the security requirements the
    #    spec declares (no string-formatted SQL, no hardcoded secrets).
    analysis_script = workspace / "_mo_static_analysis.py"
    analysis_script.write_text(_STATIC_ANALYSIS_SOURCE, encoding="utf-8")
    analysis_res = runner.run([py, "_mo_static_analysis.py"], workspace, profile)
    total_ms += analysis_res.duration_ms
    peak_rss = max(peak_rss, analysis_res.peak_rss_kb or 0)
    stages.append(StageOutcome(
        "static_analysis",
        "PASSED" if analysis_res.ok else "FAILED",
        _tail(analysis_res.stdout, 4) or "No findings.",
        analysis_res.exit_code, analysis_res.duration_ms, _tail(analysis_res.stdout),
    ))
    if not analysis_res.ok:
        return ResultState.SECURITY_FAILED, stages, {"duration_ms": total_ms, "peak_rss_kb": peak_rss}

    # 3. Generated tests — run only if the generator produced any.
    tests_dir = workspace / "tests"
    if not tests_dir.exists() or not any(tests_dir.glob("test_*.py")):
        stages.append(StageOutcome("tests", "SKIPPED",
                                   "No generated tests were produced for this project."))
        return ResultState.PARTIAL, stages, {"duration_ms": total_ms, "peak_rss_kb": peak_rss}

    test_res = runner.run([py, "-m", "pytest", "tests", "-q", "--no-header"], workspace, profile)
    total_ms += test_res.duration_ms
    peak_rss = max(peak_rss, test_res.peak_rss_kb or 0)
    passed = test_res.ok
    stages.append(StageOutcome(
        "tests", "PASSED" if passed else "FAILED",
        _tail(test_res.stdout, 3) or "pytest produced no summary.",
        test_res.exit_code, test_res.duration_ms, _tail(test_res.stdout),
    ))
    metrics = {"duration_ms": total_ms, "peak_rss_kb": peak_rss}
    return (ResultState.SUCCESS if passed else ResultState.TEST_FAILED), stages, metrics


_STATIC_ANALYSIS_SOURCE = '''\
"""MO static analysis — runs inside BUILD_SANDBOX against generated source.

Checks the security requirements the ProjectSpec declares:
  sec.parameterised_sql      no string-built SQL
  sec.no_hardcoded_secrets   no credential literals
Exits non-zero on any finding, which fails the build with SECURITY_FAILED.
"""
import ast, pathlib, re, sys

SECRET_PATTERNS = [
    re.compile(r"""(?i)(api[_-]?key|secret|password|token)\\s*=\\s*['"][^'"]{8,}['"]"""),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
findings = []

for path in pathlib.Path(".").rglob("*.py"):
    if path.name == "_mo_static_analysis.py":
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"{path}: possible hardcoded secret: {match.group()[:40]}")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        findings.append(f"{path}: does not parse: {exc}")
        continue
    for node in ast.walk(tree):
        # execute("... " + var) or execute(f"...")
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("execute", "executescript"):
            for arg in node.args:
                if isinstance(arg, ast.JoinedStr):
                    findings.append(f"{path}:{node.lineno}: f-string passed to execute() - use bound parameters")
                if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
                    findings.append(f"{path}:{node.lineno}: concatenated SQL passed to execute()")

if findings:
    print("STATIC ANALYSIS FAILED")
    for f in findings:
        print("  " + f)
    sys.exit(1)
print("STATIC ANALYSIS PASSED: no hardcoded secrets, no string-built SQL")
'''
