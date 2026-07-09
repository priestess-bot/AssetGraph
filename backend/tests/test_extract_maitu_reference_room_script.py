from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from extract_maitu_reference_room import ExtractOptions, run_extract  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sample_observed_state() -> dict:
    return {
        "title": "MyTwins麦兔直播",
        "url": "https://live2.maituai.com/LiveRoom?liveRoomId=39826",
        "live_room_id": "39826",
        "live_room_name": "京东空白直播间-0707-1352",
        "platform": None,
        "logged_in": True,
        "login_required": False,
        "active_scene_name": "场景01",
        "scenes": [
            {"name": "场景01", "scene_type": "讲品", "active": True, "status": "已激活"},
            {"name": "场景02", "scene_type": "讲品", "active": False, "status": "已激活"},
        ],
        "layers": [
            {"name": "前景", "active": False},
            {"name": "品酒大师(PRO）", "active": False},
            {"name": "标题+logo", "active": False},
            {"name": "微信图片_20260618221607_11_15", "active": False},
        ],
        "material_tabs": [
            {"name": "数字分身", "active": True},
            {"name": "背景", "active": False},
            {"name": "装饰", "active": False},
        ],
        "active_material_tab": "数字分身",
        "workbench_tabs": [
            {"name": "直播脚本", "active": True},
            {"name": "直播互动", "active": False},
        ],
        "active_workbench_tab": "直播脚本",
        "script_texts": ["大家好，今天给大家介绍张裕解百纳品酒大师系列。"],
    }


def test_run_extract_writes_reference_profile_blueprint_and_markdown(tmp_path: Path) -> None:
    observed_path = tmp_path / "current_maitu_state_39826_20260709.json"
    observed_path.write_text(json.dumps(sample_observed_state(), ensure_ascii=False), encoding="utf-8")

    report = run_extract(
        ExtractOptions(
            observed_state_path=observed_path,
            output_dir=tmp_path,
            date_stamp="20260709",
        )
    )

    profile_path = Path(report["profile_output"])
    blueprint_path = Path(report["blueprint_output"])
    markdown_path = Path(report["markdown_output"])
    profile = read_json(profile_path)
    blueprint = read_json(blueprint_path)

    assert report["reference_room_id"] == "39826"
    assert report["scene_count"] == 2
    assert report["active_scene_layer_count"] == 4
    assert report["script_block_count"] == 1

    assert profile["profile_code"] == "MT-REF-20260709-39826"
    assert profile["source"] == "browser_use_observe"
    assert profile["reference_room_id"] == "39826"
    assert profile["reference_room_name"] == "京东空白直播间-0707-1352"
    assert profile["platform"] == "京东"
    assert profile["active_scene_name"] == "场景01"
    assert profile["scenes"][0]["sort_order"] == 1
    assert profile["active_scene_layers"][0]["layer_name"] == "前景"

    assert blueprint["blueprint_code"] == "MT-BP-20260709-39826"
    assert blueprint["reference_profile_code"] == profile["profile_code"]
    assert blueprint["room_type"] == "reference_rebuild"
    assert blueprint["status"] == "draft"
    assert blueprint["reference_room_id"] == "39826"
    assert blueprint["scenes"][0]["scene_code"] == "MT-SCENE-20260709-000001"
    assert blueprint["scenes"][0]["goal"] == "第1段产品讲解"
    assert blueprint["scenes"][1]["layers"] == []

    active_layers = blueprint["scenes"][0]["layers"]
    assert active_layers[0]["layer_code"] == "MT-LAYER-20260709-000001"
    assert active_layers[0]["layer_role"] == "foreground_frame"
    assert active_layers[0]["required_category"] == "floating_sticker"
    assert active_layers[1]["layer_role"] == "digital_human"
    assert active_layers[1]["accepted_asset_types"] == ["IMG", "VID"]
    assert active_layers[2]["layer_role"] == "logo_title"
    assert active_layers[3]["layer_role"] == "background"
    assert active_layers[3]["required_category"] == "background_image"
    assert active_layers[3]["replacement_policy"] == "keep_layout"

    assert blueprint["script_blocks"][0]["scene_name"] == "场景01"
    assert "张裕解百纳" in blueprint["script_blocks"][0]["content"]

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# 麦兔参考直播间蓝图初稿：京东空白直播间-0707-1352" in markdown
    assert "| 场景01 | 讲品 | 已激活 | 是 | 4 |" in markdown
    assert "| 微信图片_20260618221607_11_15 | background | background_image | IMG | keep_layout |" in markdown


def test_run_extract_rejects_unidentified_room(tmp_path: Path) -> None:
    observed_path = tmp_path / "current_maitu_state_unknown.json"
    state = sample_observed_state()
    state["live_room_id"] = ""
    state["url"] = "https://live2.maituai.com/LiveRoom"
    observed_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    try:
        run_extract(ExtractOptions(observed_state_path=observed_path, output_dir=tmp_path, date_stamp="20260709"))
    except ValueError as exc:
        assert "live_room_id" in str(exc)
    else:
        raise AssertionError("expected missing live_room_id to fail")
