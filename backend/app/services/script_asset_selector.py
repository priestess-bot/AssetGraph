from __future__ import annotations

from typing import Any

SOURCE = "script_content_asset_selection_rule_v1"


class ScriptAssetSelector:
    """Select real AssetGraph assets for content-derived script asset needs."""

    def __init__(self, repository: Any):
        self.repository = repository

    def select(self, scenes: list[dict[str, Any]], *, max_candidates_per_need: int = 1) -> dict[str, Any]:
        selected_scenes = [
            self._select_scene(scene, max_candidates_per_need=max_candidates_per_need)
            for scene in sorted(scenes, key=lambda item: int(item.get("scene_index") or 0))
        ]
        selected_count = sum(scene["selected_count"] for scene in selected_scenes)
        missing_count = sum(scene["missing_count"] for scene in selected_scenes)
        return {
            "source": SOURCE,
            "scene_count": len(selected_scenes),
            "selected_count": selected_count,
            "missing_count": missing_count,
            "manual_review_required": any(scene["manual_review"] for scene in selected_scenes),
            "scenes": selected_scenes,
        }

    def _select_scene(self, scene: dict[str, Any], *, max_candidates_per_need: int) -> dict[str, Any]:
        selections: list[dict[str, Any]] = []
        missing_needs: list[dict[str, Any]] = []
        review_reasons = list(scene.get("review_reasons") or [])
        manual_review = bool(scene.get("manual_review"))

        for need in scene.get("asset_needs") or []:
            selection = self._select_need(scene, need, max_candidates_per_need=max_candidates_per_need)
            selections.append(selection)
            if selection["status"] == "missing_asset":
                manual_review = True
                review_reasons.append(f"missing_asset:{need.get('need_type')}")
                missing_needs.append(need)

        selected_count = sum(1 for selection in selections if selection["status"] == "selected")
        missing_count = sum(1 for selection in selections if selection["status"] == "missing_asset")
        return {
            "scene_index": int(scene.get("scene_index") or 0),
            "scene_name": str(scene.get("scene_name") or ""),
            "scene_goal": str(scene.get("scene_goal") or ""),
            "duration_seconds": int(scene.get("duration_seconds") or 0),
            "script": str(scene.get("script") or ""),
            "keywords": list(scene.get("keywords") or []),
            "asset_selections": selections,
            "selected_count": selected_count,
            "missing_count": missing_count,
            "missing_asset_needs": missing_needs,
            "manual_review": manual_review,
            "review_reasons": self._dedupe(review_reasons),
        }

    def _select_need(self, scene: dict[str, Any], need: dict[str, Any], *, max_candidates_per_need: int) -> dict[str, Any]:
        base = {
            "need_type": need.get("need_type"),
            "required_category": need.get("required_category"),
            "accepted_asset_types": need.get("accepted_asset_types") or [],
            "description": need.get("description") or "",
            "keywords": need.get("keywords") or [],
            "priority": need.get("priority") or "medium",
            "status": "missing_asset",
            "selected_asset_code": None,
            "selected_asset_type": None,
            "selected_asset_title": None,
            "selected_asset_display_code": None,
            "selected_asset_local_file_code": None,
            "selected_asset_original_filename": None,
            "selected_asset_local_relative_path": None,
            "selected_asset_browser_use_hint": None,
            "selected_asset_maitu_material_id": None,
            "selected_asset_source_material_type": None,
            "selected_asset_source_material_url": None,
            "selected_asset_source_cover_url": None,
            "selected_asset_speaker_id": None,
            "selected_asset_digital_human_image_id": None,
            "selected_asset_sound_enabled": None,
            "selected_asset_audio_role": None,
            "selected_asset_audio_classification_status": None,
            "selected_asset_audio_class": None,
            "selected_asset_material_roles": [],
            "selected_asset_constraint_rules": [],
            "match_score": None,
            "match_reasons": [],
            "selection_source": "script_content_rule_filter",
            "candidate_count": 0,
        }

        if need.get("need_type") == "script_text" or need.get("required_category") == "script_text":
            return {
                **base,
                "status": "generated_content",
                "match_score": 1.0,
                "match_reasons": ["script text is generated directly from the scene script"],
                "selection_source": "scene_script_content",
            }

        candidates = self.repository.select_assets_for_script_asset_need(
            need,
            scene,
            limit=max_candidates_per_need,
        )
        if not candidates:
            return base

        candidate = candidates[0]
        return {
            **base,
            "status": "selected",
            "selected_asset_code": candidate.get("asset_code"),
            "selected_asset_type": candidate.get("asset_type"),
            "selected_asset_title": candidate.get("title"),
            "selected_asset_display_code": candidate.get("display_code"),
            "selected_asset_local_file_code": candidate.get("local_file_code"),
            "selected_asset_original_filename": candidate.get("original_filename"),
            "selected_asset_local_relative_path": candidate.get("local_relative_path"),
            "selected_asset_browser_use_hint": candidate.get("browser_use_hint"),
            "selected_asset_maitu_material_id": candidate.get("maitu_material_id"),
            "selected_asset_source_material_type": candidate.get("source_material_type"),
            "selected_asset_source_material_url": candidate.get("source_material_url"),
            "selected_asset_source_cover_url": candidate.get("source_cover_url"),
            "selected_asset_speaker_id": candidate.get("speaker_id"),
            "selected_asset_digital_human_image_id": candidate.get("digital_human_image_id"),
            "selected_asset_sound_enabled": candidate.get("sound_enabled"),
            "selected_asset_audio_role": candidate.get("audio_role"),
            "selected_asset_audio_classification_status": candidate.get("audio_classification_status"),
            "selected_asset_audio_class": candidate.get("audio_class"),
            "selected_asset_material_roles": list(candidate.get("material_roles") or []),
            "selected_asset_constraint_rules": list(candidate.get("constraint_rules") or []),
            "match_score": candidate.get("match_score"),
            "match_reasons": candidate.get("match_reasons") or [],
            "selection_source": "script_content_rule_filter",
            "candidate_count": len(candidates),
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
