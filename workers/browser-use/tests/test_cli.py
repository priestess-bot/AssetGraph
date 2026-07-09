from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from browser_use_worker import __main__ as worker_main


@dataclass(slots=True)
class FakeProbe:
    title: str = "MyTwins麦兔直播"
    url: str = "https://live2.maituai.com/Home"
    text: str = "首页\n素材管理\n直播间"
    logged_in: bool = True
    login_required: bool = False
    opened_home: bool = False


class FakeBrowserUseCliSession:
    def __init__(self) -> None:
        self.called = False

    def probe_current_page(self, *, open_if_needed: bool) -> FakeProbe:
        assert open_if_needed is True
        self.called = True
        return FakeProbe(opened_home=True)

    def read_current_state(self, *, open_if_needed: bool):
        assert open_if_needed is True
        self.called = True
        return FakeCurrentState()


@dataclass(slots=True)
class FakeCurrentState:
    title: str = "MyTwins麦兔直播"
    url: str = "https://live2.maituai.com/LiveRoom?liveRoomId=39826"
    live_room_id: str = "39826"
    live_room_name: str = "京东空白直播间-0707-1352"
    platform: str = "京东版"
    active_scene_name: str = "场景01"


def test_probe_maitu_cli_prints_page_probe_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession, raising=False)

    exit_code = worker_main.main(["--probe-maitu"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["logged_in"] is True
    assert output["login_required"] is False
    assert output["opened_home"] is True
    assert output["url"] == "https://live2.maituai.com/Home"


def test_observe_maitu_cli_prints_current_state_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession, raising=False)

    exit_code = worker_main.main(["--observe-maitu"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["live_room_id"] == "39826"
    assert output["live_room_name"] == "京东空白直播间-0707-1352"
    assert output["platform"] == "京东版"
    assert output["active_scene_name"] == "场景01"


class FakeAssetGraphClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def get_replacement_plan_operation_plan(self, plan_code: str) -> dict:
        assert plan_code == "MT-PLAN-20260709-000001"
        return {
            "plan_code": plan_code,
            "maitu_project_code": "MT-PROJ-LOCAL-SMOKE",
            "scene_name": "本地向量检索验证场景",
            "operations": [
                {
                    "operation_type": "replace_layer_asset",
                    "slot_code": "MT-SLOT-20260709-000001",
                    "asset_code": "AG-VID-20260709-000052",
                    "asset_display_code": "MT-VID-0024",
                    "asset_local_file_code": "MT-VID-0024",
                    "asset_original_filename": "MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
                    "asset_local_relative_path": "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
                    "asset_browser_use_hint": "用于麦兔视频素材选择：品酒大师PRO",
                    "instruction": "将素材替换为 MT-VID-0024",
                }
            ],
        }

    def get_asset(self, asset_code: str) -> dict:
        assert asset_code == "AG-VID-20260709-000052"
        return {
            "asset_code": asset_code,
            "display_code": "MT-VID-0024",
            "local_file_code": "MT-VID-0024",
            "title": "视频 - 商品讲解视频 - 品酒大师PRO",
            "local_relative_path": "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
            "file_size": 5,
        }


def test_plan_code_dry_run_cli_prints_result_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)

    exit_code = worker_main.main(["--plan-code", "MT-PLAN-20260709-000001", "--dry-run"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "released"
    assert output["details"]["plan_code"] == "MT-PLAN-20260709-000001"
    assert output["details"]["operations"][0]["asset_display_code"] == "MT-VID-0024"


def test_plan_code_preflight_cli_prints_preflight_json(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)
    asset_file = tmp_path / "视频" / "MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4"
    asset_file.parent.mkdir(parents=True)
    asset_file.write_bytes(b"12345")

    exit_code = worker_main.main(
        [
            "--plan-code",
            "MT-PLAN-20260709-000001",
            "--preflight",
            "--skip-browser-probe",
            "--assets-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "warning"
    assert output["failure_count"] == 0
    assert output["ready_to_execute"] is False
    assert any(check["name"] == "maitu_browser_probe" and check["status"] == "skipped" for check in output["checks"])
