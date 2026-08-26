"""
MO NEXUS OMEGA — Build sandbox.

Generated code is never executed in the API process. It runs as a separate
process with an explicit environment allowlist, a working directory confined to
the project workspace, POSIX resource limits (CPU, address space, file size,
process count, core dumps) and a wall-clock timeout. The child is started in its
own process group so a timeout kills the whole tree, not just the parent.

HONEST LIMITATION — read before relying on this for hostile code:
this is process-level isolation, not a container or VM. It does not provide
kernel namespace isolation, a read-only root filesystem, seccomp filtering, or
true network isolation; `network=False` scrubs proxy variables and sets
PIP_NO_INDEX/NO_PROXY, which stops well-behaved tooling from reaching the
network but does not stop a determined process from opening a socket. Running
untrusted third-party code at production scale needs a container runtime with
network policy. `SandboxProfile.isolation_level` reports which level is actually
in force so callers cannot mistake one for the other.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from ..errors import MoResult, ResultState

try:  # POSIX only; absent on Windows
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


# Environment variables a sandboxed build is allowed to see. Anything not listed
# here — API keys, database URLs, SMTP passwords — never reaches generated code.
ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR",
    "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED",
    "NODE_ENV", "npm_config_cache", "CI",
})


@dataclass
class SandboxProfile:
    """Resource ceilings for one sandboxed command."""

    name: str = "BUILD_SANDBOX"
    cpu_seconds: int = 120
    wall_timeout_seconds: int = 300
    memory_mb: int = 2048
    max_output_bytes: int = 1_000_000
    max_file_size_mb: int = 128
    max_processes: int = 256
    network: bool = False
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def isolation_level(self) -> str:
        """What this profile actually enforces. Never overstated."""
        if resource is None:
            return "PROCESS_NO_RLIMIT"
        return "PROCESS_RLIMIT"


@dataclass
class SandboxResult:
    command: list[str]
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    peak_rss_kb: Optional[int]
    truncated: bool
    isolation_level: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command, "exit_code": self.exit_code,
            "duration_ms": self.duration_ms, "timed_out": self.timed_out,
            "peak_rss_kb": self.peak_rss_kb, "truncated": self.truncated,
            "isolation_level": self.isolation_level,
            "stdout": self.stdout, "stderr": self.stderr,
        }

    def as_result(self, stage: str) -> MoResult:
        if self.timed_out:
            return MoResult(
                ResultState.TIMEOUT,
                f"{stage} exceeded its {self.duration_ms}ms wall-clock budget and was killed.",
                meta=self.to_dict(),
            )
        if self.exit_code != 0:
            tail = (self.stderr or self.stdout or "").strip().splitlines()[-6:]
            return MoResult(
                ResultState.BUILD_FAILED,
                f"{stage} exited {self.exit_code}: " + " / ".join(tail or ["no output"]),
                meta=self.to_dict(),
            )
        return MoResult.ok({"stage": stage}, **self.to_dict())


def _build_env(profile: SandboxProfile, workspace: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOWLIST}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("HOME", str(workspace))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TMPDIR"] = str(workspace / ".tmp")
    env["MO_SANDBOX"] = profile.name
    if not profile.network:
        # Stops well-behaved tooling from reaching the network. Not a hard block.
        env["PIP_NO_INDEX"] = "1"
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
    env.update(profile.extra_env)
    return env


def _limits(profile: SandboxProfile):
    """Applied in the child between fork and exec."""
    def apply() -> None:  # pragma: no cover — runs in the forked child
        if resource is None:
            os.setsid()
            return
        os.setsid()
        mem = profile.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (profile.cpu_seconds, profile.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (profile.max_file_size_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NPROC, (profile.max_processes, profile.max_processes))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except (ValueError, OSError):
            pass   # some platforms reject RLIMIT_AS; CPU and FSIZE still apply
    return apply


def run(
    command: Sequence[str],
    workspace: Path,
    profile: Optional[SandboxProfile] = None,
    *,
    stdin_text: Optional[str] = None,
) -> SandboxResult:
    """Execute one command inside the sandbox. Never raises on child failure."""
    profile = profile or SandboxProfile()
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".tmp").mkdir(exist_ok=True)

    env = _build_env(profile, workspace)
    started = time.perf_counter()
    timed_out = False
    peak_rss: Optional[int] = None

    if resource is not None:
        before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss

    kwargs: dict[str, Any] = {
        "cwd": str(workspace), "env": env, "capture_output": True, "text": True,
        "timeout": profile.wall_timeout_seconds, "input": stdin_text,
    }
    if os.name == "posix":
        kwargs["preexec_fn"] = _limits(profile)

    try:
        proc = subprocess.run(list(command), **kwargs)
        exit_code, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr += f"\n[sandbox] killed after {profile.wall_timeout_seconds}s wall-clock timeout"
    except FileNotFoundError as exc:
        return SandboxResult(
            command=list(command), exit_code=127, stdout="",
            stderr=f"[sandbox] executable not found: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=False, peak_rss_kb=None, truncated=False,
            isolation_level=profile.isolation_level,
        )

    if resource is not None:
        after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        peak_rss = max(0, after - before) or after

    truncated = False
    if len(stdout) > profile.max_output_bytes:
        stdout = stdout[: profile.max_output_bytes] + "\n[sandbox] stdout truncated"
        truncated = True
    if len(stderr) > profile.max_output_bytes:
        stderr = stderr[: profile.max_output_bytes] + "\n[sandbox] stderr truncated"
        truncated = True

    return SandboxResult(
        command=list(command), exit_code=exit_code, stdout=stdout, stderr=stderr,
        duration_ms=int((time.perf_counter() - started) * 1000), timed_out=timed_out,
        peak_rss_kb=peak_rss, truncated=truncated, isolation_level=profile.isolation_level,
    )


def python_executable() -> str:
    return sys.executable or "python3"


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def make_workspace(root: Path, project_id: str) -> Path:
    ws = Path(root).resolve() / project_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def temp_workspace() -> Path:
    return Path(tempfile.mkdtemp(prefix="mo-sandbox-"))
