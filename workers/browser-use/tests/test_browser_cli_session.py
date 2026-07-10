from __future__ import annotations

import json
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


def test_non_destructive_click_raises_when_target_is_missing() -> None:
    session, _runner = make_session(['{"clicked":false,"reason":"target_not_found","target":"场景99"}'])

    with pytest.raises(MaituBrowserExecutionError) as exc_info:
        session.select_scene("场景99")

    assert exc_info.value.retryable is False
    assert "场景99" in str(exc_info.value)


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
