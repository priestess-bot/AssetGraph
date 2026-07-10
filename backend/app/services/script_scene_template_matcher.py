from __future__ import annotations

import re
from typing import Any

SOURCE = "rule_based_template_component_match_v1"

GOAL_HINTS: dict[str, tuple[str, ...]] = {
    "opening": ("opening", "开场", "欢迎", "引入", "留人"),
    "product_explanation": ("product_explanation", "产品", "讲品", "讲解", "亮点", "风土", "产区", "口感", "卖点"),
    "conversion": ("conversion", "促单", "下单", "优惠", "商品卡", "成交", "购买", "福利", "转化"),
    "transition": ("transition", "转场", "过渡", "视频"),
    "closing": ("closing", "结尾", "收尾", "最后"),
}

DOMAIN_TOKENS = (
    "张裕",
    "龙谕龙8",
    "龙谕",
    "贺兰山东麓",
    "宁夏",
    "夏日",
    "干红",
    "商品卡",
    "优惠",
    "宴请",
    "送礼",
    "品酒大师PRO",
    "品酒大师",
    "解百纳",
)


class ScriptSceneTemplateMatcher:
    """Rule-based MVP matcher for Stage 3.

    It maps Stage-2 script scenes to indexed Maitu template scenes and performs
    per-component asset selection through the repository.  The implementation is
    deterministic so route tests can pin behavior before later LLM/reranker
    upgrades.
    """

    def __init__(self, repository: Any):
        self.repository = repository

    def match(
        self,
        scenes: list[dict[str, Any]],
        *,
        blueprint_code: str | None = None,
        reference_room_id: str | None = None,
        template_library_code: str | None = None,
        status: str | None = None,
        auto_select_assets: bool = True,
        min_confidence_for_auto_match: float = 0.3,
        candidate_scene_limit: int = 200,
    ) -> dict[str, Any] | None:
        template_scenes = self.repository.list_live_room_template_scenes(
            blueprint_code=blueprint_code,
            reference_room_id=reference_room_id,
            template_library_code=template_library_code,
            status=status,
            q=None,
            limit=candidate_scene_limit,
            offset=0,
        )
        if not template_scenes:
            return None

        used_template_scene_codes: set[str] = set()
        matches: list[dict[str, Any]] = []
        for scene in sorted(scenes, key=lambda row: int(row.get("scene_index") or 0)):
            template_scene, confidence, reasons = self._best_template_scene(
                scene,
                template_scenes,
                used_template_scene_codes=used_template_scene_codes,
            )
            if template_scene is not None:
                used_template_scene_codes.add(str(template_scene.get("scene_template_code") or ""))
            components = (
                self.repository.list_live_room_template_scene_components(template_scene["scene_template_code"])
                if template_scene is not None
                else []
            ) or []
            script_context = self._script_context(scene, template_scene)
            component_selections = [
                self._select_component_asset(
                    component,
                    template_scene,
                    script_context,
                    auto_select_assets=auto_select_assets,
                )
                for component in components
            ]
            review_reasons = list(scene.get("review_reasons") or [])
            manual_review = bool(scene.get("manual_review"))
            if confidence < min_confidence_for_auto_match:
                manual_review = True
                review_reasons.append("low_confidence_template_match")
            if any(selection["status"] == "missing_asset" for selection in component_selections):
                manual_review = True
                review_reasons.append("missing_component_asset")
            review_reasons = self._dedupe(review_reasons)

            matches.append(
                {
                    "scene_index": int(scene.get("scene_index") or 0),
                    "scene_name": str(scene.get("scene_name") or f"场景{len(matches) + 1:02d}"),
                    "scene_goal": str(scene.get("scene_goal") or "explanation"),
                    "duration_seconds": int(scene.get("duration_seconds") or 0),
                    "script": str(scene.get("script") or ""),
                    "keywords": list(scene.get("keywords") or []),
                    "matched_blueprint_code": template_scene.get("blueprint_code") if template_scene else None,
                    "matched_template_library_code": template_scene.get("template_library_code") if template_scene else None,
                    "matched_template_scene_code": template_scene.get("scene_template_code") if template_scene else None,
                    "matched_template_scene_name": template_scene.get("scene_name") if template_scene else None,
                    "matched_template_scene_type": template_scene.get("scene_type") if template_scene else None,
                    "matched_reference_clip_id": template_scene.get("reference_clip_id") if template_scene else None,
                    "matched_script_block_code": template_scene.get("script_block_code") if template_scene else None,
                    "matched_script_content": template_scene.get("script_content") if template_scene else None,
                    "component_count": len(components),
                    "confidence": confidence,
                    "match_reasons": reasons,
                    "manual_review": manual_review,
                    "review_reasons": review_reasons,
                    "component_selections": component_selections,
                }
            )

        return {
            "source": SOURCE,
            "scene_count": len(scenes),
            "matched_scene_count": sum(1 for match in matches if match.get("matched_template_scene_code")),
            "manual_review_required": any(match["manual_review"] for match in matches),
            "matches": matches,
        }

    def _best_template_scene(
        self,
        script_scene: dict[str, Any],
        template_scenes: list[dict[str, Any]],
        *,
        used_template_scene_codes: set[str],
    ) -> tuple[dict[str, Any] | None, float, list[str]]:
        unused = [
            scene
            for scene in template_scenes
            if str(scene.get("scene_template_code") or "") not in used_template_scene_codes
        ]
        pool = unused or template_scenes
        scored = [(self._score_template_scene(script_scene, template_scene), template_scene) for template_scene in pool]
        scored.sort(
            key=lambda item: (
                item[0][0],
                -(item[1].get("sort_order") or 999999),
                str(item[1].get("scene_template_code") or ""),
            ),
            reverse=True,
        )
        if not scored:
            return None, 0.0, []
        (score, reasons), template_scene = scored[0]
        return template_scene, score, reasons

    def _score_template_scene(self, script_scene: dict[str, Any], template_scene: dict[str, Any]) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        script_name = str(script_scene.get("scene_name") or "")
        script_goal = str(script_scene.get("scene_goal") or "")
        script_text = " ".join(
            str(part or "")
            for part in (
                script_name,
                script_goal,
                script_scene.get("script"),
                " ".join(str(item) for item in (script_scene.get("keywords") or [])),
            )
        )
        template_text = " ".join(
            str(part or "")
            for part in (
                template_scene.get("scene_name"),
                template_scene.get("scene_type"),
                template_scene.get("reference_product_name"),
                template_scene.get("script_content"),
            )
        )
        if script_goal:
            goal_hints = GOAL_HINTS.get(script_goal, (script_goal,))
            if any(hint and hint.lower() in template_text.lower() for hint in goal_hints):
                score += 0.35
                reasons.append(f"scene_goal matches template intent: {script_goal}")

        for term in self._name_terms(script_name):
            if term and term in template_text:
                score += 0.25
                reasons.append(f"scene_name term matches template: {term}")
                break

        keyword_hits = []
        for keyword in script_scene.get("keywords") or []:
            keyword_text = str(keyword)
            if keyword_text and keyword_text in template_text:
                keyword_hits.append(keyword_text)
        if keyword_hits:
            score += min(0.36, 0.12 * len(keyword_hits))
            reasons.append("script keywords match template: " + ", ".join(keyword_hits[:5]))

        domain_hits = [token for token in DOMAIN_TOKENS if token in script_text and token in template_text]
        if domain_hits:
            score += min(0.24, 0.08 * len(domain_hits))
            reasons.append("domain tokens overlap: " + ", ".join(domain_hits[:5]))

        if script_name and template_scene.get("scene_name") and (
            script_name in str(template_scene.get("scene_name")) or str(template_scene.get("scene_name")) in script_name
        ):
            score += 0.10
            reasons.append("scene_name directly overlaps template scene_name")

        if not reasons:
            reasons.append("fallback nearest template by sort order; manual review recommended")
        return round(min(score, 1.0), 4), self._dedupe(reasons)

    @staticmethod
    def _name_terms(scene_name: str) -> list[str]:
        terms = [term for term in ("开场", "欢迎", "产品", "亮点", "讲解", "促单", "转化", "下单", "结尾") if term in scene_name]
        terms.extend(token for token in re.findall(r"[A-Za-z]+\d*|\d+[A-Za-z]*", scene_name) if len(token) >= 2)
        return terms

    @staticmethod
    def _script_context(script_scene: dict[str, Any], template_scene: dict[str, Any] | None) -> str:
        parts = [
            script_scene.get("scene_name"),
            script_scene.get("scene_goal"),
            script_scene.get("script"),
            " ".join(str(item) for item in (script_scene.get("keywords") or [])),
        ]
        if template_scene:
            parts.extend(
                [
                    template_scene.get("scene_name"),
                    template_scene.get("scene_type"),
                    template_scene.get("reference_product_name"),
                    template_scene.get("script_content"),
                ]
            )
        return "；".join(str(part).strip() for part in parts if str(part or "").strip())

    def _select_component_asset(
        self,
        component: dict[str, Any],
        template_scene: dict[str, Any] | None,
        script_context: str,
        *,
        auto_select_assets: bool,
    ) -> dict[str, Any]:
        base = {
            "component_template_code": component.get("component_template_code"),
            "layer_name": component.get("layer_name") or component.get("component_name"),
            "layer_role": component.get("layer_role") or component.get("component_role"),
            "required_category": component.get("required_category"),
            "accepted_asset_types": component.get("accepted_asset_types") or [],
            "replacement_policy": component.get("replacement_policy") or "keep_layout",
            "status": "not_selected",
            "selected_asset_code": None,
            "selected_asset_title": None,
            "selected_asset_display_code": None,
            "selected_asset_local_file_code": None,
            "selected_asset_original_filename": None,
            "selected_asset_local_relative_path": None,
            "selected_asset_browser_use_hint": None,
            "match_score": None,
            "match_reasons": [],
            "selection_source": None,
        }
        if not component.get("required_category"):
            base["status"] = "not_required"
            return base
        if not auto_select_assets:
            return base
        if template_scene is None:
            base["status"] = "missing_asset"
            base["selection_source"] = "script_scene_rule_filter"
            return base

        candidate = self.repository.select_asset_for_template_component(component, template_scene, script_context)
        if candidate is None:
            base["status"] = "missing_asset"
            base["selection_source"] = "script_scene_rule_filter"
            return base

        base.update(
            {
                "status": "selected",
                "selected_asset_code": candidate.get("asset_code"),
                "selected_asset_title": candidate.get("title"),
                "selected_asset_display_code": candidate.get("display_code"),
                "selected_asset_local_file_code": candidate.get("local_file_code"),
                "selected_asset_original_filename": candidate.get("original_filename"),
                "selected_asset_local_relative_path": candidate.get("local_relative_path"),
                "selected_asset_browser_use_hint": candidate.get("browser_use_hint"),
                "match_score": candidate.get("match_score"),
                "match_reasons": candidate.get("match_reasons") or [],
                "selection_source": "script_scene_rule_filter",
            }
        )
        return base

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
