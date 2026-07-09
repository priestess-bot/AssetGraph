from __future__ import annotations

import os
import subprocess
from typing import Sequence

import pytest

from browser_use_worker.browser_cli_session import BrowserUseCliSession, BrowserUseCliSessionConfig
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


def make_session(outputs: list[str]) -> tuple[BrowserUseCliSession, FakeRunner]:
    runner = FakeRunner(outputs)
    session = BrowserUseCliSession(
        BrowserUseCliSessionConfig(
            browser_use_repo="D:/browser-use",
            home_url="https://live2.maituai.com/",
            login_url="https://live2.maituai.com/Login",
            headed=True,
            timeout_seconds=12,
        ),
        runner=runner,
    )
    return session, runner


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
        BrowserUseCliSessionConfig(browser_use_repo="D:/browser-use", home_url="https://live2.maituai.com/", headed=True),
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


def test_subprocess_runner_scrubs_parent_python_environment(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_run(args, **kwargs):
        recorded["args"] = args
        recorded["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="Title: OK", stderr="")

    monkeypatch.setenv("PYTHONPATH", "C:/broken/hermes/site-packages")
    monkeypatch.setenv("PYTHONHOME", "C:/broken/python")
    monkeypatch.setenv("VIRTUAL_ENV", "D:/AssetGraph/workers/browser-use/.venv")
    monkeypatch.setattr(subprocess, "run", fake_run)

    session = BrowserUseCliSession(BrowserUseCliSessionConfig(browser_use_repo="D:/browser-use"))
    output = session._run_command(("uv", "run", "browser-use", "state"), cwd="D:/browser-use", timeout_seconds=3)

    env = recorded["env"]
    assert output == "Title: OK"
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "VIRTUAL_ENV" not in env
    assert env["UV_PROJECT_ENVIRONMENT"] == os.path.join("D:/browser-use", ".venv")
