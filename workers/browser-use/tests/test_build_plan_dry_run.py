from __future__ import annotations

from browser_use_worker.build_plan_dry_run import BuildPlanDryRun


def build_plan() -> dict:
    return {
        "build_plan_code": "MT-BUILD-20260709-000001",
        "blueprint_code": "MT-BP-20260709-39826",
        "reference_room_id": "39826",
        "reference_room_name": "京东空白直播间-0707-1352",
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


def test_build_plan_dry_run_renders_safe_operation_summary_without_browser_actions() -> None:
    result = BuildPlanDryRun().run(build_plan())

    assert result.status == "dry_run"
    assert result.build_plan_code == "MT-BUILD-20260709-000001"
    assert result.operation_count == 5
    assert result.planned_mutation_count == 2
    assert result.manual_review_count == 1
    assert result.safety_violation_count == 0
    assert result.ready_to_execute is False
    assert result.operations[0].safe_action == "read_only_preflight"
    assert result.operations[1].safe_action == "read_only_select_scene"
    assert result.operations[2].safe_action == "planned_layer_asset_replacement_not_executed"
    assert result.operations[2].scene_name == "场景01"
    assert result.operations[2].layer_name == "商品图"
    assert result.operations[3].safe_action == "planned_script_block_not_executed"
    assert result.operations[3].script_preview == "大家好，今天介绍品酒大师PRO。"
    assert result.operations[4].safe_action == "manual_review_save_not_executed"
    assert "would render 5" in result.summary


def test_build_plan_dry_run_flags_unsafe_go_live_instruction() -> None:
    plan = build_plan()
    plan["operations"][-1]["status"] = "ready"
    plan["operations"][-1]["instruction"] = "保存后点击正式开播。"

    result = BuildPlanDryRun().run(plan)

    assert result.status == "failed"
    assert result.ready_to_execute is False
    assert result.safety_violation_count == 2
    assert result.operations[-1].safety_notes == [
        "save_live_room must remain manual_review in dry-run/build phases.",
        "Operation instruction appears to start live streaming.",
    ]
