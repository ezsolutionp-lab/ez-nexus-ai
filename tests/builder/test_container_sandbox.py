"""Container sandbox mode: hardened argv, fail-closed when unavailable, timeouts remove the container."""

import subprocess

import pytest

from app.mo.sandbox import runner

pytestmark = pytest.mark.builder


@pytest.fixture
def container_on(monkeypatch):
    monkeypatch.setenv("MO_SANDBOX_MODE", "container")
    monkeypatch.delenv("MO_SANDBOX_IMAGE", raising=False)


class FakeDocker:
    def __init__(self, info_ok=True, result=(0, "hello\n", ""), timeout=False):
        self.calls, self.info_ok, self.result, self.timeout = [], info_ok, result, timeout

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if argv[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(argv, 0 if self.info_ok else 1, b"27.0", b"")
        if argv[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout", 1), output=b"partial")
        code, out, err = self.result
        return subprocess.CompletedProcess(argv, code, out, err)


@pytest.fixture
def fake(monkeypatch, container_on):
    f = FakeDocker()
    monkeypatch.setattr(runner.subprocess, "run", f)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    return f


def _run_argv(fake):
    return next(c[0] for c in fake.calls if c[0][:2] == ["docker", "run"])


def test_container_run_is_hardened(fake, tmp_path):
    res = runner.run(["python", "-c", "print('hi')"], tmp_path, runner.SandboxProfile(memory_mb=512, max_processes=64))
    argv = _run_argv(fake)
    assert res.ok and res.isolation_level == "CONTAINER" and res.stdout == "hello\n"
    for flag in ("--rm", "--read-only", "--cap-drop", "ALL", "no-new-privileges", "--network", "none", "65534:65534"):
        assert flag in argv, flag
    assert argv[argv.index("--memory") + 1] == "512m" and argv[argv.index("--pids-limit") + 1] == "64"
    assert f"{tmp_path.resolve()}:/workspace:rw" in argv
    assert argv[-3:] == ["python", "-c", "print('hi')"] and "python:3.11-slim" in argv
    assert "--privileged" not in argv and not any(a.startswith("--volume=/") for a in argv)


def test_network_is_only_opened_when_the_profile_asks(fake, tmp_path):
    runner.run(["true"], tmp_path, runner.SandboxProfile(network=True))
    assert "--network" not in _run_argv(fake)


def test_image_and_extra_env_are_honoured(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("MO_SANDBOX_IMAGE", "registry.example/mo-build:1")
    runner.run(["true"], tmp_path, runner.SandboxProfile(extra_env={"CI": "1"}))
    argv = _run_argv(fake)
    assert "registry.example/mo-build:1" in argv and "CI=1" in argv


def test_host_environment_never_reaches_the_container(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "top-secret-host-value")
    runner.run(["true"], tmp_path)
    assert "top-secret-host-value" not in " ".join(_run_argv(fake))


def test_unavailable_runtime_fails_closed_without_falling_back(monkeypatch, container_on, tmp_path):
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    ran = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: ran.append(a))
    res = runner.run(["python", "-c", "print(1)"], tmp_path)
    assert res.exit_code == 126 and res.isolation_level == "UNAVAILABLE" and "refusing to fall back" in res.stderr
    assert ran == [] and not res.ok


def test_daemon_down_fails_closed(monkeypatch, container_on, tmp_path):
    f = FakeDocker(info_ok=False)
    monkeypatch.setattr(runner.subprocess, "run", f)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/docker")
    res = runner.run(["true"], tmp_path)
    assert res.exit_code == 126 and not any(c[0][:2] == ["docker", "run"] for c in f.calls)


def test_timeout_removes_the_container_and_reports_it(monkeypatch, container_on, tmp_path):
    f = FakeDocker(timeout=True)
    monkeypatch.setattr(runner.subprocess, "run", f)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/docker")
    res = runner.run(["sleep", "999"], tmp_path, runner.SandboxProfile(wall_timeout_seconds=1))
    assert res.timed_out and res.exit_code is None
    name = _run_argv(f)[_run_argv(f).index("--name") + 1]
    assert ["docker", "rm", "-f", name] in [c[0] for c in f.calls]
    assert res.as_result("test").state.value == "TIMEOUT"


def test_output_is_truncated(monkeypatch, container_on, tmp_path):
    f = FakeDocker(result=(0, "x" * 5000, ""))
    monkeypatch.setattr(runner.subprocess, "run", f)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/docker")
    res = runner.run(["true"], tmp_path, runner.SandboxProfile(max_output_bytes=100))
    assert res.truncated and "truncated" in res.stdout


def test_default_mode_is_unchanged_process_isolation(monkeypatch, tmp_path):
    monkeypatch.delenv("MO_SANDBOX_MODE", raising=False)
    res = runner.run(["python3", "-c", "print('ok')"], tmp_path)
    assert res.ok and res.isolation_level.startswith("PROCESS") and res.stdout.strip() == "ok"


@pytest.mark.skipif(not runner.container_available(), reason="no container daemon in this environment")
def test_live_container_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("MO_SANDBOX_MODE", "container")
    res = runner.run(["python", "-c", "import socket,sys\ntry:\n socket.create_connection(('1.1.1.1',53),2)\nexcept OSError:\n print('offline')"],
                     tmp_path, runner.SandboxProfile(wall_timeout_seconds=60))
    assert res.isolation_level == "CONTAINER" and "offline" in res.stdout
