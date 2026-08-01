from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_worker_script():
    path = REPO_ROOT / "scripts" / "run_maitu_workbench_worker.py"
    spec = importlib.util.spec_from_file_location("assetgraph_maitu_workbench_worker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daemon_continues_after_a_failed_draft_subprocess_cycle(monkeypatch) -> None:
    worker = _load_worker_script()
    calls = 0

    class StopDaemon(RuntimeError):
        pass

    def run_cycle(*, download_missing: bool) -> int:
        nonlocal calls
        assert download_missing is False
        calls += 1
        if calls == 1:
            return 1
        raise StopDaemon

    monkeypatch.setattr(worker, "run_cycle", run_cycle)
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(sys, "argv", [str(worker.REPO_ROOT / "scripts/run_maitu_workbench_worker.py")])

    with pytest.raises(StopDaemon):
        worker.main()

    assert calls == 2


def test_worker_subprocesses_never_receive_backend_only_secrets(monkeypatch) -> None:
    worker = _load_worker_script()
    calls: list[dict[str, str]] = []
    for key in worker.BACKEND_ONLY_SECRET_KEYS:
        monkeypatch.setenv(key, f"sensitive-{key}")

    def run(_command, *, cwd, env, check):
        assert cwd == worker.WORKER_ROOT
        assert check is False
        calls.append(env)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", run)

    assert worker.run_cycle() == 0
    assert len(calls) == 3
    assert all(
        key not in environment
        for environment in calls
        for key in worker.BACKEND_ONLY_SECRET_KEYS
    )
    assert os.environ["DEEPSEEK_API_KEY"].startswith("sensitive-")
