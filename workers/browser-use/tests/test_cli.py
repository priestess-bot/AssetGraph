from __future__ import annotations

import json
from dataclasses import dataclass

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


def test_probe_maitu_cli_prints_page_probe_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession, raising=False)

    exit_code = worker_main.main(["--probe-maitu"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["logged_in"] is True
    assert output["login_required"] is False
    assert output["opened_home"] is True
    assert output["url"] == "https://live2.maituai.com/Home"


class FakeAssetGraphClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def get_replacement_plan_operation_plan(self, plan_code: str) -> dict:
        assert plan_code == "MT-PLAN-20260709-000001"
        return {
            "plan_code": plan_code,
            "operations": [
                {
                    "operation_type": "replace_layer_asset",
                    "slot_code": "MT-SLOT-20260709-000001",
                    "asset_code": "AG-VID-20260709-000052",
                    "asset_display_code": "MT-VID-0024",
                    "instruction": "将素材替换为 MT-VID-0024",
                }
            ],
        }


def test_plan_code_dry_run_cli_prints_result_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)

    exit_code = worker_main.main(["--plan-code", "MT-PLAN-20260709-000001", "--dry-run"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "released"
    assert output["details"]["plan_code"] == "MT-PLAN-20260709-000001"
    assert output["details"]["operations"][0]["asset_display_code"] == "MT-VID-0024"
