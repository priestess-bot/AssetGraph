from __future__ import annotations

from typing import Any

SOURCE = "script_content_asset_gap_report_rule_v1"

BLOCKING_NEED_TYPES = {
    "product_image",
    "background_image",
    "digital_human",
    "product_video",
    "promotion_sticker",
}

PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}


class ScriptAssetGapReporter:
    """Build a gap report from content-driven asset selections."""

    def report(self, scenes: list[dict[str, Any]]) -> dict[str, Any]:
        gaps_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for scene in sorted(scenes, key=lambda item: int(item.get("scene_index") or 0)):
            missing_needs = self._missing_needs_for_scene(scene)
            for need in missing_needs:
                need_type = str(need.get("need_type") or "unknown")
                required_category = str(need.get("required_category") or need_type)
                key = (need_type, required_category)
                gap = gaps_by_key.setdefault(
                    key,
                    {
                        "need_type": need_type,
                        "required_category": required_category,
                        "accepted_asset_types": [],
                        "priority": str(need.get("priority") or "medium"),
                        "missing_occurrences": 0,
                        "affected_scene_indexes": [],
                        "affected_scene_names": [],
                        "descriptions": [],
                        "keywords": [],
                    },
                )
                gap["missing_occurrences"] += 1
                self._append_unique(gap["affected_scene_indexes"], int(scene.get("scene_index") or 0))
                self._append_unique(gap["affected_scene_names"], str(scene.get("scene_name") or ""))
                for asset_type in need.get("accepted_asset_types") or []:
                    self._append_unique(gap["accepted_asset_types"], str(asset_type))
                self._append_unique(gap["descriptions"], str(need.get("description") or ""))
                for keyword in need.get("keywords") or []:
                    self._append_unique(gap["keywords"], str(keyword))
                if PRIORITY_RANK.get(str(need.get("priority") or "medium"), 1) > PRIORITY_RANK.get(gap["priority"], 1):
                    gap["priority"] = str(need.get("priority"))

        gaps = [self._finalize_gap(gap) for gap in gaps_by_key.values()]
        gaps.sort(key=lambda gap: (not gap["blocks_auto_build"], -gap["missing_occurrences"], gap["need_type"]))
        blocking_gap_count = sum(1 for gap in gaps if gap["blocks_auto_build"])
        total_missing_occurrences = sum(gap["missing_occurrences"] for gap in gaps)
        if blocking_gap_count:
            readiness_status = "blocked_missing_required_assets"
        elif gaps:
            readiness_status = "ready_for_layout_with_fallbacks"
        else:
            readiness_status = "ready_for_layout"
        return {
            "source": SOURCE,
            "scene_count": len(scenes),
            "gap_count": len(gaps),
            "total_missing_occurrences": total_missing_occurrences,
            "blocking_gap_count": blocking_gap_count,
            "can_build_with_fallback": blocking_gap_count == 0,
            "readiness_status": readiness_status,
            "gaps": gaps,
        }

    def _missing_needs_for_scene(self, scene: dict[str, Any]) -> list[dict[str, Any]]:
        missing_needs = [dict(need) for need in (scene.get("missing_asset_needs") or [])]
        if missing_needs:
            return missing_needs
        return [
            {
                "need_type": selection.get("need_type"),
                "required_category": selection.get("required_category"),
                "accepted_asset_types": selection.get("accepted_asset_types") or [],
                "description": selection.get("description") or "",
                "keywords": selection.get("keywords") or [],
                "priority": selection.get("priority") or "medium",
            }
            for selection in (scene.get("asset_selections") or [])
            if selection.get("status") == "missing_asset"
        ]

    def _finalize_gap(self, gap: dict[str, Any]) -> dict[str, Any]:
        blocks_auto_build = self._blocks_auto_build(gap)
        return {
            **gap,
            "blocks_auto_build": blocks_auto_build,
            "fallback_strategy": self._fallback_strategy(gap, blocks_auto_build),
            "recommended_asset_specs": [self._recommended_asset_spec(gap)],
        }

    @staticmethod
    def _blocks_auto_build(gap: dict[str, Any]) -> bool:
        if gap.get("priority") != "high":
            return False
        return gap.get("need_type") in BLOCKING_NEED_TYPES or gap.get("required_category") in BLOCKING_NEED_TYPES

    @staticmethod
    def _fallback_strategy(gap: dict[str, Any], blocks_auto_build: bool) -> str:
        need_type = gap.get("need_type")
        if blocks_auto_build:
            return (
                f"缺少高优先级 {need_type} 素材；不要用无关素材硬替换。"
                "请补充素材或人工确认临时占位后再生成可执行搭建计划。"
            )
        return (
            f"缺少 {need_type} 素材；可先使用同主题低优先级素材或隐藏该辅助图层，"
            "但需要在复核报告中标记。"
        )

    @staticmethod
    def _recommended_asset_spec(gap: dict[str, Any]) -> dict[str, Any]:
        return {
            "required_category": gap.get("required_category"),
            "accepted_asset_types": gap.get("accepted_asset_types") or [],
            "minimum_count": gap.get("missing_occurrences", 1),
            "suggested_filename_keywords": gap.get("keywords") or [],
            "suggested_tags": gap.get("keywords") or [],
            "usage_hint": "；".join(gap.get("descriptions") or []),
        }

    @staticmethod
    def _append_unique(items: list[Any], value: Any) -> None:
        if value not in {None, ""} and value not in items:
            items.append(value)
