from __future__ import annotations

import pytest

from browser_use_worker.script_layout_draft_executor import (
    ScriptLayoutDraftRunner,
    build_script_layout_draft_execution_payload,
)


class FakeScriptLayoutDraftSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.room = {
            "id": "47000002",
            "is_live": False,
            "_assetgraph_read_environment": "working",
            "topics": [
                {
                    "id": 1,
                    "clips": [
                        {"id": 416425, "name": "未命名", "order_num": 0, "clip_materials": []},
                    ],
                }
            ],
        }
        self.next_clip_id = 416426
        self.layers_by_clip: dict[int, list[dict]] = {}
        self.scripts_by_clip: dict[int, str] = {}

    def read_live_room(self, live_room_id: str) -> dict:
        self.calls.append(("read_live_room", live_room_id))
        return self.room

    def rename_clip(self, clip_id: int, name: str) -> dict:
        self.calls.append(("rename_clip", {"clip_id": clip_id, "name": name}))
        for clip in self.room["topics"][0]["clips"]:
            if clip["id"] == clip_id:
                clip["name"] = name
                return {"clip_id": clip_id, "name": name}
        raise AssertionError(f"clip not found: {clip_id}")

    def create_scene(self, *, live_room_id: str, scene_name: str, scene_index: int) -> dict:
        self.calls.append(("create_scene", {"live_room_id": live_room_id, "scene_name": scene_name, "scene_index": scene_index}))
        clip = {"id": self.next_clip_id, "name": scene_name, "order_num": scene_index, "clip_materials": []}
        self.next_clip_id += 1
        self.room["topics"][0]["clips"].append(clip)
        return {"clip_id": clip["id"], "name": scene_name}

    def insert_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict) -> dict:
        self.calls.append(("insert_asset_layer", {"clip_id": clip_id, "asset_code": operation.get("asset_code")}))
        self.layers_by_clip.setdefault(clip_id, []).append(dict(operation))
        return {"clip_id": clip_id, "asset_code": operation.get("asset_code"), "layer_id": operation.get("layer_id")}

    def position_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict) -> dict:
        self.calls.append(("position_asset_layer", {"clip_id": clip_id, "layer_id": operation.get("layer_id")}))
        return {"clip_id": clip_id, "layer_id": operation.get("layer_id"), "x": operation.get("x"), "y": operation.get("y")}

    def write_script(self, *, live_room_id: str, clip_id: int, scene_name: str, script_text: str) -> dict:
        self.calls.append(("write_script", {"clip_id": clip_id, "scene_name": scene_name, "script_text": script_text}))
        self.scripts_by_clip[clip_id] = script_text
        return {"clip_id": clip_id, "script_length": len(script_text)}

    def verify_scene(self, *, live_room_id: str, clip_id: int, scene_name: str, operation: dict) -> dict:
        self.calls.append(("verify_scene", {"clip_id": clip_id, "scene_name": scene_name}))
        return {
            "clip_id": clip_id,
            "scene_name": scene_name,
            "visual_count": len(self.layers_by_clip.get(clip_id, [])),
            "script_present": bool(self.scripts_by_clip.get(clip_id)),
        }


def content_build_plan() -> dict:
    return {
        "source": "script_content_layout_build_plan_rule_v1",
        "status": "draft_with_placeholders",
        "target_live_room_id": "47000002",
        "build_mode": "draft_with_placeholders",
        "can_execute": False,
        "manual_review_required": True,
        "operation_count": 13,
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "operation_name": "内容驱动搭建计划预检",
                "sort_order": 1,
                "status": "ready",
                "target_live_room_id": "47000002",
            },
            {
                "operation_type": "fill_default_scene",
                "operation_name": "填充默认第1场景：开场",
                "sort_order": 10,
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
                "target_live_room_id": "47000002",
            },
            {
                "operation_type": "insert_asset_layer",
                "operation_name": "插入背景",
                "sort_order": 20,
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
                "layer_id": "scene-00-background_image",
                "layer_type": "background_image",
                "asset_code": "AG-IMG-BG",
                "asset_display_code": "MT-BG-HELANS",
                "x": 0,
                "y": 0,
                "width": 1080,
                "height": 1920,
                "z_index": 1,
            },
            {
                "operation_type": "position_asset_layer",
                "operation_name": "定位背景",
                "sort_order": 30,
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
                "sort_order": 40,
                "status": "manual_required",
                "scene_index": 0,
                "scene_name": "开场",
                "layer_id": "scene-00-product_image",
                "layer_type": "product_image",
                "need_type": "product_image",
                "asset_code": None,
                "blocks_execution": True,
            },
            {
                "operation_type": "write_script",
                "operation_name": "写入脚本：开场",
                "sort_order": 50,
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
                "script_text": "欢迎来到张裕直播间。",
            },
            {
                "operation_type": "verify_scene",
                "operation_name": "回读验证场景：开场",
                "sort_order": 60,
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
            },
            {
                "operation_type": "create_scene",
                "operation_name": "新建场景：促单",
                "sort_order": 70,
                "status": "ready",
                "scene_index": 1,
                "scene_name": "促单",
                "target_live_room_id": "47000002",
            },
            {
                "operation_type": "insert_asset_layer",
                "operation_name": "插入数字人",
                "sort_order": 80,
                "status": "ready",
                "scene_index": 1,
                "scene_name": "促单",
                "layer_id": "scene-01-digital_human",
                "layer_type": "digital_human",
                "asset_code": "AG-VID-HOST",
                "asset_display_code": "DH-HOST",
                "x": 160,
                "y": 520,
                "width": 760,
                "height": 1300,
                "z_index": 3,
            },
            {
                "operation_type": "position_asset_layer",
                "operation_name": "定位数字人",
                "sort_order": 90,
                "status": "ready",
                "scene_index": 1,
                "scene_name": "促单",
                "layer_id": "scene-01-digital_human",
                "layer_type": "digital_human",
                "asset_code": "AG-VID-HOST",
                "x": 160,
                "y": 520,
                "width": 760,
                "height": 1300,
                "z_index": 3,
            },
            {
                "operation_type": "write_script",
                "operation_name": "写入脚本：促单",
                "sort_order": 100,
                "status": "ready",
                "scene_index": 1,
                "scene_name": "促单",
                "script_text": "现在下单有组合优惠。",
            },
            {
                "operation_type": "verify_scene",
                "operation_name": "回读验证场景：促单",
                "sort_order": 110,
                "status": "ready",
                "scene_index": 1,
                "scene_name": "促单",
            },
            {
                "operation_type": "save_draft",
                "operation_name": "保存直播间草稿",
                "sort_order": 9999,
                "status": "manual_review",
                "target_live_room_id": "47000002",
            },
        ],
    }


def test_script_layout_draft_runner_executes_ready_ops_and_skips_placeholders() -> None:
    session = FakeScriptLayoutDraftSession()

    result = ScriptLayoutDraftRunner(session=session).run(content_build_plan())

    assert result.status == "completed_with_manual_review"
    assert result.ready_for_go_live is False
    assert result.target_live_room_id == "47000002"
    assert result.executed_action_count == 11
    assert result.placeholder_count == 1
    assert result.manual_review_required is True
    assert result.failure_count == 0
    assert ("rename_clip", {"clip_id": 416425, "name": "开场"}) in session.calls
    assert any(call == ("create_scene", {"live_room_id": "47000002", "scene_name": "促单", "scene_index": 1}) for call in session.calls)
    assert ("insert_asset_layer", {"clip_id": 416425, "asset_code": "AG-IMG-BG"}) in session.calls
    assert ("insert_asset_layer", {"clip_id": 416426, "asset_code": "AG-VID-HOST"}) in session.calls
    assert not any(call[0] == "save_draft" for call in session.calls)
    placeholder = next(action for action in result.actions if action.operation_type == "placeholder_required")
    assert placeholder.status == "skipped"
    assert placeholder.action_type == "manual_required_placeholder"
    assert placeholder.details and placeholder.details["blocks_execution"] is True
    save = result.actions[-1]
    assert save.operation_type == "save_draft"
    assert save.status == "skipped"
    assert save.action_type == "manual_review_save_not_clicked"


def test_script_layout_draft_runner_blocks_strict_blocked_plan_without_browser_calls() -> None:
    session = FakeScriptLayoutDraftSession()
    plan = {
        "source": "script_content_layout_build_plan_rule_v1",
        "status": "blocked_missing_required_assets",
        "target_live_room_id": "47000002",
        "operations": [],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "blocked"
    assert result.failure_count == 0
    assert result.executed_action_count == 0
    assert result.actions == []
    assert session.calls == []


def test_script_layout_draft_runner_stops_after_first_failed_operation() -> None:
    class FailingRenameSession(FakeScriptLayoutDraftSession):
        def rename_clip(self, clip_id: int, name: str) -> dict:
            self.calls.append(("rename_clip", {"clip_id": clip_id, "name": name}))
            raise RuntimeError("rename failed after an uncertain remote response")

    session = FailingRenameSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
            {
                "operation_type": "fill_default_scene",
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
            },
            {
                "operation_type": "create_scene",
                "status": "ready",
                "scene_index": 1,
                "scene_name": "不得执行",
            },
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert result.failure_count == 1
    assert [action.operation_type for action in result.actions] == [
        "preflight_content_build_plan",
        "fill_default_scene",
    ]
    assert not any(call[0] == "create_scene" for call in session.calls)


def test_script_layout_draft_runner_requires_ready_preflight_as_first_operation() -> None:
    session = FakeScriptLayoutDraftSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {
                "operation_type": "fill_default_scene",
                "status": "ready",
                "scene_index": 0,
                "scene_name": "不得执行",
            },
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert result.failure_count == 1
    assert "first operation" in result.summary
    assert session.calls == []


def test_script_layout_draft_runner_rejects_non_ready_mutation_status() -> None:
    session = FakeScriptLayoutDraftSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
            {
                "operation_type": "fill_default_scene",
                "status": "manual_review",
                "scene_index": 0,
                "scene_name": "不得执行",
            },
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert result.failure_count == 1
    assert "status must be ready" in result.actions[-1].summary
    assert not any(call[0] == "rename_clip" for call in session.calls)


def test_script_layout_draft_runner_requires_authoritative_working_environment() -> None:
    session = FakeScriptLayoutDraftSession()
    session.room.pop("_assetgraph_read_environment")
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
            {
                "operation_type": "fill_default_scene",
                "status": "ready",
                "scene_index": 0,
                "scene_name": "不得执行",
            },
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert "working/draft" in result.actions[0].summary
    assert not any(call[0] == "rename_clip" for call in session.calls)


def test_script_layout_draft_runner_rejects_target_room_override_mismatch_before_session_calls() -> None:
    session = FakeScriptLayoutDraftSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan, target_live_room_id="47000099")

    assert result.status == "failed"
    assert result.failure_count == 1
    assert result.manual_review_required is True
    assert "does not match" in result.summary
    assert session.calls == []


def test_script_layout_draft_runner_clears_room_cache_between_runs() -> None:
    session = FakeScriptLayoutDraftSession()
    runner = ScriptLayoutDraftRunner(session=session)
    first_plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "status": "ready",
                "target_live_room_id": "47000002",
            }
        ],
    }

    first_result = runner.run(first_plan)
    session.room["id"] = "47000003"
    second_plan = {
        "status": "ready",
        "target_live_room_id": "47000003",
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "status": "ready",
                "target_live_room_id": "47000003",
            }
        ],
    }
    second_result = runner.run(second_plan)

    assert first_result.status == "completed"
    assert second_result.status == "completed"
    assert [call for call in session.calls if call[0] == "read_live_room"] == [
        ("read_live_room", "47000002"),
        ("read_live_room", "47000003"),
    ]


def test_script_layout_draft_runner_rejects_authoritative_room_id_mismatch() -> None:
    class WrongRoomSession(FakeScriptLayoutDraftSession):
        def read_live_room(self, live_room_id: str) -> dict:
            self.calls.append(("read_live_room", live_room_id))
            return {
                "id": "47000999",
                "topics": [{"clips": [{"id": 1, "name": "未命名", "order_num": 0}]}],
            }

    session = WrongRoomSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
            {
                "operation_type": "create_scene",
                "status": "ready",
                "scene_index": 1,
                "scene_name": "不得执行",
            },
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert result.failure_count == 1
    assert "room id" in result.actions[0].summary.lower()
    assert not any(call[0] == "create_scene" for call in session.calls)


def test_script_layout_draft_runner_rejects_active_live_room_before_mutation() -> None:
    class ActiveLiveRoomSession(FakeScriptLayoutDraftSession):
        def read_live_room(self, live_room_id: str) -> dict:
            room = super().read_live_room(live_room_id)
            return {**room, "status": "live"}

    session = ActiveLiveRoomSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
            {
                "operation_type": "fill_default_scene",
                "status": "ready",
                "scene_index": 0,
                "scene_name": "不得执行",
            },
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert result.failure_count == 1
    assert "currently live" in result.actions[0].summary.lower()
    assert not any(call[0] == "rename_clip" for call in session.calls)


@pytest.mark.parametrize("room_status", [None, "mystery"])
def test_script_layout_draft_runner_requires_explicit_not_live_evidence(room_status: str | None) -> None:
    session = FakeScriptLayoutDraftSession()
    session.room.pop("is_live")
    if room_status is not None:
        session.room["status"] = room_status
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "status": "ready",
                "target_live_room_id": "47000002",
            }
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert "not live" in result.summary.lower()
    assert session.calls == [("read_live_room", "47000002")]


def test_script_layout_draft_runner_rejects_unknown_late_operation_before_any_session_call() -> None:
    session = FakeScriptLayoutDraftSession()
    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "status": "ready",
                "target_live_room_id": "47000002",
            },
            {
                "operation_type": "fill_default_scene",
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
            },
            {"operation_type": "unexpected_future_operation", "status": "ready"},
        ],
    }

    result = ScriptLayoutDraftRunner(session=session).run(plan)

    assert result.status == "failed"
    assert "unsupported" in result.summary.lower()
    assert session.calls == []


def test_script_layout_draft_execution_payload_preserves_manual_gate() -> None:
    result = ScriptLayoutDraftRunner(session=FakeScriptLayoutDraftSession()).run(content_build_plan())

    payload = build_script_layout_draft_execution_payload(result)

    assert payload["executor"] == "browser_use"
    assert payload["execution_status"] == "completed_with_manual_review"
    assert payload["mode"] == "script_layout_draft"
    assert payload["ready_for_go_live"] is False
    assert payload["operation_results"][1]["operation_type"] == "fill_default_scene"
    assert payload["operation_results"][1]["status"] == "completed"
    assert payload["operation_results"][4]["operation_type"] == "placeholder_required"
    assert payload["operation_results"][4]["status"] == "skipped"
    assert payload["operation_results"][-1]["action_type"] == "manual_review_save_not_clicked"


def test_script_layout_draft_runner_skips_ready_asset_when_maitu_binding_is_missing() -> None:
    class MissingBindingSession(FakeScriptLayoutDraftSession):
        def insert_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict) -> dict:
            self.calls.append(("insert_asset_layer", {"clip_id": clip_id, "asset_code": operation.get("asset_code")}))
            return {"status": "manual_required", "reason": "missing_maitu_material_binding", "asset_code": operation.get("asset_code")}

        def position_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict) -> dict:
            self.calls.append(("position_asset_layer", {"clip_id": clip_id, "layer_id": operation.get("layer_id")}))
            return {"status": "manual_required", "reason": "target_material_not_found", "layer_id": operation.get("layer_id")}

    result = ScriptLayoutDraftRunner(session=MissingBindingSession()).run(content_build_plan())

    insert_action = next(action for action in result.actions if action.operation_type == "insert_asset_layer")
    position_action = next(action for action in result.actions if action.operation_type == "position_asset_layer")
    assert insert_action.status == "skipped"
    assert insert_action.action_type == "manual_required_asset_binding"
    assert position_action.status == "skipped"
    assert position_action.action_type == "manual_required_position_binding"
    assert result.ready_for_go_live is False


def test_script_layout_draft_skipped_binding_marks_result_manual_review() -> None:
    class MissingBindingSession(FakeScriptLayoutDraftSession):
        def insert_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict) -> dict:
            return {"status": "manual_required", "reason": "missing_maitu_material_binding"}

    plan = {
        "status": "ready",
        "target_live_room_id": "47000002",
        "manual_review_required": False,
        "operations": [
            {"operation_type": "preflight_content_build_plan", "status": "ready"},
            {"operation_type": "fill_default_scene", "status": "ready", "scene_index": 0, "scene_name": "开场"},
            {
                "operation_type": "insert_asset_layer",
                "status": "ready",
                "scene_index": 0,
                "scene_name": "开场",
                "asset_code": "AG-IMG-MISSING",
            },
        ],
    }

    result = ScriptLayoutDraftRunner(session=MissingBindingSession()).run(plan)

    assert result.status == "completed_with_manual_review"
    assert result.manual_review_required is True
    assert result.actions[-1].status == "skipped"
