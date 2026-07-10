from __future__ import annotations

from browser_use_worker.live_scene_fill import LiveSceneFillRunner, build_live_scene_fill_execution_payload


class FakeLiveSceneFillSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.room = {
            "id": 40173,
            "name": "龙谕龙8单场景测试",
            "topics": [
                {
                    "id": 271879,
                    "clips": [
                        {"id": 416425, "name": "未命名", "order_num": 0, "clip_materials": []},
                        {"id": 416426, "name": "错误多余场景", "order_num": 1, "clip_materials": []},
                    ],
                }
            ],
        }

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

    def create_scene_from_template(self, *args, **kwargs) -> dict:  # pragma: no cover - should never be called in this test
        raise AssertionError("first planned scene must use the default clip, not create a new clip")

    def fill_clip_from_template(
        self,
        *,
        live_room_id: str,
        target_clip_id: int,
        reference_room_id: str,
        reference_clip_id: str,
        scene_name: str,
        component_operations: list[dict],
        script_content: str | None,
    ) -> dict:
        self.calls.append(
            (
                "fill_clip_from_template",
                {
                    "live_room_id": live_room_id,
                    "target_clip_id": target_clip_id,
                    "reference_room_id": reference_room_id,
                    "reference_clip_id": reference_clip_id,
                    "scene_name": scene_name,
                    "component_count": len(component_operations),
                    "script_content": script_content,
                },
            )
        )
        return {
            "live_room_id": live_room_id,
            "target_clip_id": target_clip_id,
            "reference_clip_id": reference_clip_id,
            "visual_count": len(component_operations),
            "text_count": 1 if script_content else 0,
            "layer_names": [operation["layer_name"] for operation in component_operations],
        }


def single_scene_build_plan() -> dict:
    return {
        "build_plan_code": "MT-BUILD-20260710-000001",
        "blueprint_code": "MT-BP-20260709-38336-TEMPLATE",
        "reference_room_id": "38336",
        "reference_room_name": "张裕夏日主题",
        "operations": [
            {
                "operation_type": "preflight_scene_build_plan",
                "operation_name": "只读预检单场景搭建计划",
                "sort_order": 1,
                "status": "ready",
                "details": {"safety_gate": True},
            },
            {
                "operation_type": "create_scene_from_template",
                "operation_name": "按模板创建单场景 商品01-场景01",
                "sort_order": 10,
                "scene_name": "商品01-场景01",
                "details": {"reference_clip_id": "390051", "scene_template_code": "MT-TPL-SCENE-38336-001"},
            },
            {
                "operation_type": "insert_template_component",
                "operation_name": "插入模板组件 背景",
                "sort_order": 20,
                "scene_name": "商品01-场景01",
                "layer_name": "背景",
                "details": {"component_template_code": "MT-TPL-LAYER-38336-001-01", "material_id": 40131},
            },
            {
                "operation_type": "insert_template_component",
                "operation_name": "插入模板组件 标题+logo",
                "sort_order": 30,
                "scene_name": "商品01-场景01",
                "layer_name": "标题+logo",
                "details": {"component_template_code": "MT-TPL-LAYER-38336-001-02", "material_id": 40101},
            },
            {
                "operation_type": "add_script_block",
                "operation_name": "写入脚本 商品01-场景01",
                "sort_order": 900,
                "scene_name": "商品01-场景01",
                "script_block_content": "今天我们讲龙谕龙8。",
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


def test_live_scene_fill_uses_default_clip_for_first_planned_scene() -> None:
    session = FakeLiveSceneFillSession()

    result = LiveSceneFillRunner(session=session).run(single_scene_build_plan(), target_live_room_id="40173")

    assert result.status == "completed"
    assert result.target_clip_id == 416425
    assert result.target_scene_name == "商品01-场景01"
    assert result.visual_count == 2
    assert result.text_count == 1
    assert ("rename_clip", {"clip_id": 416425, "name": "商品01-场景01"}) in session.calls
    assert any(
        call == (
            "fill_clip_from_template",
            {
                "live_room_id": "40173",
                "target_clip_id": 416425,
                "reference_room_id": "38336",
                "reference_clip_id": "390051",
                "scene_name": "商品01-场景01",
                "component_count": 2,
                "script_content": "今天我们讲龙谕龙8。",
            },
        )
        for call in session.calls
    )
    assert all(call[0] != "create_scene_from_template" for call in session.calls)
    assert result.actions[1].action_type == "map_first_planned_scene_to_default_clip"
    assert result.actions[-1].action_type == "manual_review_save_not_clicked"


def test_live_scene_fill_execution_payload_records_completed_components_and_manual_save_skip() -> None:
    result = LiveSceneFillRunner(session=FakeLiveSceneFillSession()).run(single_scene_build_plan(), target_live_room_id="40173")

    payload = build_live_scene_fill_execution_payload(result)

    assert payload["executor"] == "browser_use"
    assert payload["execution_status"] == "completed"
    assert payload["mode"] == "live_scene_fill"
    assert payload["operation_results"][1]["operation_type"] == "create_scene_from_template"
    assert payload["operation_results"][1]["status"] == "completed"
    assert payload["operation_results"][1]["details"]["target_clip_id"] == 416425
    component_results = [
        row for row in payload["operation_results"] if row["operation_type"] == "insert_template_component"
    ]
    assert [row["layer_name"] for row in component_results] == ["背景", "标题+logo"]
    assert all(row["status"] == "completed" for row in component_results)
    assert payload["operation_results"][-1]["operation_type"] == "save_live_room"
    assert payload["operation_results"][-1]["status"] == "skipped"
    assert payload["operation_results"][-1]["details"]["go_live_clicked"] is False
