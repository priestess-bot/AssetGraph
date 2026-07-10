from __future__ import annotations

from typing import Any

SOURCE = "script_content_layout_build_plan_rule_v1"


class ScriptLayoutBuildPlanBuilder:
    """Convert content-driven layout plans into safe worker-oriented BuildPlan operations."""

    def build(self, layout_plan: dict[str, Any], *, target_live_room_id: str | None = None) -> dict[str, Any]:
        build_mode = str(layout_plan.get("build_mode") or "strict")
        status = str(layout_plan.get("status") or "draft")
        blocked_reasons: list[str] = []
        if status == "blocked_missing_required_assets" or layout_plan.get("can_generate_layout") is False:
            blocked_reasons.append("layout_plan_blocked")
            if int(layout_plan.get("blocking_gap_count") or 0) > 0:
                blocked_reasons.append("missing_required_assets")
            return {
                "source": SOURCE,
                "status": "blocked_missing_required_assets",
                "target_live_room_id": target_live_room_id,
                "build_mode": build_mode,
                "can_execute": False,
                "manual_review_required": True,
                "blocked_reasons": self._dedupe(blocked_reasons),
                "operation_count": 0,
                "operations": [],
            }

        operations = self._operations_for_layout(layout_plan, target_live_room_id=target_live_room_id)
        has_manual_operation = any(operation.get("status") in {"manual_required", "manual_review"} for operation in operations)
        can_execute = bool(layout_plan.get("can_generate_executable_build_plan")) and not has_manual_operation
        result_status = "ready" if can_execute else str(layout_plan.get("status") or "manual_review_required")
        return {
            "source": SOURCE,
            "status": result_status,
            "target_live_room_id": target_live_room_id,
            "build_mode": build_mode,
            "can_execute": can_execute,
            "manual_review_required": has_manual_operation or bool(layout_plan.get("manual_review_required")),
            "blocked_reasons": [],
            "operation_count": len(operations),
            "operations": operations,
        }

    def _operations_for_layout(self, layout_plan: dict[str, Any], *, target_live_room_id: str | None) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        sort_order = 1
        operations.append(
            {
                "operation_type": "preflight_content_build_plan",
                "operation_name": "内容驱动搭建计划预检",
                "sort_order": sort_order,
                "status": "ready",
                "target_live_room_id": target_live_room_id,
                "instruction": "确认当前麦兔页面、直播间草稿、默认第1场景和禁开播安全边界；不点击正式开播。",
            }
        )
        sort_order += 10
        for scene in sorted(layout_plan.get("scenes") or [], key=lambda item: int(item.get("scene_index") or 0)):
            scene_index = int(scene.get("scene_index") or 0)
            if scene_index == 0:
                operations.append(
                    {
                        "operation_type": "fill_default_scene",
                        "operation_name": f"填充默认第1场景：{scene.get('scene_name')}",
                        "sort_order": sort_order,
                        "status": "ready",
                        "scene_index": scene_index,
                        "scene_name": scene.get("scene_name"),
                        "target_live_room_id": target_live_room_id,
                        "instruction": "新建直播间自带第1场景，直接重命名并填充该默认场景，不新建第1场景。",
                    }
                )
            else:
                operations.append(
                    {
                        "operation_type": "create_scene",
                        "operation_name": f"新建场景：{scene.get('scene_name')}",
                        "sort_order": sort_order,
                        "status": "ready",
                        "scene_index": scene_index,
                        "scene_name": scene.get("scene_name"),
                        "target_live_room_id": target_live_room_id,
                        "instruction": "从第2个计划场景开始新建麦兔场景，并在创建后回读场景列表确认。",
                    }
                )
            sort_order += 10
            for layer in scene.get("layers") or []:
                if layer.get("status") == "placeholder_required":
                    operations.append(self._placeholder_operation(scene, layer, sort_order=sort_order))
                    sort_order += 10
                    continue
                operations.append(self._insert_operation(scene, layer, sort_order=sort_order))
                sort_order += 10
                operations.append(self._position_operation(scene, layer, sort_order=sort_order))
                sort_order += 10
            script_block = scene.get("script_block") or {}
            operations.append(
                {
                    "operation_type": "write_script",
                    "operation_name": f"写入脚本：{scene.get('scene_name')}",
                    "sort_order": sort_order,
                    "status": "ready" if script_block.get("text") else "manual_required",
                    "scene_index": scene_index,
                    "scene_name": scene.get("scene_name"),
                    "script_text": script_block.get("text") or "",
                    "instruction": "在当前场景直播脚本区域写入对应剧本文案，写入后重新 Observe 验证。",
                }
            )
            sort_order += 10
            operations.append(
                {
                    "operation_type": "verify_scene",
                    "operation_name": f"回读验证场景：{scene.get('scene_name')}",
                    "sort_order": sort_order,
                    "status": "ready",
                    "scene_index": scene_index,
                    "scene_name": scene.get("scene_name"),
                    "instruction": "回读场景图层、坐标、素材编号和脚本文案；只保存验证证据，不开播。",
                }
            )
            sort_order += 10
        manual_review = bool(layout_plan.get("manual_review_required")) or any(
            operation.get("status") == "manual_required" for operation in operations
        )
        operations.append(
            {
                "operation_type": "save_draft",
                "operation_name": "保存直播间草稿",
                "sort_order": 9999,
                "status": "manual_review" if manual_review else "ready",
                "target_live_room_id": target_live_room_id,
                "instruction": "仅保存草稿；存在占位/缺口时必须人工复核，不点击正式开播。",
            }
        )
        return operations

    @staticmethod
    def _insert_operation(scene: dict[str, Any], layer: dict[str, Any], *, sort_order: int) -> dict[str, Any]:
        return {
            "operation_type": "insert_asset_layer",
            "operation_name": f"插入素材图层：{layer.get('layer_type')}",
            "sort_order": sort_order,
            "status": "ready",
            "scene_index": scene.get("scene_index"),
            "scene_name": scene.get("scene_name"),
            "layer_id": layer.get("layer_id"),
            "layer_type": layer.get("layer_type"),
            "need_type": layer.get("need_type"),
            "asset_code": layer.get("asset_code"),
            "asset_display_code": layer.get("asset_display_code"),
            "asset_local_file_code": layer.get("asset_local_file_code"),
            "asset_original_filename": layer.get("asset_original_filename"),
            "asset_local_relative_path": layer.get("asset_local_relative_path"),
            "asset_browser_use_hint": layer.get("asset_browser_use_hint"),
            "material_id": layer.get("maitu_material_id"),
            "source_material_type": layer.get("source_material_type"),
            "source_material_url": layer.get("source_material_url"),
            "source_cover_url": layer.get("source_cover_url"),
            "speaker_id": layer.get("speaker_id"),
            "digital_human_image_id": layer.get("digital_human_image_id"),
            "x": layer.get("x"),
            "y": layer.get("y"),
            "width": layer.get("width"),
            "height": layer.get("height"),
            "z_index": layer.get("z_index"),
            "instruction": f"按素材编号 {layer.get('asset_code')} 插入 {layer.get('layer_type')} 图层。",
        }

    @staticmethod
    def _position_operation(scene: dict[str, Any], layer: dict[str, Any], *, sort_order: int) -> dict[str, Any]:
        return {
            "operation_type": "position_asset_layer",
            "operation_name": f"定位素材图层：{layer.get('layer_type')}",
            "sort_order": sort_order,
            "status": "ready",
            "scene_index": scene.get("scene_index"),
            "scene_name": scene.get("scene_name"),
            "layer_id": layer.get("layer_id"),
            "layer_type": layer.get("layer_type"),
            "asset_code": layer.get("asset_code"),
            "x": layer.get("x"),
            "y": layer.get("y"),
            "width": layer.get("width"),
            "height": layer.get("height"),
            "z_index": layer.get("z_index"),
            "instruction": "按布局计划设置图层坐标、尺寸和层级，执行后回读坐标验证。",
        }

    @staticmethod
    def _placeholder_operation(scene: dict[str, Any], layer: dict[str, Any], *, sort_order: int) -> dict[str, Any]:
        return {
            "operation_type": "placeholder_required",
            "operation_name": f"缺失素材占位：{layer.get('layer_type')}",
            "sort_order": sort_order,
            "status": "manual_required",
            "scene_index": scene.get("scene_index"),
            "scene_name": scene.get("scene_name"),
            "layer_id": layer.get("layer_id"),
            "layer_type": layer.get("layer_type"),
            "need_type": layer.get("need_type"),
            "required_category": layer.get("required_category"),
            "asset_code": None,
            "x": layer.get("x"),
            "y": layer.get("y"),
            "width": layer.get("width"),
            "height": layer.get("height"),
            "z_index": layer.get("z_index"),
            "blocks_execution": True,
            "instruction": "该图层缺少匹配素材，只生成占位记录；必须补充素材或人工确认后才能执行真实插入。",
        }

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result
