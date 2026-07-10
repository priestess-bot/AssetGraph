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
        self.called = True
        return FakeCurrentState()

    def select_scene(self, scene_name: str) -> dict:
        self.called = True
        return {"clicked": True, "target": scene_name}

    def open_material_tab(self, tab_name: str) -> dict:
        self.called = True
        return {"clicked": True, "target": tab_name}

    def open_workbench_tab(self, tab_name: str) -> dict:
        self.called = True
        return {"clicked": True, "target": tab_name}


@dataclass(slots=True)
class FakeScene:
    name: str
    active: bool = False


@dataclass(slots=True)
class FakeLayer:
    name: str
    active: bool = False


@dataclass(slots=True)
class FakeTab:
    name: str
    active: bool = False


@dataclass(slots=True)
class FakeCurrentState:
    title: str = "MyTwins麦兔直播"
    url: str = "https://live2.maituai.com/LiveRoom?liveRoomId=39826"
    text: str = "场景01\n商品图\n直播脚本"
    live_room_id: str = "39826"
    live_room_name: str = "京东空白直播间-0707-1352"
    platform: str = "京东版"
    logged_in: bool = True
    login_required: bool = False
    scenes: list[FakeScene] | None = None
    active_scene_name: str = "场景01"
    layers: list[FakeLayer] | None = None
    workbench_tabs: list[FakeTab] | None = None

    def __post_init__(self) -> None:
        if self.scenes is None:
            self.scenes = [FakeScene("场景01", active=True)]
        if self.layers is None:
            self.layers = [FakeLayer("商品图")]
        if self.workbench_tabs is None:
            self.workbench_tabs = [FakeTab("直播脚本", active=True)]


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
    writes: list[tuple[str, dict]] = []

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def write_live_room_build_plan_execution_result(self, build_plan_code: str, payload: dict) -> dict:
        self.writes.append((build_plan_code, payload))
        return {
            "execution_code": "MT-EXEC-20260709-000001",
            "build_plan_code": build_plan_code,
            "blueprint_code": "MT-BP-20260709-39826",
            "executor": payload.get("executor", "browser_use"),
            "execution_status": payload["execution_status"],
            "mode": payload["mode"],
            "operation_results": payload["operation_results"],
            "id": "89100000-0000-0000-0000-000000000001",
        }

    def get_live_room_build_plan_operation_plan(self, build_plan_code: str) -> dict:
        assert build_plan_code == "MT-BUILD-20260709-000001"
        return {
            "build_plan_code": build_plan_code,
            "blueprint_code": "MT-BP-20260709-39826",
            "reference_room_id": "39826",
            "operations": [
                {
                    "operation_type": "preflight_build_plan",
                    "operation_name": "只读预检",
                    "sort_order": 1,
                    "status": "ready",
                    "instruction": "只读确认当前麦兔页面，默认不点击正式开播。",
                },
                {
                    "operation_type": "select_scene",
                    "operation_name": "选择场景01",
                    "sort_order": 10,
                    "status": "ready",
                    "scene_name": "场景01",
                    "instruction": "只做定位不保存。",
                },
                {
                    "operation_type": "replace_layer_asset",
                    "operation_name": "规划商品图",
                    "sort_order": 20,
                    "status": "planned",
                    "scene_name": "场景01",
                    "layer_name": "商品图",
                    "required_category": "floating_sticker",
                    "accepted_asset_types": ["IMG"],
                    "replacement_policy": "keep_layout",
                    "instruction": "定位商品图图层并保持原布局。",
                },
                {
                    "operation_type": "add_script_block",
                    "operation_name": "写脚本块",
                    "sort_order": 30,
                    "status": "planned",
                    "scene_name": "场景01",
                    "script_block_code": "SCRIPT-1",
                    "script_block_content": "大家好，今天介绍品酒大师PRO。",
                    "instruction": "写入脚本块，写入后重新 Observe。",
                },
                {
                    "operation_type": "save_live_room",
                    "operation_name": "保存直播间草稿",
                    "sort_order": 999,
                    "status": "manual_review",
                    "instruction": "仅保存草稿；默认不点击正式开播。",
                },
            ],
        }

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


def test_build_plan_preflight_cli_prints_preflight_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession, raising=False)

    exit_code = worker_main.main(["--build-plan-code", "MT-BUILD-20260709-000001", "--preflight-build"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "passed"
    assert output["ready_to_execute"] is True
    assert output["build_plan_code"] == "MT-BUILD-20260709-000001"
    assert any(check["name"] == "maitu_current_state_probe" and check["status"] == "pass" for check in output["checks"])


def test_build_plan_preflight_cli_can_skip_browser_probe(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)

    exit_code = worker_main.main([
        "--build-plan-code",
        "MT-BUILD-20260709-000001",
        "--preflight-build",
        "--skip-browser-probe",
    ])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "warning"
    assert output["ready_to_execute"] is False
    assert any(check["name"] == "maitu_current_state_probe" and check["status"] == "skipped" for check in output["checks"])


def test_build_plan_code_dry_run_cli_prints_safe_operation_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)

    exit_code = worker_main.main(["--build-plan-code", "MT-BUILD-20260709-000001", "--dry-run"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "dry_run"
    assert output["ready_to_execute"] is False
    assert output["build_plan_code"] == "MT-BUILD-20260709-000001"
    assert output["operation_count"] == 5
    assert output["operations"][0]["safe_action"] == "read_only_preflight"
    assert output["operations"][-1]["safe_action"] == "manual_review_save_not_executed"


def test_build_plan_non_destructive_cli_runs_only_allowed_low_risk_actions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession, raising=False)

    exit_code = worker_main.main(["--build-plan-code", "MT-BUILD-20260709-000001", "--non-destructive-build"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert output["ready_for_mutation"] is False
    assert output["allowed_action_count"] == 3
    assert output["blocked_mutation_count"] == 3
    assert output["actions"][1]["action_type"] == "select_scene"
    assert output["actions"][2]["action_type"] == "open_material_tab"
    assert output["actions"][3]["action_type"] == "open_workbench_tab"


def test_build_plan_non_destructive_cli_can_write_execution_result(monkeypatch, capsys) -> None:
    FakeAssetGraphClient.writes = []
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)
    monkeypatch.setattr(worker_main, "BrowserUseCliSession", FakeBrowserUseCliSession, raising=False)

    exit_code = worker_main.main([
        "--build-plan-code",
        "MT-BUILD-20260709-000001",
        "--non-destructive-build",
        "--write-result",
    ])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["worker_result"]["status"] == "completed"
    assert output["execution_result"]["execution_code"] == "MT-EXEC-20260709-000001"
    assert output["execution_result"]["execution_status"] == "completed"
    assert FakeAssetGraphClient.writes[0][0] == "MT-BUILD-20260709-000001"
    written_payload = FakeAssetGraphClient.writes[0][1]
    assert written_payload["mode"] == "non_destructive"
    assert written_payload["operation_results"][1]["action_type"] == "select_scene"


def test_script_layout_draft_execute_cli_reads_plan_file_and_runs_in_memory_dry_run(tmp_path: Path, capsys) -> None:
    plan_file = tmp_path / "script-layout-build-plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "source": "script_content_layout_build_plan_rule_v1",
                "status": "draft_with_placeholders",
                "target_live_room_id": "SMOKE-ROOM-STAGE5A",
                "manual_review_required": True,
                "operations": [
                    {"operation_type": "preflight_content_build_plan", "operation_name": "预检", "status": "ready"},
                    {
                        "operation_type": "fill_default_scene",
                        "operation_name": "填充默认场景",
                        "status": "ready",
                        "scene_index": 0,
                        "scene_name": "开场",
                    },
                    {
                        "operation_type": "insert_asset_layer",
                        "operation_name": "插入背景",
                        "status": "ready",
                        "scene_index": 0,
                        "scene_name": "开场",
                        "layer_id": "scene-00-background_image",
                        "layer_type": "background_image",
                        "asset_code": "AG-IMG-BG",
                        "x": 0,
                        "y": 0,
                        "width": 1080,
                        "height": 1920,
                        "z_index": 1,
                    },
                    {
                        "operation_type": "placeholder_required",
                        "operation_name": "缺失商品图",
                        "status": "manual_required",
                        "scene_index": 0,
                        "scene_name": "开场",
                        "layer_id": "scene-00-product_image",
                        "layer_type": "product_image",
                        "need_type": "product_image",
                        "blocks_execution": True,
                    },
                    {
                        "operation_type": "write_script",
                        "operation_name": "写脚本",
                        "status": "ready",
                        "scene_index": 0,
                        "scene_name": "开场",
                        "script_text": "欢迎来到张裕直播间。",
                    },
                    {"operation_type": "verify_scene", "operation_name": "验证", "status": "ready", "scene_index": 0, "scene_name": "开场"},
                    {"operation_type": "save_draft", "operation_name": "保存草稿", "status": "manual_review"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = worker_main.main([
        "--script-layout-build-plan-file",
        str(plan_file),
        "--script-layout-draft-execute",
        "--dry-run",
    ])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed_with_manual_review"
    assert output["target_live_room_id"] == "SMOKE-ROOM-STAGE5A"
    assert output["ready_for_go_live"] is False
    assert output["placeholder_count"] == 1
    assert output["actions"][1]["action_type"] == "map_first_planned_scene_to_default_clip"
    assert output["actions"][3]["action_type"] == "manual_required_placeholder"
    assert output["actions"][-1]["action_type"] == "manual_review_save_not_clicked"


def test_script_layout_draft_execute_cli_can_write_execution_result(monkeypatch, tmp_path: Path, capsys) -> None:
    FakeAssetGraphClient.writes = []
    monkeypatch.setattr(worker_main, "AssetGraphClient", FakeAssetGraphClient, raising=False)
    plan_file = tmp_path / "script-layout-build-plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "build_plan_code": "MT-BUILD-CONTENT-20260710-000001",
                "source": "script_content_layout_build_plan_rule_v1",
                "status": "draft_with_placeholders",
                "target_live_room_id": "SMOKE-ROOM-STAGE5A",
                "manual_review_required": True,
                "operations": [
                    {"operation_type": "preflight_content_build_plan", "operation_name": "预检", "status": "ready"},
                    {"operation_type": "fill_default_scene", "operation_name": "填充默认场景", "status": "ready", "scene_index": 0, "scene_name": "开场"},
                    {"operation_type": "write_script", "operation_name": "写脚本", "status": "ready", "scene_index": 0, "scene_name": "开场", "script_text": "欢迎来到张裕直播间。"},
                    {"operation_type": "verify_scene", "operation_name": "验证", "status": "ready", "scene_index": 0, "scene_name": "开场"},
                    {"operation_type": "save_draft", "operation_name": "保存草稿", "status": "manual_review"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = worker_main.main([
        "--script-layout-build-plan-file",
        str(plan_file),
        "--script-layout-draft-execute",
        "--dry-run",
        "--write-result",
    ])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["worker_result"]["status"] == "completed_with_manual_review"
    assert output["execution_result"]["execution_code"] == "MT-EXEC-20260709-000001"
    assert FakeAssetGraphClient.writes[0][0] == "MT-BUILD-CONTENT-20260710-000001"
    written_payload = FakeAssetGraphClient.writes[0][1]
    assert written_payload["mode"] == "script_layout_draft"
    assert written_payload["ready_for_go_live"] is False
    assert written_payload["operation_results"][1]["operation_type"] == "fill_default_scene"
