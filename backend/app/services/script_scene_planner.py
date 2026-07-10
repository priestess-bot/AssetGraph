from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

KEYWORD_CANDIDATES = [
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
]

GOAL_RULES = [
    ("opening", ("开场", "欢迎", "引入", "留人")),
    ("product_explanation", ("产品", "亮点", "讲品", "风土", "产区", "口感", "卖点")),
    ("conversion", ("促单", "下单", "优惠", "商品卡", "成交", "购买", "福利")),
    ("transition", ("转场", "过渡", "视频")),
    ("closing", ("结尾", "收尾", "最后")),
]


@dataclass(slots=True)
class ParsedScene:
    scene_index: int
    scene_name: str
    scene_goal: str
    duration_seconds: int
    script: str
    keywords: list[str]
    manual_review: bool
    review_reasons: list[str]


class ScriptScenePlanner:
    """Deterministic first-pass splitter for live-room scripts.

    This deliberately avoids pretending to be a full LLM scene planner. It gives
    AssetGraph a stable MVP artifact that can later be refined by LLM/reranker
    while tests keep field semantics stable.
    """

    def plan(
        self,
        script_text: str,
        *,
        target_scene_count: int | None = None,
        default_scene_duration_seconds: int = 60,
    ) -> dict[str, Any]:
        segments = self._split_segments(script_text)
        scenes = [
            self._scene_from_segment(
                index,
                segment,
                duration_seconds=default_scene_duration_seconds,
                target_scene_count=target_scene_count,
                total_segments=len(segments),
            )
            for index, segment in enumerate(segments)
        ]
        manual_review_required = any(scene.manual_review for scene in scenes)
        if target_scene_count and len(scenes) < target_scene_count:
            manual_review_required = True
        return {
            "source": "rule_based_v1",
            "scene_count": len(scenes),
            "target_scene_count": target_scene_count,
            "manual_review_required": manual_review_required,
            "scenes": [asdict(scene) for scene in scenes],
        }

    def _split_segments(self, script_text: str) -> list[str]:
        normalized = "\n".join(line.strip() for line in script_text.splitlines())
        blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
        if blocks:
            return blocks
        sentences = [part.strip() for part in re.split(r"(?<=[。！？!?])", normalized) if part.strip()]
        return sentences or [normalized.strip()]

    def _scene_from_segment(
        self,
        scene_index: int,
        segment: str,
        *,
        duration_seconds: int,
        target_scene_count: int | None,
        total_segments: int,
    ) -> ParsedScene:
        title, body = self._extract_title_and_body(segment)
        script = body or segment
        goal = self._infer_goal(segment)
        keywords = [keyword for keyword in KEYWORD_CANDIDATES if keyword in segment]
        review_reasons: list[str] = []
        if len(script) < 20:
            review_reasons.append("too_short")
        if target_scene_count and total_segments < target_scene_count:
            review_reasons.append("scene_count_below_target")
        if not keywords:
            review_reasons.append("no_domain_keywords")
        return ParsedScene(
            scene_index=scene_index,
            scene_name=title or f"场景{scene_index + 1:02d}",
            scene_goal=goal,
            duration_seconds=duration_seconds,
            script=script,
            keywords=keywords,
            manual_review=bool(review_reasons),
            review_reasons=review_reasons,
        )

    @staticmethod
    def _extract_title_and_body(segment: str) -> tuple[str | None, str]:
        match = re.match(r"^([^：:]{1,12})[：:]\s*(.+)$", segment, re.S)
        if not match:
            return None, segment.strip()
        return match.group(1).strip(), match.group(2).strip()

    @staticmethod
    def _infer_goal(segment: str) -> str:
        for goal, needles in GOAL_RULES:
            if any(needle in segment for needle in needles):
                return goal
        return "explanation"
