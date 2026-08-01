from __future__ import annotations

from typing import Any

from app.services.layer_stacking import compile_layer_stack
from app.services.script_asset_gap_reporter import ScriptAssetGapReporter

SOURCE = "script_content_layout_plan_rule_v1"

LAYOUT_RULES: dict[str, dict[str, Any]] = {
    "background_image": {"x": 0, "y": 0, "width": 1080, "height": 1920, "z_index": 1, "fit": "cover"},
    "product_video": {"x": 80, "y": 360, "width": 920, "height": 520, "z_index": 2, "fit": "contain"},
    "digital_human": {"x": 160, "y": 520, "width": 760, "height": 1300, "z_index": 3, "fit": "contain"},
    "supporting_visual": {"x": 80, "y": 360, "width": 920, "height": 520, "z_index": 4, "fit": "contain"},
    "product_image": {"x": 720, "y": 980, "width": 280, "height": 280, "z_index": 5, "fit": "contain"},
    "promotion_sticker": {"x": 80, "y": 1240, "width": 420, "height": 180, "z_index": 6, "fit": "contain"},
    "brand_logo_title": {"x": 90, "y": 50, "width": 900, "height": 220, "z_index": 7, "fit": "contain"},
}

DEFAULT_RULE = {"x": 80, "y": 420, "width": 920, "height": 520, "z_index": 8, "fit": "contain"}

ROLE_FOR_NEED = {
    "background_image": "background",
    "product_video": "supporting_video",
    "digital_human": "digital_human",
    "supporting_visual": "decoration_foreground",
    "product_image": "product_display",
    "promotion_sticker": "promotion_text",
    "brand_logo_title": "brand_title",
}


class ScriptLayoutPlanner:
    """Generate content-driven Maitu scene layouts from selected script assets."""

    def plan(
        self,
        scenes: list[dict[str, Any]],
        *,
        build_mode: str = "strict",
        canvas_width: int = 1080,
        canvas_height: int = 1920,
    ) -> dict[str, Any]:
        normalized_mode = build_mode or "strict"
        gap_report = ScriptAssetGapReporter().report(scenes)
        blocking_gap_count = int(gap_report.get("blocking_gap_count") or 0)
        has_blocking_gaps = blocking_gap_count > 0
        if normalized_mode == "strict" and has_blocking_gaps:
            status = "blocked_missing_required_assets"
            can_generate_layout = False
            can_generate_executable_build_plan = False
        elif has_blocking_gaps:
            status = "draft_with_placeholders"
            can_generate_layout = True
            can_generate_executable_build_plan = False
        else:
            status = "ready_for_build_plan"
            can_generate_layout = True
            can_generate_executable_build_plan = True

        layout_scenes = [
            self._plan_scene(
                scene,
                build_mode=normalized_mode,
                overall_status=status,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
            )
            for scene in sorted(scenes, key=lambda item: int(item.get("scene_index") or 0))
        ]
        manual_review_required = any(scene["status"] != "ready" for scene in layout_scenes)
        if status == "ready_for_build_plan" and manual_review_required:
            status = "manual_review_required"
            can_generate_executable_build_plan = False
        return {
            "source": SOURCE,
            "build_mode": normalized_mode,
            "status": status,
            "scene_count": len(layout_scenes),
            "blocking_gap_count": blocking_gap_count,
            "can_generate_layout": can_generate_layout,
            "can_generate_executable_build_plan": can_generate_executable_build_plan,
            "manual_review_required": manual_review_required,
            "scenes": layout_scenes,
        }

    def _plan_scene(
        self,
        scene: dict[str, Any],
        *,
        build_mode: str,
        overall_status: str,
        canvas_width: int,
        canvas_height: int,
    ) -> dict[str, Any]:
        scene_index = int(scene.get("scene_index") or 0)
        duration_seconds = max(1, int(scene.get("duration_seconds") or 1))
        review_reasons = list(scene.get("review_reasons") or [])
        missing_needs = [dict(need) for need in (scene.get("missing_asset_needs") or [])]
        has_missing = bool(missing_needs) or any(
            selection.get("status") == "missing_asset" for selection in (scene.get("asset_selections") or [])
        )
        if overall_status == "blocked_missing_required_assets" and has_missing:
            scene_status = "blocked_missing_required_assets"
        elif has_missing or bool(scene.get("manual_review")):
            scene_status = "manual_review_required"
        else:
            scene_status = "ready"

        layers: list[dict[str, Any]] = []
        missing_placeholders: list[dict[str, Any]] = []
        for selection in scene.get("asset_selections") or []:
            need_type = str(selection.get("need_type") or "unknown")
            if need_type == "script_text" or selection.get("required_category") == "script_text":
                continue
            if selection.get("status") == "selected":
                layers.append(
                    self._layer_from_selection(
                        selection,
                        scene_index=scene_index,
                        duration_seconds=duration_seconds,
                        status="ready",
                    )
                )
            elif selection.get("status") == "missing_asset":
                placeholder = self._placeholder_from_need(
                    selection,
                    scene_index=scene_index,
                    duration_seconds=duration_seconds,
                )
                missing_placeholders.append(placeholder)
                if build_mode == "draft_with_placeholders":
                    layers.append(placeholder)
        if missing_needs and not missing_placeholders:
            for need in missing_needs:
                placeholder = self._placeholder_from_need(
                    need,
                    scene_index=scene_index,
                    duration_seconds=duration_seconds,
                )
                missing_placeholders.append(placeholder)
                if build_mode == "draft_with_placeholders":
                    layers.append(placeholder)

        stacking_failures = compile_layer_stack(layers)
        if stacking_failures:
            scene_status = "manual_review_required"
            review_reasons.extend(stacking_failures)
        return {
            "scene_index": scene_index,
            "scene_name": str(scene.get("scene_name") or f"场景{scene_index + 1:02d}"),
            "scene_goal": str(scene.get("scene_goal") or "explanation"),
            "duration_seconds": duration_seconds,
            "status": scene_status,
            "canvas": {"width": canvas_width, "height": canvas_height},
            "layers": layers,
            "script_block": {
                "status": "ready" if scene.get("script") else "missing_script",
                "target": "maitu_script_panel",
                "text": str(scene.get("script") or ""),
            },
            "missing_placeholders": missing_placeholders,
            "review_reasons": self._dedupe(review_reasons),
            "stacking_failures": stacking_failures,
        }

    def _layer_from_selection(
        self,
        selection: dict[str, Any],
        *,
        scene_index: int,
        duration_seconds: int,
        status: str,
    ) -> dict[str, Any]:
        need_type = str(selection.get("need_type") or "asset_layer")
        rule = self._rule_for_need(need_type)
        material_roles = [
            str(role).strip()
            for role in (selection.get("selected_asset_material_roles") or [])
            if str(role).strip()
        ]
        inferred_role = ROLE_FOR_NEED.get(need_type, need_type)
        role = inferred_role if inferred_role in material_roles or not material_roles else material_roles[0]
        return {
            "layer_id": f"scene-{scene_index:02d}-{need_type}",
            "layer_type": need_type,
            "need_type": need_type,
            "role": role,
            "material_roles": list(dict.fromkeys([*material_roles, role])),
            "status": status,
            "required_category": selection.get("required_category"),
            "asset_code": selection.get("selected_asset_code"),
            "asset_display_code": selection.get("selected_asset_display_code"),
            "asset_local_file_code": selection.get("selected_asset_local_file_code"),
            "asset_original_filename": selection.get("selected_asset_original_filename"),
            "asset_local_relative_path": selection.get("selected_asset_local_relative_path"),
            "asset_browser_use_hint": selection.get("selected_asset_browser_use_hint"),
            "maitu_material_id": selection.get("selected_asset_maitu_material_id"),
            "source_material_type": selection.get("selected_asset_source_material_type"),
            "source_material_url": selection.get("selected_asset_source_material_url"),
            "source_cover_url": selection.get("selected_asset_source_cover_url"),
            "speaker_id": selection.get("selected_asset_speaker_id"),
            "digital_human_image_id": selection.get("selected_asset_digital_human_image_id"),
            "sound_enabled": selection.get("selected_asset_sound_enabled") is True,
            "audio_role": selection.get("selected_asset_audio_role") or "muted",
            "audio_classification_status": selection.get("selected_asset_audio_classification_status") or "unknown",
            "audio_class": selection.get("selected_asset_audio_class") or "unknown",
            "audio_start_seconds": 0.0,
            "audio_end_seconds": float(duration_seconds),
            "asset_title": selection.get("selected_asset_title"),
            "x": rule["x"],
            "y": rule["y"],
            "width": rule["width"],
            "height": rule["height"],
            "z_index": rule["z_index"],
            "fit": rule["fit"],
            "source_selection_status": selection.get("status"),
            "constraint_rules": list(selection.get("selected_asset_constraint_rules") or []),
            "constraint_evidence": {},
        }

    def _placeholder_from_need(
        self,
        need: dict[str, Any],
        *,
        scene_index: int,
        duration_seconds: int,
    ) -> dict[str, Any]:
        layer = self._layer_from_selection(
            {
                **need,
                "selected_asset_code": None,
                "selected_asset_display_code": None,
                "selected_asset_local_file_code": None,
                "selected_asset_title": None,
                "status": "missing_asset",
            },
            scene_index=scene_index,
            duration_seconds=duration_seconds,
            status="placeholder_required",
        )
        return layer

    @staticmethod
    def _rule_for_need(need_type: str) -> dict[str, Any]:
        return LAYOUT_RULES.get(need_type, DEFAULT_RULE)

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
