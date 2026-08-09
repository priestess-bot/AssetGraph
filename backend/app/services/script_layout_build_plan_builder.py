from __future__ import annotations

from typing import Any

from app.services.audio_plan import AudioPlanError, AudioPlanValidator
from app.services.layer_stacking import compile_layer_stack

SOURCE = "script_content_layout_build_plan_rule_v1"
PROTECTED_REFERENCE_ROOM_IDS = ("38336", "38995")


class ScriptLayoutBuildPlanBuilder:
    """Convert content-driven layout plans into safe worker-oriented BuildPlan operations."""

    def build(
        self,
        layout_plan: dict[str, Any],
        *,
        target_live_room_id: str | None = None,
        expected_title: str | None = None,
    ) -> dict[str, Any]:
        build_mode = str(layout_plan.get("build_mode") or "strict")
        status = str(layout_plan.get("status") or "draft")
        normalized_expected_title = str(expected_title or "").strip() or None
        blocked_reasons: list[str] = []
        if status == "blocked_missing_required_assets" or layout_plan.get("can_generate_layout") is False:
            blocked_reasons.append("layout_plan_blocked")
            if int(layout_plan.get("blocking_gap_count") or 0) > 0:
                blocked_reasons.append("missing_required_assets")
            return {
                "source": SOURCE,
                "status": "blocked_missing_required_assets",
                "target_live_room_id": target_live_room_id,
                "expected_title": normalized_expected_title,
                "build_mode": build_mode,
                "can_execute": False,
                "manual_review_required": True,
                "blocked_reasons": self._dedupe(blocked_reasons),
                "operation_count": 0,
                "operations": [],
            }

        try:
            normalized_layout = dict(layout_plan)
            normalized_layout["scenes"] = AudioPlanValidator().normalize_scenes(list(layout_plan.get("scenes") or []))
        except AudioPlanError as exc:
            return {
                "source": SOURCE,
                "status": "blocked_audio_policy",
                "target_live_room_id": target_live_room_id,
                "expected_title": normalized_expected_title,
                "build_mode": build_mode,
                "can_execute": False,
                "manual_review_required": True,
                "blocked_reasons": ["audio_policy_violation", str(exc)],
                "operation_count": 0,
                "operations": [],
            }

        stacking_failures: list[str] = []
        for scene in normalized_layout["scenes"]:
            if not isinstance(scene, dict):
                stacking_failures.append("layer_stack_scene_invalid")
                continue
            layers = scene.get("layers")
            if not isinstance(layers, list):
                stacking_failures.append(f"layer_stack_missing:{scene.get('scene_name') or 'unknown'}")
                continue
            stacking_failures.extend(str(reason) for reason in scene.get("stacking_failures") or [])
            stacking_failures.extend(compile_layer_stack(layers))
        stacking_failures = list(dict.fromkeys(stacking_failures))
        if stacking_failures:
            return {
                "source": SOURCE,
                "status": "blocked_layer_constraints",
                "target_live_room_id": target_live_room_id,
                "expected_title": normalized_expected_title,
                "build_mode": build_mode,
                "can_execute": False,
                "manual_review_required": True,
                "blocked_reasons": stacking_failures,
                "operation_count": 0,
                "operations": [],
            }

        operations = self._operations_for_layout(
            normalized_layout,
            target_live_room_id=target_live_room_id,
            expected_title=normalized_expected_title,
        )
        has_manual_operation = any(operation.get("status") in {"manual_required", "manual_review"} for operation in operations)
        can_execute = bool(layout_plan.get("can_generate_executable_build_plan")) and not has_manual_operation
        result_status = "ready" if can_execute else str(layout_plan.get("status") or "manual_review_required")
        return {
            "source": SOURCE,
            "status": result_status,
            "target_live_room_id": target_live_room_id,
            "expected_title": normalized_expected_title,
            "build_mode": build_mode,
            "can_execute": can_execute,
            "manual_review_required": has_manual_operation or bool(layout_plan.get("manual_review_required")),
            "blocked_reasons": [],
            "operation_count": len(operations),
            "operations": operations,
        }

    def _operations_for_layout(
        self,
        layout_plan: dict[str, Any],
        *,
        target_live_room_id: str | None,
        expected_title: str | None,
    ) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        sort_order = 1
        operations.append(
            {
                "operation_type": "preflight_content_build_plan",
                "operation_name": "内容驱动搭建计划预检",
                "sort_order": sort_order,
                "status": "ready",
                "target_live_room_id": target_live_room_id,
                "expected_live_room_title": expected_title,
                "require_fresh_blank_room": True,
                "protected_reference_room_ids": list(PROTECTED_REFERENCE_ROOM_IDS),
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
        scene_names = [
            str(scene.get("scene_name") or "").strip()
            for scene in sorted(
                layout_plan.get("scenes") or [],
                key=lambda item: int(item.get("scene_index") or 0),
            )
        ]
        operations.append(
            {
                "operation_type": "save_draft" if manual_review else "verify_draft_persisted",
                "operation_name": "人工复核并保存直播间草稿" if manual_review else "确认直播间草稿已自动保存",
                "sort_order": 9999,
                "status": "manual_review" if manual_review else "ready",
                "target_live_room_id": target_live_room_id,
                "expected_scene_names": scene_names,
                "instruction": (
                    "存在占位或缺口，人工复核后仅保存草稿，不点击正式开播。"
                    if manual_review
                    else "刷新 working room 并确认全部场景已自动保存；不点击保存；不点击正式开播。"
                ),
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
            "maitu_material_id": layer.get("maitu_material_id"),
            "maitu_source_material_id": layer.get("maitu_source_material_id"),
            "material_id": layer.get("maitu_material_id"),
            "source_material_type": layer.get("source_material_type"),
            "source_material_url": layer.get("source_material_url"),
            "source_cover_url": layer.get("source_cover_url"),
            "speaker_id": layer.get("speaker_id"),
            "digital_human_image_id": layer.get("digital_human_image_id"),
            "sound_enabled": layer.get("sound_enabled") is True,
            "audio_role": layer.get("audio_role") or "muted",
            "audio_classification_status": layer.get("audio_classification_status") or "unknown",
            "audio_class": layer.get("audio_class") or "unknown",
            "audio_start_seconds": layer.get("audio_start_seconds"),
            "audio_end_seconds": layer.get("audio_end_seconds"),
            "x": layer.get("x"),
            "y": layer.get("y"),
            "width": layer.get("width"),
            "height": layer.get("height"),
            "z_index": layer.get("z_index"),
            "fit": layer.get("fit") or "contain",
            "preserve_aspect_ratio": layer.get("preserve_aspect_ratio") is True,
            "rotation": layer.get("rotation", 0.0),
            "loop": layer.get("loop") is True,
            "muted": layer.get("muted") is not False,
            "constraint_rules": list(layer.get("constraint_rules") or []),
            "constraint_evidence": dict(layer.get("constraint_evidence") or {}),
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
            "fit": layer.get("fit") or "contain",
            "preserve_aspect_ratio": layer.get("preserve_aspect_ratio") is True,
            "rotation": layer.get("rotation", 0.0),
            "loop": layer.get("loop") is True,
            "muted": layer.get("muted") is not False,
            "sound_enabled": layer.get("sound_enabled") is True,
            "audio_role": layer.get("audio_role") or "muted",
            "constraint_rules": list(layer.get("constraint_rules") or []),
            "constraint_evidence": dict(layer.get("constraint_evidence") or {}),
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
