from __future__ import annotations

import re
from typing import Any

from app.services.video_production_models import VideoProductionError


PRESET_CODE = "zhangyu_wine_demo_v1"
PRESET_SOURCE = "assetgraph_commercial_video_rule_v1"
DEFAULT_TOPIC = "夏日聚餐的清爽红酒选择"
PRODUCT_NAME = "张裕品酒大师PRO"
PRODUCT_FACTS = (
    "以蛇龙珠葡萄酿造",
    "橡木桶贮藏九个月以上",
    "可留意紫罗兰、成熟樱桃与草本气息",
    "适合搭配烤鸭和肉菜",
)
FORBIDDEN_COMMERCIAL_TERMS = (
    "优惠",
    "赠品",
    "赠送",
    "库存",
    "限量",
    "第一",
    "最佳",
    "到手价",
    "优惠券",
    "折扣",
)

BASE_DURATIONS = (6.0, 10.0, 9.0, 10.0, 9.0, 11.0)


def generate_story_brief(
    topic: str,
    *,
    preset_code: str = PRESET_CODE,
    target_duration_seconds: int = 55,
) -> dict[str, Any]:
    if preset_code != PRESET_CODE:
        raise VideoProductionError("UNKNOWN_PRESET", f"unsupported preset: {preset_code}")
    normalized_topic = " ".join(topic.split()).strip() or DEFAULT_TOPIC
    if len(normalized_topic) > 255:
        raise VideoProductionError("INVALID_TOPIC", "topic exceeds 255 characters")
    if not 30 <= target_duration_seconds <= 120:
        raise VideoProductionError("INVALID_TARGET_DURATION", "target duration must be between 30 and 120 seconds")

    return {
        "source": PRESET_SOURCE,
        "preset_code": PRESET_CODE,
        "topic": normalized_topic,
        "creative_angle": _creative_angle(normalized_topic),
        "product": {
            "name": PRODUCT_NAME,
            "series": "品酒大师",
            "variant": "PRO",
            "category": "干红葡萄酒",
        },
        "objective": "商品种草与商品详情访问意向",
        "audience": "希望为聚餐或日常佐餐选择红酒、但不想先理解复杂术语的消费者",
        "format": {
            "orientation": "vertical",
            "width": 1080,
            "height": 1920,
            "target_duration_seconds": target_duration_seconds,
            "shot_count": 6,
        },
        "verified_facts": list(PRODUCT_FACTS),
        "content_rules": {
            "cta": "进入商品详情核对容量与当前规格",
            "forbidden_claim_categories": ["价格", "促销", "库存", "排名", "赠品", "疗效"],
            "topic_is_not_a_fact_source": True,
        },
    }


def generate_commercial_script(story_brief: dict[str, Any]) -> dict[str, Any]:
    angle = str(story_brief.get("creative_angle") or "summer_gathering")
    opening = {
        "gift": "送礼选红酒，怎样兼顾体面、风味和真实的饮用场景？",
        "beginner": "第一次选红酒，怎样避开复杂术语，先找到清爽好搭餐的风格？",
        "summer_gathering": "夏日聚餐，怎样选一瓶清爽又好搭餐的红酒？",
        "gathering": "朋友聚餐，怎样选一瓶容易理解、又能衬托菜肴的红酒？",
    }.get(angle, "聚餐选红酒，怎样从场景和口味出发，找到好搭餐的风格？")
    blocks = [
        ("hook", opening, "夏日聚餐 · 清爽好搭餐"),
        (
            "product_positioning",
            "张裕品酒大师PRO，以蛇龙珠葡萄酿造，橡木桶贮藏九个月以上，果香之外也保留了佐餐需要的结构感。",
            "蛇龙珠酿造 · 橡木桶贮藏九个月以上",
        ),
        (
            "tasting_notes",
            "倒入杯中，可以留意紫罗兰、成熟樱桃与草本气息。先闻香，再小口品尝，层次会更清楚。",
            "紫罗兰 · 成熟樱桃 · 草本气息",
        ),
        (
            "pairing",
            "它适合搭配烤鸭和肉菜。从味道较轻的菜开始，再转向浓郁菜肴，酒和菜更能彼此衬托。",
            "烤鸭与肉菜佐餐",
        ),
        (
            "selection_guidance",
            "挑选时不用先看复杂名词，先确认场景和口味。偏爱清爽果香、又需要搭餐，可以把这款作为备选。",
            "先看场景，再看口味",
        ),
        (
            "cta",
            "一瓶酒的价值，在于让相聚更从容。想继续了解品酒大师PRO，可以进入商品详情，核对容量与当前规格。",
            "进入商品详情 · 核对当前规格",
        ),
    ]
    sections = [
        {
            "section_index": index,
            "section_type": section_type,
            "narration": narration,
            "tts_text": narration.replace("PRO", "P R O"),
            "screen_text": screen_text,
        }
        for index, (section_type, narration, screen_text) in enumerate(blocks)
    ]
    spoken_script = "".join(section["narration"] for section in sections)
    chinese_character_count = len(re.findall(r"[\u3400-\u9fff]", spoken_script))
    forbidden_hits = [term for term in FORBIDDEN_COMMERCIAL_TERMS if term in spoken_script]
    if not 190 <= chinese_character_count <= 230:
        raise VideoProductionError(
            "SCRIPT_LENGTH_OUT_OF_RANGE",
            f"commercial script contains {chinese_character_count} Chinese characters",
        )
    if forbidden_hits:
        raise VideoProductionError(
            "UNVERIFIED_COMMERCIAL_CLAIM",
            f"generated script contains forbidden terms: {', '.join(forbidden_hits)}",
        )
    return {
        "source": PRESET_SOURCE,
        "preset_code": PRESET_CODE,
        "title": str(story_brief.get("topic") or DEFAULT_TOPIC),
        "spoken_script": spoken_script,
        "sections": sections,
        "section_count": len(sections),
        "quality_report": {
            "verified_fact_source": PRESET_CODE,
            "topic_used_as_fact_source": False,
            "chinese_character_count": chinese_character_count,
            "forbidden_commercial_claim_hits": forbidden_hits,
            "promotion_free": not forbidden_hits,
        },
    }


def plan_shots(
    story_brief: dict[str, Any],
    script: dict[str, Any],
) -> dict[str, Any]:
    target_duration = float(story_brief["format"]["target_duration_seconds"])
    scale = target_duration / sum(BASE_DURATIONS)
    durations = [round(value * scale, 3) for value in BASE_DURATIONS]
    durations[-1] = round(target_duration - sum(durations[:-1]), 3)
    clip_specs = (
        ("MT-VID-0027", 0.0, 6.0, "contain", "opening"),
        ("MT-VID-0016", 0.0, 12.0, "cover", "product"),
        ("MT-VID-0027", 30.0, 42.0, "contain", "vineyard"),
        ("MT-VID-0016", 12.0, 25.0, "cover", "pouring"),
        ("MT-VID-0024", 0.0, 6.442, "cover", "detail"),
        ("MT-VID-0016", 25.0, 38.848, "cover", "cta"),
    )
    transition_names = ("cut", "cut", "cut", "cut", "cut", "fade_out")
    cursor = 0.0
    shots: list[dict[str, Any]] = []
    for index, (duration, section, clip, transition) in enumerate(
        zip(durations, script["sections"], clip_specs, transition_names, strict=True)
    ):
        asset_code, source_start, source_end, fit, visual_role = clip
        end = round(cursor + duration, 3)
        shots.append(
            {
                "shot_index": index,
                "shot_code": f"SHOT-{index + 1:02d}",
                "start_seconds": cursor,
                "end_seconds": end,
                "duration_seconds": duration,
                "goal": section["section_type"],
                "narration": section["narration"],
                "tts_text": section["tts_text"],
                "screen_text": section["screen_text"],
                "asset_code": asset_code,
                "source_start_seconds": source_start,
                "source_end_seconds": source_end,
                "source_available_seconds": round(source_end - source_start, 3),
                "fit": fit,
                "visual_role": visual_role,
                "transition": transition,
                "overlay_roles": ["brand_logo"] if index in {0, 5} else [],
            }
        )
        cursor = end
    return {
        "source": PRESET_SOURCE,
        "preset_code": PRESET_CODE,
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "duration_seconds": target_duration,
        "shot_count": len(shots),
        "shots": shots,
    }


def _creative_angle(topic: str) -> str:
    if any(token in topic for token in ("送礼", "礼物", "礼赠")):
        return "gift"
    if any(token in topic for token in ("入门", "新手", "第一次", "小白")):
        return "beginner"
    if "夏" in topic:
        return "summer_gathering"
    if any(token in topic for token in ("聚餐", "朋友", "宴请", "佐餐")):
        return "gathering"
    return "product_education"
