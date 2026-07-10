from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
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
    assert session.rename_clip(416425, "商品01-场景01") == rename_payload
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
    assert "replace_clip_materials" in runner.commands[2][4]
    assert "const count = args.componentOperations.length;" in runner.commands[2][4]
    assert "|| visualMaterials.length" not in runner.commands[2][4]
    assert "localStorage.getItem('token')" in runner.commands[2][4]
    assert "material.type === 'audio'" not in runner.commands[2][4]
    assert "xhr('PUT', 'clip_materials/'" in runner.commands[2][4]
    assert "matchingTexts.length !== 1" in runner.commands[2][4]
    assert "go_live_clicked: false" in runner.commands[2][4]


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
    assert "missing_maitu_material_binding" in runner.commands[1][4]
    assert "'PUT', 'clip_materials/'" in runner.commands[2][4]
    assert "'POST', 'clip_materials'" in runner.commands[3][4]
    assert "'live_rooms/' + args.liveRoomId" in runner.commands[4][4]
    assert all("location.origin !== 'https://live2.maituai.com'" in command[4] for command in runner.commands)
    assert all("(localStorage.getItem('token') || '').trim()" in command[4] for command in runner.commands)
    assert all("if (!token)" in command[4] for command in runner.commands)
    assert "material.type === 'audio'" not in runner.commands[3][4]
    assert "xhr('PUT', 'clip_materials/'" in runner.commands[3][4]
    assert "verifiedTexts.length !== 1 || verifiedTexts[0].content !== args.scriptText" in runner.commands[3][4]
    assert all("go_live_clicked" in command[4] for command in runner.commands)


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


@pytest.mark.parametrize(
    ("layer_type", "source_type", "expected"),
    [
        ("product_image", "image", "image"),
        ("product_video", "decorative_video", "video"),
        ("supporting_visual", "image", "image"),
        ("supporting_visual", "video", "video"),
        ("digital_human", "digital_human", "digital_human"),
        ("product_image", "decorative_video", None),
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
