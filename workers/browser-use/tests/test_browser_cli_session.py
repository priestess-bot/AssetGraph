from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Sequence

import pytest

import browser_use_worker.browser_cli_session as browser_cli_session_module
from browser_use_worker.browser_cli_session import (
    BrowserUseCliSession,
    BrowserUseCliSessionConfig,
    is_trusted_browser_use_cli_session,
)
from browser_use_worker.maitu_executor import MaituBrowserExecutionError


class ConfigMismatchRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        self.commands.append(tuple(args))
        if "--headed" in args:
            raise MaituBrowserExecutionError("Session 'default' is already running with different config. Run browser-use close first.")
        return "opened existing session"


class FakeRunner:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        self.commands.append(tuple(args))
        if not self.outputs:
            raise AssertionError(f"No fake output left for command: {args}")
        return self.outputs.pop(0)


def test_production_session_trust_gate_rejects_injected_runner_or_rebound_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BrowserUseCliSessionConfig(
        session_name="assetgraph-trust-test",
        cdp_url="http://127.0.0.1:9222",
    )
    trusted = BrowserUseCliSession(config=config)
    assert is_trusted_browser_use_cli_session(trusted) is True

    injected = BrowserUseCliSession(config=config, runner=FakeRunner([]))
    assert is_trusted_browser_use_cli_session(injected) is False

    monkeypatch.setattr(BrowserUseCliSession, "read_page_summary", lambda _self: {})
    assert is_trusted_browser_use_cli_session(trusted) is False


def make_session(outputs: list[str]) -> tuple[BrowserUseCliSession, FakeRunner]:
    runner = FakeRunner(outputs)
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            home_url="https://live2.maituai.com/",
            login_url="https://live2.maituai.com/Login",
            headed=True,
            timeout_seconds=12,
            session_name=None,
            cdp_url=None,
        ),
        runner=runner,
    )
    return session, runner


def test_default_config_uses_environment_browser_use_repository(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_USE_REPO", "/opt/browser-use-pinned")

    config = BrowserUseCliSessionConfig()

    assert config.browser_use_repo == "/opt/browser-use-pinned"


def test_default_config_uses_visible_chrome_cdp_and_named_session(monkeypatch) -> None:
    monkeypatch.delenv("BROWSER_USE_SESSION_NAME", raising=False)
    monkeypatch.delenv("BROWSER_USE_CDP_URL", raising=False)

    config = BrowserUseCliSessionConfig()

    assert config.session_name == "assetgraph-maitu"
    assert config.cdp_url == "http://127.0.0.1:9222"
    assert config.no_proxy_hosts == ("127.0.0.1", "localhost")
    assert config.timeout_seconds == 120.0


def _running_cdp_session(
    *,
    name: str = "assetgraph-maitu-test",
    cdp_url: str = "ws://127.0.0.1:9222/devtools/browser/test",
    config: str = "cdp",
) -> str:
    return json.dumps(
        {
            "sessions": [
                {
                    "name": name,
                    "phase": "running",
                    "pid": 1234,
                    "config": config,
                    "cdp_url": cdp_url,
                }
            ]
        }
    )


def test_named_session_attaches_cdp_with_read_only_state_then_reuses_session() -> None:
    runner = FakeRunner(
        ['{"sessions": []}', "first", _running_cdp_session(), _running_cdp_session(), "second"]
    )
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session._call_browser_use(["state"]) == "first"
    assert session._call_browser_use(["state"]) == "second"

    assert runner.commands == [
        ("uv", "run", "browser-use", "--json", "sessions"),
        (
            "uv",
            "run",
            "browser-use",
            "--session",
            "assetgraph-maitu-test",
            "--cdp-url",
            "http://127.0.0.1:9222",
            "state",
        ),
        ("uv", "run", "browser-use", "--json", "sessions"),
        ("uv", "run", "browser-use", "--json", "sessions"),
        ("uv", "run", "browser-use", "--session", "assetgraph-maitu-test", "state"),
    ]


def test_first_mutating_command_runs_only_after_read_only_attach_and_transport_readback() -> None:
    runner = FakeRunner(['{"sessions": []}', "attached", _running_cdp_session(), "clicked"])
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session._call_browser_use(["click", "42"]) == "clicked"
    assert runner.commands[1][-1] == "state"
    assert "--cdp-url" in runner.commands[1]
    assert runner.commands[2][-2:] == ("--json", "sessions")
    assert runner.commands[3][-2:] == ("click", "42")
    assert "--cdp-url" not in runner.commands[3]


def test_cdp_attached_open_does_not_start_a_second_headed_browser() -> None:
    runner = FakeRunner(['{"sessions": []}', "attached", _running_cdp_session(), "opened"])
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            home_url="https://live2.maituai.com/",
            headed=True,
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    session.open_home()

    assert runner.commands[0] == ("uv", "run", "browser-use", "--json", "sessions")
    assert runner.commands[1][-1] == "state"
    assert runner.commands[2][-2:] == ("--json", "sessions")
    assert "--headed" not in runner.commands[3]
    assert runner.commands[3][-2:] == ("open", "https://live2.maituai.com/")


def test_maitu_api_eval_switches_from_unrelated_active_tab_to_unique_trusted_tab() -> None:
    room_payload = {
        "id": 41172,
        "name": "asser测试",
        "status": "offline",
        "topics": [],
    }
    running = _running_cdp_session(name="assetgraph-maitu-tabs")
    listing = json.dumps(
        {
            "success": True,
            "data": {
                "_raw_text": (
                    "TAB  URL\n"
                    "0    https://easychuan.cn/\n"
                    "1    https://live2.maituai.com.evil.example/LiveRoom\n"
                    "2    https://live2.maituai.com/LiveRoom?liveRoomId=41172"
                )
            },
        }
    )
    runner = FakeRunner(
        [
            '{"sessions": []}',
            "attached",
            running,
            listing,
            running,
            "switched: 2",
            running,
            'result: {"origin":"https://live2.maituai.com","href":"https://live2.maituai.com/LiveRoom?liveRoomId=41172"}',
            running,
            "result: " + json.dumps(room_payload, ensure_ascii=False),
        ]
    )
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-tabs",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session.read_live_room("41172") == room_payload
    assert runner.commands[3][-3:] == ("--json", "tab", "list")
    assert runner.commands[5][-3:] == ("tab", "switch", "2")
    assert runner.commands[7][-2:] == ("eval", BrowserUseCliSession.MAITU_TAB_PROBE_SCRIPT)
    assert "live_rooms/41172" in runner.commands[9][-1]


def test_maitu_api_tab_retries_transient_post_switch_origin_mismatch(monkeypatch) -> None:
    running = _running_cdp_session(name="assetgraph-maitu-tabs")
    listing = json.dumps(
        {
            "success": True,
            "data": {
                "_raw_text": (
                    "TAB  URL\n"
                    "0    https://easychuan.cn/\n"
                    "1    https://live2.maituai.com/LiveRoom?liveRoomId=41172"
                )
            },
        }
    )
    runner = FakeRunner(
        [
            '{"sessions": []}',
            "attached",
            running,
            listing,
            running,
            "switched: 1",
            running,
            'result: {"origin":"https://easychuan.cn","href":"https://easychuan.cn/"}',
            running,
            listing,
            running,
            "switched: 1",
            running,
            'result: {"origin":"https://live2.maituai.com","href":"https://live2.maituai.com/LiveRoom?liveRoomId=41172"}',
        ]
    )
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-tabs",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )
    monkeypatch.setattr("browser_use_worker.browser_cli_session.time.sleep", lambda _seconds: None)

    session._ensure_maitu_api_tab()

    switch_commands = [command for command in runner.commands if command[-3:-1] == ("tab", "switch")]
    probe_commands = [
        command
        for command in runner.commands
        if command[-2:] == ("eval", BrowserUseCliSession.MAITU_TAB_PROBE_SCRIPT)
    ]
    assert len(switch_commands) == 2
    assert len(probe_commands) == 2


def test_maitu_api_eval_fails_closed_when_multiple_trusted_tabs_exist() -> None:
    running = _running_cdp_session(name="assetgraph-maitu-ambiguous-tabs")
    listing = json.dumps(
        {
            "success": True,
            "data": {
                "_raw_text": (
                    "TAB  URL\n"
                    "0    https://live2.maituai.com/MaterialManage\n"
                    "1    https://live2.maituai.com/LiveRoom?liveRoomId=41172"
                )
            },
        }
    )
    runner = FakeRunner(['{"sessions": []}', "attached", running, listing])
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-ambiguous-tabs",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    with pytest.raises(MaituBrowserExecutionError, match="exactly one trusted Maitu tab"):
        session.read_live_room("41172")

    assert not any(command[-3:-1] == ("tab", "switch") for command in runner.commands)
    assert len(runner.commands) == 4


def test_existing_named_session_is_discovered_before_cdp_attach() -> None:
    commands: list[tuple[str, ...]] = []

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        command = tuple(args)
        commands.append(command)
        if command[-1] == "sessions":
            return _running_cdp_session()
        if "--cdp-url" in command:
            raise AssertionError("running named session must be reused without reapplying CDP config")
        return "existing named session"

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session._call_browser_use(["state"]) == "existing named session"
    assert session._call_browser_use(["state"]) == "existing named session"
    assert commands == [
        ("uv", "run", "browser-use", "--json", "sessions"),
        ("uv", "run", "browser-use", "--session", "assetgraph-maitu-test", "state"),
        ("uv", "run", "browser-use", "--json", "sessions"),
        ("uv", "run", "browser-use", "--session", "assetgraph-maitu-test", "state"),
    ]
    assert all("--cdp-url" not in command for command in commands)


def test_reused_named_session_is_revalidated_before_every_business_command() -> None:
    runner = FakeRunner(
        [
            _running_cdp_session(),
            "first",
            _running_cdp_session(
                cdp_url="wss://remote.example/devtools/browser/replaced",
                config="cloud",
            ),
        ]
    )
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session._call_browser_use(["state"]) == "first"
    with pytest.raises(MaituBrowserExecutionError, match="transport"):
        session._call_browser_use(["click", "42"])

    assert runner.commands[-1] == ("uv", "run", "browser-use", "--json", "sessions")
    assert all(command[-2:] != ("click", "42") for command in runner.commands)


def test_production_runner_rejects_disabled_named_transport() -> None:
    with pytest.raises(ValueError, match="production runner requires"):
        BrowserUseCliSession(BrowserUseCliSessionConfig(session_name=None, cdp_url=None))


def test_transport_config_is_immutable_after_validation() -> None:
    config = BrowserUseCliSessionConfig()
    session = BrowserUseCliSession(config, runner=FakeRunner([]))

    with pytest.raises(FrozenInstanceError):
        session.config.cdp_url = None


@pytest.mark.parametrize(
    "config",
    [
        BrowserUseCliSessionConfig(session_name="unsafe session", cdp_url="http://127.0.0.1:9222"),
        BrowserUseCliSessionConfig(session_name="unsafe.session", cdp_url="http://127.0.0.1:9222"),
        BrowserUseCliSessionConfig(session_name="safe-session", cdp_url=None),
        BrowserUseCliSessionConfig(session_name=None, cdp_url="http://127.0.0.1:9222"),
        BrowserUseCliSessionConfig(session_name="safe-session", cdp_url="http://192.0.2.10:9222"),
        BrowserUseCliSessionConfig(session_name="safe-session", cdp_url="http://user@127.0.0.1:9222"),
    ],
)
def test_transport_config_rejects_unsafe_named_session_or_remote_cdp(config) -> None:
    with pytest.raises(ValueError):
        BrowserUseCliSession(config, runner=FakeRunner([]))


@pytest.mark.parametrize(
    "entry",
    [
        {
            "name": "assetgraph-maitu-test",
            "phase": "running",
            "pid": 1234,
            "config": "cloud",
            "cdp_url": "wss://remote.example/devtools/browser/test",
        },
        {
            "name": "assetgraph-maitu-test",
            "phase": "running",
            "pid": 1234,
            "config": "cdp",
        },
        {
            "name": "assetgraph-maitu-test",
            "phase": "running",
            "pid": 1234,
            "config": "cdp",
            "cdp_url": "ws://127.0.0.1:9333/devtools/browser/wrong-port",
        },
    ],
)
def test_existing_named_session_rejects_untrusted_or_unknown_transport(entry) -> None:
    runner = FakeRunner([json.dumps({"sessions": [entry]})])
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    with pytest.raises(MaituBrowserExecutionError, match="transport"):
        session._call_browser_use(["state"])

    assert runner.commands == [("uv", "run", "browser-use", "--json", "sessions")]


def test_config_mismatch_fallback_requires_revalidated_loopback_session() -> None:
    commands: list[tuple[str, ...]] = []

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        command = tuple(args)
        commands.append(command)
        if command[-1] == "sessions":
            if len([item for item in commands if item[-1] == "sessions"]) == 1:
                raise MaituBrowserExecutionError("sessions temporarily unavailable")
            return _running_cdp_session(
                cdp_url="wss://remote.example/devtools/browser/test",
                config="cloud",
            )
        if "--cdp-url" in command:
            raise MaituBrowserExecutionError("Session is already running with different config")
        raise AssertionError("must not fall back to an unvalidated existing session")

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    with pytest.raises(MaituBrowserExecutionError, match="transport"):
        session._call_browser_use(["state"])

    assert len(commands) == 3
    assert commands[0][-2:] == ("--json", "sessions")
    assert "--cdp-url" in commands[1]
    assert commands[2][-2:] == ("--json", "sessions")


def test_config_mismatch_fallback_revalidates_transport_and_lease_before_reuse() -> None:
    commands: list[tuple[str, ...]] = []
    guard_calls = 0

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        command = tuple(args)
        commands.append(command)
        if command[-1] == "sessions":
            if len([item for item in commands if item[-1] == "sessions"]) == 1:
                raise MaituBrowserExecutionError("sessions temporarily unavailable")
            return _running_cdp_session()
        if "--cdp-url" in command:
            raise MaituBrowserExecutionError("Session is already running with different config")
        return "trusted existing session"

    def guard() -> bool:
        nonlocal guard_calls
        guard_calls += 1
        return True

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )
    session.set_execution_guard(guard)

    assert session._call_browser_use(["state"]) == "trusted existing session"
    assert guard_calls == 4
    assert [command[-1] for command in commands] == ["sessions", "state", "sessions", "state"]
    assert "--cdp-url" in commands[1]
    assert "--cdp-url" not in commands[3]


def test_lease_guard_is_rechecked_before_discovery_and_browser_command() -> None:
    runner = FakeRunner(['{"sessions": []}'])
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )
    guard_calls = 0

    def guard() -> bool:
        nonlocal guard_calls
        guard_calls += 1
        return guard_calls == 1

    session.set_execution_guard(guard)

    with pytest.raises(MaituBrowserExecutionError, match="lease"):
        session._call_browser_use(["state"])

    assert guard_calls == 2
    assert runner.commands == [("uv", "run", "browser-use", "--json", "sessions")]


def test_named_session_process_lock_is_acquired_before_first_external_command(monkeypatch) -> None:
    events: list[str] = []

    def acquire(session_name: str, timeout_seconds: float) -> None:
        assert session_name == "assetgraph-maitu-test"
        assert timeout_seconds == pytest.approx(120.0, abs=0.001)
        events.append("lock")

    monkeypatch.setattr(browser_cli_session_module, "_acquire_process_session_lock", acquire, raising=False)

    sessions_calls = 0

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        nonlocal sessions_calls
        events.append("runner")
        if args[-1] == "sessions":
            sessions_calls += 1
            return '{"sessions": []}' if sessions_calls == 1 else _running_cdp_session()
        return "state"

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    session._session_lock_acquired = True
    assert session._call_browser_use(["state"]) == "state"
    assert session._call_browser_use(["state"]) == "state"
    assert events == [
        "lock",
        "runner",
        "runner",
        "runner",
        "lock",
        "runner",
        "runner",
    ]


def test_named_session_process_lock_rejects_a_second_worker_process() -> None:
    session_name = f"assetgraph-lock-test-{os.getpid()}"
    code = (
        "import time; "
        "from browser_use_worker.browser_cli_session import _acquire_process_session_lock; "
        f"_acquire_process_session_lock({session_name!r}, 2.0); "
        "print('locked', flush=True); time.sleep(5)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(MaituBrowserExecutionError, match="owned by another worker"):
            browser_cli_session_module._acquire_process_session_lock(session_name, 0.2)
    finally:
        child.terminate()
        child.wait(timeout=5)

    browser_cli_session_module._acquire_process_session_lock(session_name, 0.5)
    browser_cli_session_module._acquire_process_session_lock(session_name, 0.5)


def test_worker_can_release_current_process_browser_session_locks() -> None:
    session_name = f"assetgraph-release-lock-test-{os.getpid()}"
    browser_cli_session_module._acquire_process_session_lock(session_name, 0.5)

    BrowserUseCliSession.release_current_process_locks()

    assert session_name not in browser_cli_session_module._HELD_SESSION_LOCKS


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork semantics")
def test_fork_child_cannot_reuse_parent_process_lock_ownership() -> None:
    session_name = f"assetgraph-fork-lock-test-{os.getpid()}"
    browser_cli_session_module._acquire_process_session_lock(session_name, 0.5)

    child_pid = os.fork()
    if child_pid == 0:
        try:
            browser_cli_session_module._acquire_process_session_lock(session_name, 0.2)
        except MaituBrowserExecutionError:
            os._exit(0)
        os._exit(1)

    waited_pid, status = os.waitpid(child_pid, 0)
    assert waited_pid == child_pid
    assert os.waitstatus_to_exitcode(status) == 0


def test_config_mismatch_path_shares_one_timeout_budget_across_four_commands(monkeypatch) -> None:
    clock = [0.0]
    timeouts: list[float] = []
    sessions_calls = 0

    monkeypatch.setattr(browser_cli_session_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser_cli_session_module, "_acquire_process_session_lock", lambda *_args: None, raising=False)

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        nonlocal sessions_calls
        timeouts.append(timeout_seconds)
        clock[0] += 1.0
        if args[-1] == "sessions":
            sessions_calls += 1
            if sessions_calls == 1:
                raise MaituBrowserExecutionError("sessions temporarily unavailable")
            return _running_cdp_session()
        if "--cdp-url" in args:
            raise MaituBrowserExecutionError("Session is already running with different config")
        return "state"

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            timeout_seconds=10.0,
            session_name="assetgraph-maitu-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session._call_browser_use(["state"]) == "state"
    assert timeouts == [10.0, 9.0, 8.0, 7.0]


def test_session_lock_wait_and_transport_share_one_timeout_budget(monkeypatch) -> None:
    clock = [0.0]
    lock_timeouts: list[float] = []
    runner_timeouts: list[float] = []

    monkeypatch.setattr(browser_cli_session_module.time, "monotonic", lambda: clock[0])

    def acquire(_session_name: str, timeout_seconds: float) -> None:
        lock_timeouts.append(timeout_seconds)
        clock[0] += 3.0

    monkeypatch.setattr(browser_cli_session_module, "_acquire_process_session_lock", acquire)

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        runner_timeouts.append(timeout_seconds)
        clock[0] += 2.0
        return (
            _running_cdp_session(name="assetgraph-maitu-budget-test")
            if args[-1] == "sessions"
            else "state"
        )

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            timeout_seconds=10.0,
            session_name="assetgraph-maitu-budget-test",
            cdp_url="http://127.0.0.1:9222",
        ),
        runner=runner,
    )

    assert session._call_browser_use(["state"]) == "state"
    assert lock_timeouts == [10.0]
    assert runner_timeouts == [7.0, 5.0]


def test_headed_fallback_reuses_the_original_timeout_deadline(monkeypatch) -> None:
    clock = [0.0]
    timeouts: list[float] = []

    monkeypatch.setattr(browser_cli_session_module.time, "monotonic", lambda: clock[0])

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        timeouts.append(timeout_seconds)
        if len(timeouts) == 1:
            clock[0] += 3.0
            raise MaituBrowserExecutionError("Session is already running with different config")
        return "opened"

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            timeout_seconds=10.0,
            headed=True,
            session_name=None,
            cdp_url=None,
        ),
        runner=runner,
    )

    session.open_url("https://live2.maituai.com/")

    assert timeouts == [10.0, 7.0]


def test_runner_internal_type_error_never_replays_browser_command() -> None:
    calls = 0

    def runner(args: Sequence[str], *, cwd: str | None, timeout_seconds: float) -> str:
        nonlocal calls
        calls += 1
        raise TypeError("runner implementation failed after dispatch")

    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(session_name=None, cdp_url=None),
        runner=runner,
    )

    with pytest.raises(TypeError, match="after dispatch"):
        session._call_browser_use(["state"])

    assert calls == 1


def test_read_current_state_parses_reference_room_from_browser_use_eval() -> None:
    payload = {
        "title": "MyTwins麦兔直播",
        "href": "https://live2.maituai.com/LiveRoom?liveRoomId=39826",
        "text": "返回\n(ID:39826)\n京东空白直播间-0707-1352\n直播间设置\n京东版",
        "scenes": [
            {"text": "场景01\n已激活\n讲品", "active": True},
            {"text": "场景02\n已激活\n讲品", "active": False},
        ],
        "layers": [
            {"text": "前景", "active": False},
            {"text": "品酒大师(PRO）", "active": False},
            {"text": "微信图片_20260618221607_11_15", "active": False},
        ],
        "materialTabs": [
            {"text": "数字分身", "active": True},
            {"text": "背景", "active": False},
            {"text": "视频", "active": False},
        ],
        "workbenchTabs": [{"text": "直播脚本", "active": True}],
        "textareas": [{"value": "大家好，今天介绍品酒大师系列。", "maxlength": 3000}],
    }
    session, runner = make_session(["result: " + json.dumps(payload, ensure_ascii=False)])

    state = session.read_current_state(open_if_needed=False)

    assert state.live_room_id == "39826"
    assert state.live_room_name == "京东空白直播间-0707-1352"
    assert state.platform == "京东版"
    assert state.active_scene_name == "场景01"
    assert [scene.name for scene in state.scenes] == ["场景01", "场景02"]
    assert state.scenes[0].scene_type == "讲品"
    assert state.scenes[0].active is True
    assert [layer.name for layer in state.layers] == ["前景", "品酒大师(PRO）", "微信图片_20260618221607_11_15"]
    assert state.active_material_tab == "数字分身"
    assert state.active_workbench_tab == "直播脚本"
    assert state.script_texts == ["大家好，今天介绍品酒大师系列。"]
    assert runner.commands == [("uv", "run", "browser-use", "eval", BrowserUseCliSession.CURRENT_STATE_SCRIPT)]


def test_probe_opens_maitu_home_when_current_page_is_elsewhere() -> None:
    session, runner = make_session(
        [
            "Title: Example\nURL: https://example.com\nExample Domain",
            "opened https://live2.maituai.com/",
            "Title: MyTwins麦兔直播\nURL: https://live2.maituai.com/Home\n首页\n数字分身\n素材管理\n直播间",
        ]
    )

    probe = session.probe_current_page(open_if_needed=True)

    assert probe.logged_in is True
    assert probe.login_required is False
    assert probe.opened_home is True
    assert runner.commands == [
        ("uv", "run", "browser-use", "state"),
        ("uv", "run", "browser-use", "--headed", "open", "https://live2.maituai.com/"),
        ("uv", "run", "browser-use", "state"),
    ]


def test_open_home_falls_back_to_existing_session_on_headed_config_mismatch() -> None:
    runner = ConfigMismatchRunner()
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            home_url="https://live2.maituai.com/",
            headed=True,
            session_name=None,
            cdp_url=None,
        ),
        runner=runner,
    )

    session.open_home()

    assert runner.commands == [
        ("uv", "run", "browser-use", "--headed", "open", "https://live2.maituai.com/"),
        ("uv", "run", "browser-use", "open", "https://live2.maituai.com/"),
    ]


def test_ensure_ready_fails_manual_when_maitu_login_page_is_visible() -> None:
    session, _runner = make_session([
        "Title: MyTwins麦兔直播\nURL: https://live2.maituai.com/Login\n手机号\n密码\n登录",
    ])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.ensure_ready(maitu_project_code="MT-PROJ-1", scene_name="京东空白直播间")

    assert exc_info.value.retryable is False
    assert "login" in str(exc_info.value).lower()
    assert "人工登录" in (exc_info.value.retry_instruction or "")


def test_probe_accepts_logged_in_maitu_dashboard_without_opening_home() -> None:
    session, runner = make_session([
        "Title: MyTwins麦兔直播\nURL: https://live2.maituai.com/Home\n首页\n商品库\n数字分身\n素材管理",
    ])

    session.ensure_ready(maitu_project_code=None, scene_name=None)

    assert session.last_probe is not None
    assert session.last_probe.logged_in is True
    assert runner.commands == [("uv", "run", "browser-use", "state")]


def test_probe_rereads_an_empty_maitu_shell_before_classifying_login() -> None:
    session, runner = make_session(
        [
            '{"title":"MyTwins麦兔直播","href":"https://live2.maituai.com/LiveRoom?liveRoomId=38336","text":""}',
            '{"title":"MyTwins麦兔直播","href":"https://live2.maituai.com/Login","text":"欢迎，登陆麦兔直播\\n手机号登录"}',
        ]
    )

    probe = session.probe_current_page(open_if_needed=True)

    assert probe.logged_in is False
    assert probe.login_required is True
    assert runner.commands == [
        ("uv", "run", "browser-use", "state"),
        ("uv", "run", "browser-use", "state"),
    ]


def test_readonly_session_blocks_mutating_operations() -> None:
    session, _runner = make_session([])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.replace_layer_asset({"slot_code": "MT-SLOT-1"}, {"asset_code": "AG-IMG-1"})

    assert exc_info.value.retryable is False
    assert "read-only" in str(exc_info.value)


def test_probe_command_can_parse_json_summary_from_browser_use_eval_output() -> None:
    session, _runner = make_session([
        '{"title":"MyTwins麦兔直播","href":"https://live2.maituai.com/Home","text":"首页\\n素材管理\\n直播间"}',
    ])

    summary = session.read_page_summary()

    assert summary["title"] == "MyTwins麦兔直播"
    assert summary["href"] == "https://live2.maituai.com/Home"
    assert "素材管理" in summary["text"]


def test_state_without_url_falls_back_to_eval_summary() -> None:
    session, runner = make_session(
        [
            "viewport: 2560x1600\n欢迎，登陆麦兔直播",
            '{"title":"MyTwins麦兔直播","href":"https://live2.maituai.com/Login","text":"欢迎，登陆麦兔直播\\n账号登录"}',
        ]
    )

    summary = session.read_page_summary()

    assert summary["title"] == "MyTwins麦兔直播"
    assert summary["href"] == "https://live2.maituai.com/Login"
    assert runner.commands == [
        ("uv", "run", "browser-use", "state"),
        ("uv", "run", "browser-use", "eval", BrowserUseCliSession.PAGE_SUMMARY_SCRIPT),
    ]


def test_cli_session_checks_lease_guard_before_every_browser_command() -> None:
    session, runner = make_session(
        [
            "viewport: 2560x1600\n欢迎，登陆麦兔直播",
            '{"title":"unused","href":"https://live2.maituai.com/Login","text":"unused"}',
        ]
    )
    guard_calls = 0

    def lease_is_valid() -> bool:
        nonlocal guard_calls
        guard_calls += 1
        return guard_calls < 2

    session.set_execution_guard(lease_is_valid)

    with pytest.raises(MaituBrowserExecutionError, match="lease"):
        session.read_page_summary()

    assert runner.commands == [("uv", "run", "browser-use", "state")]


def test_read_jd_live_dashboard_state_opens_dashboard_url_and_extracts_metrics() -> None:
    session, runner = make_session([
        "opened https://jm.jd.com/live-data",
        "Title: 京麦商家后台\nURL: https://jm.jd.com/live-data\n直播数据\n在线人数 12\nGMV 345.67元",
    ])

    state = session.read_jd_live_dashboard_state(open_url="https://jm.jd.com/live-data")

    assert state.logged_in is True
    assert state.login_required is False
    assert state.metrics["online_viewers"] == 12
    assert state.metrics["gmv"] == 345.67
    assert runner.commands == [
        ("uv", "run", "browser-use", "--headed", "open", "https://jm.jd.com/live-data"),
        ("uv", "run", "browser-use", "state"),
    ]


def test_live_scene_fill_api_methods_use_browser_use_eval() -> None:
    room_payload = {
        "id": 40173,
        "_assetgraph_read_environment": "working",
        "topics": [{"clips": [{"id": 416425, "name": "未命名", "order_num": 0}]}],
    }
    rename_payload = {"clip_id": 416425, "name": "商品01-场景01"}
    fill_payload = {"target_clip_id": 416425, "visual_count": 2, "text_count": 1, "layer_names": ["背景", "标题+logo"]}
    session, runner = make_session([
        "result: " + json.dumps(room_payload, ensure_ascii=False),
        "result: " + json.dumps(rename_payload, ensure_ascii=False),
        "result: " + json.dumps(fill_payload, ensure_ascii=False),
    ])

    assert session.read_live_room("40173") == room_payload
    assert session.rename_clip(live_room_id="40173", clip_id=416425, name="商品01-场景01") == rename_payload
    assert session.fill_clip_from_template(
        live_room_id="40173",
        target_clip_id=416425,
        reference_room_id="38336",
        reference_clip_id="390051",
        scene_name="商品01-场景01",
        component_operations=[{"layer_name": "背景"}, {"layer_name": "标题+logo"}],
        script_content="脚本",
    ) == fill_payload

    assert len(runner.commands) == 3
    assert all(command[:4] == ("uv", "run", "browser-use", "eval") for command in runner.commands)
    assert all("(localStorage.getItem('token') || '').trim()" in command[4] for command in runner.commands)
    assert "live_rooms/40173" in runner.commands[0][4]
    assert "_assetgraph_read_environment:'working'" in runner.commands[0][4]
    assert "clips/416425" in runner.commands[1][4]
    assert '\"liveRoomId\": \"40173\"' in runner.commands[1][4]
    assert runner.commands[1][4].index("rename target clip not found") < runner.commands[1][4].index("xhr('PUT'")
    assert "replace_clip_materials" in runner.commands[2][4]
    assert runner.commands[2][4].count("replace_clip_materials") == 1
    assert "cumulative" not in runner.commands[2][4]
    assert "const count = args.componentOperations.length;" in runner.commands[2][4]
    assert "|| visualMaterials.length" not in runner.commands[2][4]
    assert "localStorage.getItem('token')" in runner.commands[2][4]
    assert "material.type === 'audio'" not in runner.commands[2][4]
    assert "xhr('PUT', 'clip_materials/'" in runner.commands[2][4]
    assert "matchingTexts.length !== 1" in runner.commands[2][4]
    assert "go_live_clicked: false" in runner.commands[2][4]


def test_test_room_reset_api_methods_are_target_bound_never_live_and_authoritatively_verified() -> None:
    delete_payload = {
        "status": "deleted",
        "live_room_id": "41172",
        "clip_id": 7002,
        "verified": True,
        "go_live_clicked": False,
    }
    clear_payload = {
        "status": "cleared",
        "live_room_id": "41172",
        "clip_id": 7001,
        "deleted_material_ids": [8001, 8002],
        "remaining_material_count": 0,
        "verified": True,
        "go_live_clicked": False,
    }
    session, runner = make_session(
        [
            "result: " + json.dumps(delete_payload, ensure_ascii=False),
            "result: " + json.dumps(clear_payload, ensure_ascii=False),
        ]
    )

    assert session.delete_clip(
        live_room_id="41172",
        clip_id=7002,
        expected_live_room_title="张裕品酒大师PRO测试直播间",
    ) == delete_payload
    assert session.clear_clip_materials(
        live_room_id="41172",
        clip_id=7001,
        expected_live_room_title="张裕品酒大师PRO测试直播间",
    ) == clear_payload

    delete_script = runner.commands[0][4]
    clear_script = runner.commands[1][4]
    for script in (delete_script, clear_script):
        assert "live_rooms/' + args.liveRoomId + '?env=working&include_qa_clips=true'" in script
        assert "room.name !== args.expectedLiveRoomTitle" in script
        assert "room.live_session_id" in script
        assert "room.latest_live_time" in script
        assert "flatMap" in script
        assert "location.origin !== 'https://live2.maituai.com'" in script
        assert "missing authenticated Maitu token" in script
        assert "verification_source:'working_room_readback'" in script
        assert "go_live_clicked:false" in script
        assert "go_live" not in script.replace("go_live_clicked", "")
    assert "refusing to delete the final clip" in delete_script
    assert "xhr('DELETE', 'clips/' + args.clipId" in delete_script
    assert delete_script.index("requires explicit authoritative never-live evidence") < delete_script.index(
        "xhr('DELETE', 'clips/'"
    )
    assert "xhr('DELETE', 'clip_materials/' + materialId" in clear_script
    assert "assertTargetRoom(beforeDelete, 'before deleting material ' + materialId)" in clear_script
    assert "assertTargetRoom(afterDelete, 'after deleting material ' + materialId)" in clear_script
    assert clear_script.index("assertTargetRoom(beforeDelete") < clear_script.index(
        "xhr('DELETE', 'clip_materials/' + materialId"
    )
    assert clear_script.index("xhr('DELETE', 'clip_materials/' + materialId") < clear_script.index(
        "assertTargetRoom(afterDelete"
    )
    assert "deleted material remains after per-mutation authoritative readback" in clear_script
    assert "verifiedClip.clip_materials.length !== 0" in clear_script


def test_template_fill_and_scene_creation_search_all_topics_and_can_bind_keeper_topic() -> None:
    fill_payload = {"target_clip_id": 7001, "visual_count": 9, "text_count": 0, "go_live_clicked": False}
    create_payload = {"clip_id": 9001, "name": "产品讲解", "verified": True, "go_live_clicked": False}
    rename_payload = {"clip_id": 7001, "name": "开场介绍", "verified": True, "go_live_clicked": False}
    script_payload = {"clip_id": 7001, "script_content_verified": True, "verified": True, "go_live_clicked": False}
    session, runner = make_session(
        [
            "result: " + json.dumps(fill_payload, ensure_ascii=False),
            "result: " + json.dumps(create_payload, ensure_ascii=False),
            "result: " + json.dumps(rename_payload, ensure_ascii=False),
            "result: " + json.dumps(script_payload, ensure_ascii=False),
        ]
    )

    session.fill_clip_from_template(
        live_room_id="41172",
        target_clip_id=7001,
        reference_room_id="38336",
        reference_clip_id="390069",
        scene_name="产品讲解",
        component_operations=[{"operation_type": "insert_template_component"} for _ in range(9)],
        script_content=None,
        expected_live_room_title="张裕品酒大师PRO测试直播间",
    )
    session.create_scene(
        live_room_id="41172",
        scene_name="产品讲解",
        scene_index=1,
        topic_id=102,
        expected_live_room_title="张裕品酒大师PRO测试直播间",
    )
    session.rename_clip(
        live_room_id="41172",
        clip_id=7001,
        name="开场介绍",
        expected_live_room_title="张裕品酒大师PRO测试直播间",
    )
    session.write_script(
        live_room_id="41172",
        clip_id=7001,
        scene_name="开场介绍",
        script_text="欢迎来到直播间。",
        expected_live_room_title="张裕品酒大师PRO测试直播间",
    )

    fill_script = runner.commands[0][4]
    create_script = runner.commands[1][4]
    rename_script = runner.commands[2][4]
    write_script = runner.commands[3][4]
    assert "arr(refRoom.topics).flatMap" in fill_script
    assert "arr(targetBeforeText.topics).flatMap" in fill_script
    assert "arr(verifiedRoom.topics).flatMap" in fill_script
    assert "JSON.parse(m.style_front" in fill_script
    assert fill_script.count("replace_clip_materials") == 1
    assert "view_clip_materials: selectedVisuals" in fill_script
    assert "cumulative" not in fill_script
    assert '"topicId": 102' in create_script
    assert "topics.find((item) => String(item && item.id) === String(args.topicId))" in create_script
    assert "arr(verifyRoom.topics).flatMap" in create_script
    for script in (fill_script, create_script, rename_script, write_script):
        assert "expectedLiveRoomTitle" in script
        assert "latest_live_time" in script
        assert "live_session_id" in script
        assert "never-live evidence" in script
    assert "(room.topics || []).flatMap" in rename_script
    assert "arr(room.topics).flatMap" in write_script
    assert "readTargetClip('before primary text write')" in write_script
    assert "readTargetClip('after primary text write')" in write_script
    assert "readTargetClip('before duplicate text delete ' + duplicate.id)" in write_script
    assert "readTargetClip('after duplicate text delete ' + duplicate.id)" in write_script
    assert write_script.index("readTargetClip('before duplicate text delete '") < write_script.index(
        "xhr('DELETE', 'clip_materials/' + duplicate.id"
    )
    assert write_script.index("xhr('DELETE', 'clip_materials/' + duplicate.id") < write_script.index(
        "readTargetClip('after duplicate text delete '"
    )
    assert "readTargetClip('before text create')" in write_script
    assert "readTargetClip('after text create')" in write_script


def test_script_layout_draft_api_methods_use_browser_use_eval() -> None:
    create_payload = {"status": "created", "clip_id": 416426, "name": "促单", "go_live_clicked": False}
    insert_payload = {"status": "manual_required", "reason": "missing_maitu_material_binding", "asset_code": "AG-IMG-BG", "go_live_clicked": False}
    position_payload = {"status": "manual_required", "reason": "target_material_not_found", "layer_id": "scene-00-background_image", "go_live_clicked": False}
    script_payload = {"status": "written", "clip_id": 416425, "script_length": 9, "go_live_clicked": False}
    verify_payload = {"status": "verified", "clip_id": 416425, "visual_count": 0, "text_count": 1, "script_present": True, "go_live_clicked": False}
    session, runner = make_session([
        "result: " + json.dumps(create_payload, ensure_ascii=False),
        "result: " + json.dumps(insert_payload, ensure_ascii=False),
        "result: " + json.dumps(position_payload, ensure_ascii=False),
        "result: " + json.dumps(script_payload, ensure_ascii=False),
        "result: " + json.dumps(verify_payload, ensure_ascii=False),
    ])

    assert session.create_scene(live_room_id="47000002", scene_name="促单", scene_index=1) == create_payload
    assert session.insert_asset_layer(
        live_room_id="47000002",
        clip_id=416425,
        operation={
            "layer_id": "scene-00-background_image",
            "layer_type": "background_image",
            "source_material_type": "image",
            "asset_code": "AG-IMG-BG",
            "asset_local_relative_path": "背景/bg.png",
            "x": 0,
            "y": 0,
            "width": 1080,
            "height": 1920,
            "z_index": 1,
        },
    )["status"] == "manual_required"
    assert session.position_asset_layer(
        live_room_id="47000002",
        clip_id=416425,
        operation={"layer_id": "scene-00-background_image", "asset_code": "AG-IMG-BG", "x": 0, "y": 0, "z_index": 1},
    )["reason"] == "target_material_not_found"
    assert session.write_script(live_room_id="47000002", clip_id=416425, scene_name="开场", script_text="欢迎来到直播间。") == script_payload
    assert session.verify_scene(live_room_id="47000002", clip_id=416425, scene_name="开场", operation={}) == verify_payload

    assert len(runner.commands) == 5
    assert all(command[:4] == ("uv", "run", "browser-use", "eval") for command in runner.commands)
    assert "'POST', 'clips'" in runner.commands[0][4]
    assert "created scene response did not include an authoritative clip id" in runner.commands[0][4]
    assert "find((clip) => clip.name === args.sceneName" not in runner.commands[0][4]
    assert "missing_maitu_material_binding" in runner.commands[1][4]
    assert "'PUT', 'clip_materials/'" in runner.commands[2][4]
    assert "exact clip-material source or audio identity mismatch before position mutation" in runner.commands[2][4]
    assert "sound_enabled: op.sound_enabled === true" in runner.commands[1][4]
    assert "Boolean(verifiedMaterial.sound_enabled)" in runner.commands[1][4]
    assert "'POST', 'clip_materials'" in runner.commands[3][4]
    assert "script target clip identity mismatch before write" in runner.commands[3][4]
    assert "script target clip identity mismatch after write" in runner.commands[3][4]
    assert "'live_rooms/' + args.liveRoomId" in runner.commands[4][4]
    assert "const expectedLayers = arr(op.expected_layers)" in runner.commands[4][4]
    assert "const exactNumber =" in runner.commands[4][4]
    assert "text_material_id:texts[0].id" in runner.commands[4][4]
    assert "verify scene layer source or geometry mismatch" in runner.commands[4][4]
    assert all("location.origin !== 'https://live2.maituai.com'" in command[4] for command in runner.commands)
    assert all("(localStorage.getItem('token') || '').trim()" in command[4] for command in runner.commands)
    assert all("if (!token)" in command[4] for command in runner.commands)
    assert "material.type === 'audio'" not in runner.commands[3][4]
    assert "xhr('PUT', 'clip_materials/'" in runner.commands[3][4]
    assert "verifiedTexts.length !== 1 || verifiedTexts[0].content !== args.scriptText" in runner.commands[3][4]
    assert all("go_live_clicked" in command[4] for command in runner.commands)


def test_digital_human_insert_uses_source_record_but_verifies_composite_identity() -> None:
    inserted = {
        "status": "inserted",
        "material_id": 88001,
        "source_material_id": 37200,
        "source_material_type": "digital_human",
        "source_material_url": "https://static.example/digital-human/7717.png",
        "speaker_id": 3760,
        "digital_human_image_id": 7717,
        "verified": True,
        "go_live_clicked": False,
    }
    session, runner = make_session(["result: " + json.dumps(inserted, ensure_ascii=False)])

    assert session.insert_asset_layer(
        live_room_id="41172",
        clip_id=7001,
        operation={
            "layer_id": "scene-00-digital-human",
            "layer_type": "digital_human",
            "source_material_type": "digital_human",
            "maitu_material_id": None,
            "maitu_source_material_id": 37200,
            "source_material_url": None,
            "source_cover_url": "https://static.example/digital-human/7717.png",
            "speaker_id": 3760,
            "digital_human_image_id": 7717,
            "expected_live_room_title": "asser测试",
            "require_offline_working_room": True,
        },
    ) == inserted

    script = runner.commands[0][4]
    assert '"maitu_source_material_id": 37200' in script
    assert "op.maitu_source_material_id || null" in script
    assert "const verifiedSourceMatches = verifiedMaterial && isDigitalHuman" in script
    assert "String(verifiedMaterial.digital_human_image_id || '') === String(digitalHumanImageId || '')" in script
    assert "String(verifiedMaterial.speaker_id || '') === String(speakerId || '')" in script
    assert "source_material_id: verifiedMaterial.material_id || materialId" in script
    assert "source_material_url: verifiedMaterial.url || sourceUrl" in script


def test_verify_scene_uses_render_style_geometry_and_canonical_source_url() -> None:
    verify_payload = {
        "status": "verified",
        "clip_id": 7001,
        "verified": True,
        "verification_source": "working_room_readback",
        "go_live_clicked": False,
    }
    session, runner = make_session(["result: " + json.dumps(verify_payload, ensure_ascii=False)])

    assert session.verify_scene(
        live_room_id="41172",
        clip_id=7001,
        scene_name="产品讲解",
        operation={
            "scene_index": 1,
            "expected_visual_count": 1,
            "expected_text_count": 1,
            "expected_script_text": "介绍张裕品酒大师PRO。",
            "expected_layers": [
                {
                    "material_id": 80001,
                    "layer_id": "商品主视觉",
                    "source_material_type": "image",
                    "source_material_id": 50001,
                    "source_material_url": "https://cdn.example.test/product.png",
                    "left": 10,
                    "top": 20,
                    "width": 1080,
                    "height": 1920,
                    "z_index": 3,
                    "style_front": {
                        "left": 43.196,
                        "top": 187.533,
                        "width": 440,
                        "height": 782,
                        "zIndex": 3,
                        "transform": {"scale": 1, "rotation": 0},
                    },
                }
            ],
        },
    ) == verify_payload

    script = runner.commands[0][4]
    assert "left: style.left ?? material.left" in script
    assert "top: style.top ?? material.top" in script
    assert "width: style.width ?? material.width" in script
    assert "height: style.height ?? material.height" in script
    assert "zIndex: style.zIndex ?? material.layer_n" in script
    assert "const canonicalSourceUrl = (value)" in script
    assert "canonicalSourceUrl(material.url) === canonicalSourceUrl(expected.source_material_url)" in script
    assert "Object.keys(value).sort()" in script
    assert "Object.prototype.hasOwnProperty.call(expected, 'style_front')" in script
    assert "normalizeJson(expected.style_front)" in script
    assert "normalizeJson(expected.style_front || {})" not in script
    assert "verify scene style_front snapshot mismatch" in script
    assert "exactNumber(geometry.width, expected.width)" in script
    assert "exactNumber(geometry.height, expected.height)" in script
    assert "exactNumber(geometry.zIndex, expected.z_index)" in script


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://live2.maituai.com/", True),
        ("https://live2.maituai.com/MaterialManage", True),
        ("https://live2.maituai.com:443/MaterialManage", True),
        ("http://live2.maituai.com/", False),
        ("https://live2.maituai.com:444/", False),
        ("https://user@live2.maituai.com/", False),
        ("https://maituai.com.evil.test/MyTwins", False),
        ("https://evil.test/?next=live2.maituai.com", False),
        ("javascript:https://live2.maituai.com", False),
    ],
)
def test_maitu_url_detection_requires_exact_https_origin(url: str, expected: bool) -> None:
    assert BrowserUseCliSession._is_maitu_url(url) is expected


def test_logged_in_detection_rejects_lookalike_maitu_url() -> None:
    assert (
        BrowserUseCliSession._looks_like_logged_in(
            "MyTwins 麦兔",
            "https://maituai.com.evil.test/MyTwins",
            "素材管理 直播间",
        )
        is False
    )


def test_logged_in_detection_rejects_unsettled_maitu_shell() -> None:
    assert (
        BrowserUseCliSession._looks_like_logged_in(
            "MyTwins麦兔直播",
            "https://live2.maituai.com/LiveRoom?liveRoomId=38336",
            "",
        )
        is False
    )


@pytest.mark.parametrize(
    ("layer_type", "source_type", "expected"),
    [
        ("product_image", "image", "image"),
        ("product_video", "decorative_video", "video"),
        ("supporting_visual", "image", "image"),
        ("supporting_visual", "video", "video"),
        ("background", "image", "image"),
        ("background", "decorative_video", "video"),
        ("set_surface", "image", "image"),
        ("product_display", "image", "image"),
        ("product_display", "decorative_video", "video"),
        ("brand_title", "image", "image"),
        ("promotion_text", "image", "image"),
        ("decoration_foreground", "decorative_video", "video"),
        ("supporting_video", "decorative_video", "video"),
        ("digital_human", "digital_human", "digital_human"),
        ("product_image", "decorative_video", None),
        ("set_surface", "decorative_video", None),
        ("supporting_video", "image", None),
        ("voice", "video", None),
    ],
)
def test_resolved_operation_material_type_is_layer_and_source_type_safe(
    layer_type: str,
    source_type: str,
    expected: str | None,
) -> None:
    assert (
        BrowserUseCliSession._resolved_operation_material_type(
            {"layer_type": layer_type, "source_material_type": source_type}
        )
        == expected
    )


def test_insert_asset_layer_uses_resolved_source_type_for_polymorphic_and_strict_video_layers() -> None:
    session, runner = make_session(['{"status":"inserted"}', '{"status":"inserted"}'])
    binding = {
        "asset_code": "AG-VID-SHARED",
        "maitu_material_id": 42601,
        "source_material_type": "decorative_video",
        "source_material_url": "https://static.example/shared.mp4",
    }

    supporting_result = session.insert_asset_layer(
        live_room_id="47000002",
        clip_id=416425,
        operation={**binding, "layer_type": "supporting_visual"},
    )
    strict_video_result = session.insert_asset_layer(
        live_room_id="47000002",
        clip_id=416425,
        operation={**binding, "layer_type": "product_video"},
    )

    assert supporting_result["status"] == "inserted"
    assert strict_video_result["status"] == "inserted"
    assert len(runner.commands) == 2
    assert all('"materialType": "video"' in command[4] for command in runner.commands)
    assert all("type: materialType" in command[4] for command in runner.commands)
    assert all("normalizeMaterialType(verifiedMaterial.type)" in command[4] for command in runner.commands)
    assert all("sound_enabled: op.sound_enabled === true" in command[4] for command in runner.commands)


def test_functional_plan_business_roles_map_to_explicit_maitu_payload_types() -> None:
    operations = [
        ("background", "image", "image"),
        ("set_surface", "image", "image"),
        ("product_display", "decorative_video", "video"),
        ("digital_human", "digital_human", "digital_human"),
        ("brand_title", "image", "image"),
        ("promotion_text", "image", "image"),
        ("decoration_foreground", "image", "image"),
        ("supporting_video", "decorative_video", "video"),
    ]

    assert [
        BrowserUseCliSession._resolved_operation_material_type(
            {"layer_type": role, "source_material_type": source_type}
        )
        for role, source_type, _expected in operations
    ] == [expected for _role, _source_type, expected in operations]


@pytest.mark.parametrize("layer_type", ["background_image", "product_image", "product_video"])
def test_insert_asset_layer_rejects_digital_human_binding_for_strict_image_or_video_layer(layer_type: str) -> None:
    session, runner = make_session([])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.insert_asset_layer(
            live_room_id="47000002",
            clip_id=416425,
            operation={
                "asset_code": "AG-DH-WRONG-LAYER",
                "layer_type": layer_type,
                "source_material_type": "digital_human",
                "maitu_material_id": 40222,
                "source_material_url": "https://static.example/dh.png",
                "speaker_id": 4224,
                "digital_human_image_id": 8856,
            },
        )

    assert "incompatible" in str(exc_info.value)
    assert runner.commands == []


def test_non_destructive_scene_and_tab_clicks_use_browser_use_eval() -> None:
    session, runner = make_session([
        '{"clicked":true,"target":"场景02"}',
        '{"clicked":true,"target":"装饰"}',
        '{"clicked":true,"target":"直播脚本"}',
    ])

    assert session.select_scene("场景02")["clicked"] is True
    assert session.open_material_tab("装饰")["target"] == "装饰"
    assert session.open_workbench_tab("直播脚本")["target"] == "直播脚本"
    assert [command[:4] for command in runner.commands] == [
        ("uv", "run", "browser-use", "eval"),
        ("uv", "run", "browser-use", "eval"),
        ("uv", "run", "browser-use", "eval"),
    ]
    assert "场景02" in runner.commands[0][4]
    assert "装饰" in runner.commands[1][4]
    assert "直播脚本" in runner.commands[2][4]


def test_non_destructive_text_click_keeps_newline_regex_escaped_for_browser_eval() -> None:
    session, runner = make_session(['{"clicked":true,"target":"视频"}'])

    session._click_existing_text_target(target="视频", selectors=("div", "button"), action_name="test")

    script = runner.commands[0][4]
    assert "text.split(/\\n/)" in script
    assert "text.split(/\n/)" not in script


def test_non_destructive_click_raises_when_target_is_missing() -> None:
    session, _runner = make_session(['{"clicked":false,"reason":"target_not_found","target":"场景99"}'])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.select_scene("场景99")

    assert exc_info.value.retryable is False
    assert "场景99" in str(exc_info.value)


def test_list_maitu_materials_combines_regular_and_digital_human_records() -> None:
    inventory_payload = {
        "materials": [
            {"id": 41043, "name": "6月29日 (2)-9051.mp4", "type": "decorative_video"},
        ],
        "digital_humans": [
            {
                "id": 37200,
                "name": "张裕定制形象260519",
                "type": "digital_human",
                "speaker_id": 3760,
                "digital_human_image_id": 7717,
            }
        ],
    }
    session, runner = make_session(["result: " + json.dumps(inventory_payload, ensure_ascii=False)])

    materials = session.list_maitu_materials()

    assert [material["id"] for material in materials] == [41043, 37200]
    assert materials[1]["digital_human_image_id"] == 7717
    assert len(runner.commands) == 1
    assert runner.commands[0][:4] == ("uv", "run", "browser-use", "eval")
    assert "allPages('materials?is_pub=false')" in runner.commands[0][4]
    assert "allPages('materials/digital_human?access_rule=private')" in runner.commands[0][4]
    assert "page * limit" in runner.commands[0][4]
    assert "Unexpected inventory response schema" in runner.commands[0][4]


def test_list_maitu_materials_rejects_malformed_inventory_record() -> None:
    session, _runner = make_session(
        [
            "result: "
            + json.dumps(
                {"materials": [{"id": "not-a-number", "name": "坏记录", "type": "image"}], "digital_humans": []},
                ensure_ascii=False,
            )
        ]
    )

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.list_maitu_materials()

    assert "invalid record" in str(exc_info.value)


def test_maitu_account_identity_caches_api_token_without_returning_it() -> None:
    session, runner = make_session(
        [
            "result: "
            + json.dumps(
                {"external_account_id": 88, "account_name": "operator", "token": "secret-token"}
            )
        ]
    )

    identity = session.read_maitu_account_identity()

    assert identity == {"external_account_id": 88, "account_name": "operator"}
    assert session._maitu_api_token == "secret-token"
    assert len(runner.commands) == 1


def test_maitu_interaction_api_uses_cached_browser_token_and_fixed_api_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, runner = make_session([])
    session._maitu_api_token = "secret-token"
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, limit: int) -> bytes:
            assert limit == 16 * 1024 * 1024 + 1
            return json.dumps({"success": True, "data": {"items": [], "total": 0}}).encode()

    def fake_urlopen(request, *, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(browser_cli_session_module.urllib.request, "urlopen", fake_urlopen)

    payload = session.get_maitu_interaction_api_page(
        "live_session/?offset=0&limit=100&status=2&live_room_platform=4"
    )

    assert payload == {"items": [], "total": 0}
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url.startswith("https://api.maituai.com/live_session/")
    assert request.get_header("Authorization") == "secret-token"
    assert timeout == 12
    assert runner.commands == []


def test_maitu_interaction_api_rejects_untrusted_path_before_browser_or_network() -> None:
    session, runner = make_session([])

    with pytest.raises(ValueError, match="unsupported"):
        session.get_maitu_interaction_api_page("users/me")

    assert runner.commands == []


def test_upload_maitu_material_uses_visible_material_page_file_input_and_reads_back(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "新品主图.png"
    image_path.write_bytes(b"image")
    inventory_payload = {
        "materials": [
            {
                "id": 50001,
                "name": "新品主图.png",
                "type": "image",
                "url": "https://static.example/new-product.png",
            }
        ],
        "digital_humans": [],
    }
    session, runner = make_session(
        [
            "opened material page",
            '{"ready":true,"href":"https://live2.maituai.com/MaterialManage"}',
            '{"clicked":true,"target":"装饰"}',
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "|SHADOW(open)|*[561]<input type=file accept=video/mp4,video/quicktime />\n"
            "|SHADOW(open)|*[562]<input type=file accept=image/jpeg,image/png,image/gif />",
            "result: " + json.dumps({"materials": [], "digital_humans": []}, ensure_ascii=False),
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "uploaded file",
            "result: " + json.dumps(inventory_payload, ensure_ascii=False),
        ]
    )
    monkeypatch.setattr("browser_use_worker.browser_cli_session.time.sleep", lambda _seconds: None)

    uploaded = session.upload_maitu_material(
        asset={"asset_code": "AG-IMG-1", "subject": "新品主图", "original_filename": "新品主图.png"},
        local_path=image_path,
        layer_type="product_image",
    )

    assert uploaded["id"] == 50001
    assert uploaded["url"].endswith("new-product.png")
    assert runner.commands[0] == (
        "uv",
        "run",
        "browser-use",
        "--headed",
        "open",
        "https://live2.maituai.com/MaterialManage",
    )
    assert runner.commands[1][:4] == ("uv", "run", "browser-use", "eval")
    assert "MaterialManage" in runner.commands[1][4]
    assert runner.commands[2][:4] == ("uv", "run", "browser-use", "eval")
    assert "装饰" in runner.commands[2][4]
    assert runner.commands[3][:4] == ("uv", "run", "browser-use", "eval")
    assert "location.origin === 'https://live2.maituai.com'" in runner.commands[3][4]
    assert "MaterialManage__container" in runner.commands[3][4]
    assert "kindInputs.length === 1" in runner.commands[3][4]
    assert runner.commands[4] == ("uv", "run", "browser-use", "state")
    assert runner.commands[5][:4] == ("uv", "run", "browser-use", "eval")
    assert runner.commands[6][:4] == ("uv", "run", "browser-use", "eval")
    assert "location.origin === 'https://live2.maituai.com'" in runner.commands[6][4]
    assert runner.commands[7] == ("uv", "run", "browser-use", "upload", "562", str(image_path))


def test_upload_video_selects_new_video_record_not_existing_same_subject_image(monkeypatch, tmp_path) -> None:
    video_path = tmp_path / "MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4"
    video_path.write_bytes(b"video")
    existing_image = {
        "id": 40999,
        "name": "品酒大师(PRO）",
        "type": "image",
        "url": "https://static.example/product-pro.png",
    }
    uploaded_video = {
        "id": 42601,
        "name": "MT-VID-0024_视频_商品讲解视频_品酒大师PRO-836.mp4",
        "type": "decorative_video",
        "url": "https://static.example/product-pro-836.mp4",
    }
    before_payload = {"materials": [existing_image], "digital_humans": []}
    after_payload = {"materials": [uploaded_video, existing_image], "digital_humans": []}
    session, runner = make_session(
        [
            "opened material page",
            '{"ready":true,"href":"https://live2.maituai.com/MaterialManage"}',
            '{"clicked":true,"target":"视频"}',
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "|SHADOW(open)|*[561]<input type=file accept=video/mp4,video/quicktime />\n"
            "|SHADOW(open)|*[562]<input type=file accept=image/jpeg,image/png,image/gif />",
            "result: " + json.dumps(before_payload, ensure_ascii=False),
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "uploaded file",
            "result: " + json.dumps(after_payload, ensure_ascii=False),
        ]
    )
    monkeypatch.setattr("browser_use_worker.browser_cli_session.time.sleep", lambda _seconds: None)

    uploaded = session.upload_maitu_material(
        asset={
            "asset_code": "AG-VID-1",
            "subject": "品酒大师PRO",
            "original_filename": video_path.name,
        },
        local_path=video_path,
        layer_type="product_video",
    )

    assert uploaded["id"] == 42601
    assert uploaded["type"] == "decorative_video"
    assert runner.commands[7] == ("uv", "run", "browser-use", "upload", "561", str(video_path))


def test_upload_rejects_file_extension_layer_type_conflict(tmp_path) -> None:
    image_path = tmp_path / "wrong.png"
    image_path.write_bytes(b"image")
    session, runner = make_session([])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.upload_maitu_material(asset={"asset_code": "AG-WRONG"}, local_path=image_path, layer_type="product_video")

    assert exc_info.value.retryable is False
    assert "type mismatch" in str(exc_info.value)
    assert runner.commands == []


def test_upload_rejects_filename_without_stable_readback_key_before_side_effect(tmp_path: Path) -> None:
    image_path = tmp_path / "---.png"
    image_path.write_bytes(b"image")
    session, runner = make_session([])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.upload_maitu_material(asset={"asset_code": "AG-EMPTY-NAME"}, local_path=image_path, layer_type="product_image")

    assert "stable match key" in str(exc_info.value)
    assert runner.commands == []


def test_upload_target_verification_rejects_wrong_origin() -> None:
    session, _runner = make_session(
        ['{"verified":false,"href":"https://evil.example/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}']
    )

    with pytest.raises(MaituBrowserExecutionError):
        session._verify_material_upload_target(target_tab="视频", kind="video")


def test_upload_reverifies_trusted_target_immediately_before_local_file_upload(tmp_path: Path) -> None:
    image_path = tmp_path / "新品主图.png"
    image_path.write_bytes(b"image")
    session, runner = make_session(
        [
            "opened material page",
            '{"ready":true,"href":"https://live2.maituai.com/MaterialManage"}',
            '{"clicked":true,"target":"装饰"}',
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "*[562]<input type=file accept=image/jpeg,image/png,image/gif />",
            "result: " + json.dumps({"materials": [], "digital_humans": []}),
            '{"verified":false,"href":"https://evil.example/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
        ]
    )

    with pytest.raises(MaituBrowserExecutionError):
        session.upload_maitu_material(asset={"asset_code": "AG-IMG-1"}, local_path=image_path, layer_type="product_image")

    assert not any("upload" in command for command in runner.commands)


def test_file_input_indices_preserve_ambiguity_for_fail_closed_upload() -> None:
    state = (
        "*[10]<input type=file accept=image/png,image/jpeg />\n"
        "*[11]<input type=file accept=image/png,image/jpeg />"
    )

    assert BrowserUseCliSession._file_input_indices(state, kind="image") == [10, 11]


def test_upload_readback_rejects_multiple_new_matching_records(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "新品主图.png"
    image_path.write_bytes(b"image")
    after_payload = {
        "materials": [
            {"id": 1, "name": "新品主图-1111.png", "type": "image", "url": "https://static.example/a.png"},
            {"id": 2, "name": "新品主图-2222.png", "type": "image", "url": "https://static.example/b.png"},
        ],
        "digital_humans": [],
    }
    session, _runner = make_session(
        [
            "opened material page",
            '{"ready":true,"href":"https://live2.maituai.com/MaterialManage"}',
            '{"clicked":true,"target":"装饰"}',
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "*[562]<input type=file accept=image/jpeg,image/png,image/gif />",
            "result: " + json.dumps({"materials": [], "digital_humans": []}),
            '{"verified":true,"href":"https://live2.maituai.com/MaterialManage","tab_count":1,"active_tab_count":1,"input_count":1}',
            "uploaded file",
            "result: " + json.dumps(after_payload, ensure_ascii=False),
        ]
    )
    monkeypatch.setattr("browser_use_worker.browser_cli_session.time.sleep", lambda _seconds: None)

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.upload_maitu_material(asset={"asset_code": "AG-IMG-1"}, local_path=image_path, layer_type="product_image")

    assert exc_info.value.retryable is False
    assert "ambiguous" in str(exc_info.value)


def test_subprocess_runner_scrubs_parent_python_environment(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_run(args, **kwargs):
        recorded["args"] = args
        recorded["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="Title: OK", stderr="")

    monkeypatch.setenv("PYTHONPATH", "C:/broken/hermes/site-packages")
    monkeypatch.setenv("PYTHONHOME", "C:/broken/python")
    monkeypatch.setenv("VIRTUAL_ENV", "D:/AssetGraph/workers/browser-use/.venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "D:/wrong/.venv")
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.setattr(subprocess, "run", fake_run)

    session = BrowserUseCliSession(BrowserUseCliSessionConfig(browser_use_repo="D:/browser-use"))
    output = session._run_command(("uv", "run", "browser-use", "state"), cwd="D:/browser-use", timeout_seconds=3)

    env = recorded["env"]
    assert output == "Title: OK"
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "VIRTUAL_ENV" not in env
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["UV_PROJECT_ENVIRONMENT"] == os.path.join("D:/browser-use", ".venv")
    assert env["NO_PROXY"] == "example.com,127.0.0.1,localhost"
    assert env["no_proxy"] == "example.com,127.0.0.1,localhost"


def test_ipv6_loopback_cdp_is_added_to_both_no_proxy_spellings(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "example.com")
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            session_name="safe-session",
            cdp_url="http://[::1]:9222",
        ),
        runner=FakeRunner([]),
    )

    env = session._subprocess_env("D:/browser-use")

    assert env["NO_PROXY"] == "example.com,127.0.0.1,localhost,::1"
    assert env["no_proxy"] == "example.com,127.0.0.1,localhost,::1"
