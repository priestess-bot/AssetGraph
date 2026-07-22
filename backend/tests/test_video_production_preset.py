from __future__ import annotations

import re

import pytest

from app.services.video_production_models import VideoProductionError
from app.services.video_production_preset import (
    DEFAULT_TOPIC,
    PRODUCT_FACTS,
    generate_commercial_script,
    generate_story_brief,
    plan_shots,
)
from app.services.video_production_subtitles import build_ass_subtitles


def test_demo_preset_generates_verified_script_and_six_contiguous_shots() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)

    assert brief["verified_facts"] == list(PRODUCT_FACTS)
    assert brief["content_rules"]["topic_is_not_a_fact_source"] is True
    assert 190 <= script["quality_report"]["chinese_character_count"] <= 230
    assert script["quality_report"]["promotion_free"] is True
    assert script["section_count"] == 6
    assert "P R O" in script["sections"][1]["tts_text"]
    assert shot_list["shot_count"] == 6
    assert shot_list["duration_seconds"] == 55
    assert [shot["asset_code"] for shot in shot_list["shots"]] == [
        "MT-VID-0027",
        "MT-VID-0016",
        "MT-VID-0027",
        "MT-VID-0016",
        "MT-VID-0024",
        "MT-VID-0016",
    ]
    assert shot_list["shots"][0]["start_seconds"] == 0
    assert shot_list["shots"][-1]["end_seconds"] == 55
    assert [shot["transition"] for shot in shot_list["shots"]] == [
        "cut",
        "cut",
        "cut",
        "cut",
        "cut",
        "fade_out",
    ]
    assert all(
        left["end_seconds"] == right["start_seconds"]
        for left, right in zip(shot_list["shots"], shot_list["shots"][1:])
    )


def test_topic_changes_angle_but_never_becomes_a_product_fact() -> None:
    topic = "送礼场景，限量库存第一名"
    brief = generate_story_brief(topic)
    script = generate_commercial_script(brief)

    assert brief["creative_angle"] == "gift"
    assert script["title"] == topic
    assert topic not in script["spoken_script"]
    assert not any(term in script["spoken_script"] for term in ("限量", "库存", "第一"))


def test_preset_rejects_unknown_domain_and_unsupported_duration() -> None:
    with pytest.raises(VideoProductionError, match="unsupported preset"):
        generate_story_brief("主题", preset_code="unknown")
    with pytest.raises(VideoProductionError, match="between 30 and 120"):
        generate_story_brief("主题", target_duration_seconds=15)


def test_ass_subtitles_are_complete_monotonic_and_stay_within_safe_lines() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)

    content, manifest = build_ass_subtitles(shot_list)

    assert content.startswith("[Script Info]")
    assert "Noto Sans CJK SC" in content
    assert manifest["headline_event_count"] == 6
    assert manifest["text_complete"] is True
    assert manifest["truncated_event_count"] == 0
    assert "…" not in content
    captions = [event for event in manifest["events"] if event["kind"] == "caption"]
    assert captions
    assert all(event["start_seconds"] < event["end_seconds"] for event in captions)
    assert all(
        len(lines) <= 2
        and all(
            len(re.findall(r".", line)) <= (19 if event["kind"] == "caption" else 16)
            for line in lines
        )
        for event in manifest["events"]
        for lines in [event["text"].splitlines()]
    )
    for shot in shot_list["shots"]:
        rendered = "".join(
            event["source_text"]
            for event in captions
            if event["shot_index"] == shot["shot_index"]
        )
        assert re.sub(r"\s+", "", rendered) == re.sub(r"\s+", "", shot["narration"])


def test_ass_subtitles_stop_at_real_speech_duration() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)
    voice_manifest = {
        "segments": [
            {"shot_index": shot["shot_index"], "speech_duration_seconds": 4.25}
            for shot in shot_list["shots"]
        ]
    }

    _, manifest = build_ass_subtitles(shot_list, voice_manifest)

    for shot in shot_list["shots"]:
        captions = [
            event
            for event in manifest["events"]
            if event["kind"] == "caption" and event["shot_index"] == shot["shot_index"]
        ]
        assert captions[-1]["end_seconds"] == pytest.approx(shot["start_seconds"] + 4.25, abs=0.001)
