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
                "selected_asset_code": "AG-VID-20260709-000052",
                "selected_asset_title": "视频 - 商品讲解视频 - 品酒大师PRO",
                "selected_asset_display_code": "MT-VID-0024",
                "selected_asset_local_file_code": "MT-VID-0024",
                "match_score": 0.94,
                "match_reasons": ["maitu_category matches required_category: product_video", "script context mentions 品酒大师PRO"],
                "instruction": "定位商品图图层，计划替换为 MT-VID-0024（视频 - 商品讲解视频 - 品酒大师PRO；AssetGraph编号 AG-VID-20260709-000052），保持原布局。",
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
    assert result.operations[2].selected_asset_code == "AG-VID-20260709-000052"
    assert result.operations[2].selected_asset_display_code == "MT-VID-0024"
    assert result.operations[2].match_score == 0.94
    assert "script context mentions 品酒大师PRO" in (result.operations[2].match_reasons or [])
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


def scene_build_plan() -> dict:
    return {
        "build_plan_code": "MT-BUILD-20260710-000001",
        "blueprint_code": "MT-BP-20260709-38336-TEMPLATE",
        "operations": [
            {
                "operation_type": "preflight_scene_build_plan",
                "operation_name": "只读预检单场景搭建计划",
                "sort_order": 1,
                "status": "ready",
                "instruction": "预检单场景模板和禁开播规则；此计划为 dry-run，不直接操作麦兔。",
                "details": {"scene_template_code": "MT-TPL-SCENE-38336-001"},
            },
            {
                "operation_type": "create_scene_from_template",
                "operation_name": "按模板创建单场景 商品01-场景01",
                "sort_order": 10,
                "status": "planned",
                "scene_name": "商品01-场景01",
                "instruction": "按模板场景复刻结构；只生成计划，不点击正式开播。",
                "details": {"scene_template_code": "MT-TPL-SCENE-38336-001"},
            },
            {
                "operation_type": "insert_template_component",
                "operation_name": "插入模板组件 背景",
                "sort_order": 20,
                "status": "planned",
                "scene_name": "商品01-场景01",
                "layer_name": "微信图片_20260618221607_11_15",
                "layer_role": "background",
                "required_category": "background_image",
                "accepted_asset_types": ["IMG"],
                "replacement_policy": "keep_layout",
                "instruction": "插入/配置背景组件，保持模板坐标、尺寸和层级。",
                "details": {
                    "scene_template_code": "MT-TPL-SCENE-38336-001",
                    "component_template_code": "MT-TPL-LAYER-38336-001-01",
                    "geometry": {"left": 0, "top": 0, "width": 1080, "height": 1919, "scale": None},
                },
            },
            {
                "operation_type": "add_script_block",
                "operation_name": "写入单场景脚本",
                "sort_order": 30,
                "status": "planned",
                "scene_name": "商品01-场景01",
                "script_block_code": "MT-TPL-SCRIPT-38336-001",
                "script_block_content": "今天我们用张裕夏日主题的结构讲龙谕龙8。",
                "instruction": "写入目标脚本，并回读确认文本一致。",
            },
            {
                "operation_type": "save_live_room",
                "operation_name": "保存单场景直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "scene_name": "商品01-场景01",
                "instruction": "只在组件和脚本回读验证通过后保存草稿；禁止点击正式开播。",
            },
        ],
    }


def test_scene_build_plan_dry_run_renders_template_component_operations_without_browser_actions() -> None:
    result = BuildPlanDryRun().run(scene_build_plan())

    assert result.status == "dry_run"
    assert result.build_plan_code == "MT-BUILD-20260710-000001"
    assert result.operation_count == 5
    assert result.planned_mutation_count == 3
    assert result.manual_review_count == 1
    assert result.safety_violation_count == 0
    assert result.operations[0].safe_action == "read_only_scene_preflight"
    assert result.operations[1].safe_action == "planned_scene_creation_not_executed"
    assert result.operations[2].safe_action == "planned_template_component_insert_not_executed"
    assert result.operations[2].layer_name == "微信图片_20260618221607_11_15"
    assert result.operations[3].safe_action == "planned_script_block_not_executed"
    assert result.operations[4].safe_action == "manual_review_save_not_executed"
