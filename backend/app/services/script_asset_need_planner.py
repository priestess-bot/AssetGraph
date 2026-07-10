from __future__ import annotations

from typing import Any

SOURCE = "script_content_asset_need_rule_v1"

PRODUCT_KEYWORDS = (
    "龙谕龙8",
    "龙谕龙12",
    "龙谕",
    "品酒大师PRO",
    "品酒大师MASTER",
    "品酒大师SUPER",
    "品酒大师PLUS",
    "品酒大师",
    "解百纳",
    "干红",
    "葡萄酒",
    "红酒",
)

REGION_KEYWORDS = (
    "宁夏",
    "贺兰山东麓",
    "贺兰山",
    "黄河",
    "葡萄园",
    "产区",
    "风土",
    "酒庄",
    "烟台",
)

PROMOTION_KEYWORDS = (
    "优惠",
    "商品卡",
    "下单",
    "福利",
    "赠品",
    "抽奖",
    "京豆",
    "限量",
    "成交",
    "购买",
)

TASTING_KEYWORDS = (
    "闻香",
    "入口",
    "口感",
    "单宁",
    "酒体",
    "颜色",
    "挂杯",
    "品鉴",
    "橡木桶",
    "香草",
    "巧克力",
)

BRAND_KEYWORDS = ("张裕", "百年张裕", "龙谕", "解百纳")


class ScriptAssetNeedPlanner:
    """Extract content-driven asset needs from structured script scenes.

    This is the corrected main path for live-room building: script content first,
    template references only later as layout/style fallback.  The planner returns
    stable deterministic needs that downstream retrieval/layout/build-plan steps
    can consume.
    """

    def plan(
        self,
        scenes: list[dict[str, Any]],
        *,
        include_default_host: bool = True,
        include_script_text_need: bool = True,
    ) -> dict[str, Any]:
        planned_scenes = [
            self._plan_scene(
                scene,
                include_default_host=include_default_host,
                include_script_text_need=include_script_text_need,
            )
            for scene in sorted(scenes, key=lambda item: int(item.get("scene_index") or 0))
        ]
        return {
            "source": SOURCE,
            "scene_count": len(planned_scenes),
            "manual_review_required": any(scene["manual_review"] for scene in planned_scenes),
            "scenes": planned_scenes,
        }

    def _plan_scene(
        self,
        scene: dict[str, Any],
        *,
        include_default_host: bool,
        include_script_text_need: bool,
    ) -> dict[str, Any]:
        scene_index = int(scene.get("scene_index") or 0)
        scene_name = str(scene.get("scene_name") or f"场景{scene_index + 1:02d}")
        scene_goal = str(scene.get("scene_goal") or "explanation")
        duration_seconds = int(scene.get("duration_seconds") or 0)
        script = str(scene.get("script") or "")
        incoming_keywords = [str(item) for item in (scene.get("keywords") or [])]
        text = "；".join([scene_name, scene_goal, script, "；".join(incoming_keywords)])

        needs: list[dict[str, Any]] = []
        if include_script_text_need:
            needs.append(
                self._need(
                    need_type="script_text",
                    required_category="script_text",
                    accepted_asset_types=["TEXT"],
                    description=f"{scene_name} 的主播话术文本",
                    keywords=self._dedupe([scene_name, *incoming_keywords]),
                    priority="high",
                    suggested_layer_role="script_block",
                    reason="每个场景必须写入对应直播话术，并在执行后回读验证。",
                )
            )
        if include_default_host:
            needs.append(
                self._need(
                    need_type="digital_human",
                    required_category="digital_human_video",
                    accepted_asset_types=["IMG", "VID"],
                    description="用于承载当前场景讲解的主播数字人或主播形象素材",
                    keywords=self._dedupe(["主播", "数字人", *self._hits(text, BRAND_KEYWORDS)]),
                    priority="high",
                    suggested_layer_role="digital_human",
                    reason="直播讲解场景默认需要主播主体；后续可按品牌或人设选择数字人。",
                )
            )

        product_hits = self._hits(text, PRODUCT_KEYWORDS)
        region_hits = self._hits(text, REGION_KEYWORDS)
        promotion_hits = self._hits(text, PROMOTION_KEYWORDS)
        tasting_hits = self._hits(text, TASTING_KEYWORDS)
        brand_hits = self._hits(text, BRAND_KEYWORDS)

        if product_hits or scene_goal in {"product_explanation", "conversion"}:
            product_keywords = self._dedupe([*product_hits, *self._hits(text, ("750ml", "整箱", "礼盒"))])
            if not product_keywords and incoming_keywords:
                product_keywords = incoming_keywords[:4]
            needs.append(
                self._need(
                    need_type="product_image",
                    required_category="product_image",
                    accepted_asset_types=["IMG"],
                    description=f"{scene_name} 需要展示的商品主图、瓶身图或整箱图",
                    keywords=product_keywords,
                    priority="high",
                    suggested_layer_role="product_image",
                    reason="剧本包含商品/讲品/促单内容，需要商品图承接用户识别与点击。",
                )
            )

        if region_hits:
            background_keywords = self._dedupe([*region_hits, "葡萄园" if any(token in text for token in ("宁夏", "贺兰山东麓", "风土")) else ""])
            needs.append(
                self._need(
                    need_type="background_image",
                    required_category="background_image",
                    accepted_asset_types=["IMG"],
                    description=f"与 {scene_name} 内容匹配的产区、葡萄园或品牌氛围背景",
                    keywords=background_keywords,
                    priority="high",
                    suggested_layer_role="background",
                    reason="剧本提到产区/风土/地域元素，背景应表达对应环境而不是复刻模板。",
                )
            )
        elif "夏日" in text or brand_hits or scene_goal == "opening":
            needs.append(
                self._need(
                    need_type="background_image",
                    required_category="background_image",
                    accepted_asset_types=["IMG"],
                    description=f"{scene_name} 的品牌氛围或主题背景",
                    keywords=self._dedupe(["夏日" if "夏日" in text else "", *brand_hits]),
                    priority="high" if scene_goal == "opening" else "medium",
                    suggested_layer_role="background",
                    reason="开场/品牌场景需要先建立直播间视觉氛围。",
                )
            )

        supporting_hits = self._dedupe([*self._hits(text, ("贺兰山", "黄河", "橡木桶", "米其林", "拉菲", "盲品赛")), *tasting_hits])
        if supporting_hits:
            needs.append(
                self._need(
                    need_type="supporting_visual",
                    required_category="floating_sticker",
                    accepted_asset_types=["IMG", "VID"],
                    description=f"用于解释 {scene_name} 中风土、工艺、口感或背书信息的辅助视觉素材",
                    keywords=supporting_hits,
                    priority="medium",
                    suggested_layer_role="supporting_visual",
                    reason="剧本包含解释性信息，需要辅助画面降低纯口播理解成本。",
                )
            )

        if tasting_hits and scene_goal in {"product_explanation", "explanation"}:
            needs.append(
                self._need(
                    need_type="product_video",
                    required_category="product_video",
                    accepted_asset_types=["VID"],
                    description=f"展示 {scene_name} 中酒体、倒酒、瓶身或品鉴动作的视频素材",
                    keywords=self._dedupe([*product_hits, *tasting_hits]),
                    priority="medium",
                    suggested_layer_role="product_video",
                    reason="品鉴/口感内容更适合视频动态承接。",
                )
            )

        if promotion_hits or scene_goal == "conversion":
            needs.append(
                self._need(
                    need_type="promotion_sticker",
                    required_category="floating_sticker",
                    accepted_asset_types=["IMG"],
                    description=f"{scene_name} 的优惠、商品卡、赠品或下单提示贴片",
                    keywords=self._dedupe([*promotion_hits, *product_hits]),
                    priority="high",
                    suggested_layer_role="promotion_sticker",
                    reason="促单内容需要明确视觉提示，引导点击商品卡/下单。",
                )
            )

        if brand_hits and scene_goal in {"opening", "closing"}:
            needs.append(
                self._need(
                    need_type="brand_logo_title",
                    required_category="floating_sticker",
                    accepted_asset_types=["IMG"],
                    description=f"{scene_name} 的品牌 logo、标题条或开场识别贴片",
                    keywords=brand_hits,
                    priority="medium",
                    suggested_layer_role="logo_title",
                    reason="开场/收尾需要品牌识别，但不应替代根据剧本选择的主体素材。",
                )
            )

        needs = self._merge_needs(needs)
        content_need_count = sum(1 for need in needs if need["need_type"] not in {"script_text", "digital_human"})
        review_reasons = list(scene.get("review_reasons") or [])
        manual_review = bool(scene.get("manual_review"))
        if len(script) < 12 or content_need_count == 0:
            manual_review = True
            review_reasons.append("insufficient_content_for_asset_needs")

        return {
            "scene_index": scene_index,
            "scene_name": scene_name,
            "scene_goal": scene_goal,
            "duration_seconds": duration_seconds,
            "script": script,
            "keywords": self._dedupe([*incoming_keywords, *product_hits, *region_hits, *promotion_hits]),
            "asset_needs": needs,
            "manual_review": manual_review,
            "review_reasons": self._dedupe(review_reasons),
        }

    @staticmethod
    def _need(
        *,
        need_type: str,
        required_category: str,
        accepted_asset_types: list[str],
        description: str,
        keywords: list[str],
        priority: str,
        suggested_layer_role: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "need_type": need_type,
            "required_category": required_category,
            "accepted_asset_types": accepted_asset_types,
            "description": description,
            "keywords": [keyword for keyword in ScriptAssetNeedPlanner._dedupe(keywords) if keyword],
            "priority": priority,
            "suggested_layer_role": suggested_layer_role,
            "reason": reason,
        }

    @staticmethod
    def _hits(text: str, candidates: tuple[str, ...]) -> list[str]:
        return [candidate for candidate in candidates if candidate and candidate in text]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @staticmethod
    def _merge_needs(needs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        priority_rank = {"low": 0, "medium": 1, "high": 2}
        for need in needs:
            need_type = need["need_type"]
            if need_type not in merged:
                merged[need_type] = need
                order.append(need_type)
                continue
            existing = merged[need_type]
            existing["keywords"] = ScriptAssetNeedPlanner._dedupe([*existing.get("keywords", []), *need.get("keywords", [])])
            if priority_rank.get(need.get("priority", "low"), 0) > priority_rank.get(existing.get("priority", "low"), 0):
                existing["priority"] = need["priority"]
            if len(need.get("description", "")) > len(existing.get("description", "")):
                existing["description"] = need["description"]
        return [merged[need_type] for need_type in order]
