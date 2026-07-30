from __future__ import annotations

import pytest

from app.services.audio_plan import AudioPlanError, AudioPlanValidator
from app.services.script_layout_build_plan_builder import ScriptLayoutBuildPlanBuilder


def layer(layer_id: str, *, role: str = "muted", enabled: bool = False, start: float = 0, end: float = 10):
    return {
        "layer_id": layer_id,
        "source_material_type": "video",
        "sound_enabled": enabled,
        "audio_role": role,
        "audio_classification_status": "classified",
        "audio_class": "speech" if role != "bgm" else "music",
        "audio_start_seconds": start,
        "audio_end_seconds": end,
    }


def test_unknown_video_audio_defaults_to_muted() -> None:
    result = AudioPlanValidator().normalize_layer(
        {"layer_id": "product", "source_material_type": "video"}, scene_duration=12
    )

    assert result["sound_enabled"] is False
    assert result["audio_role"] == "muted"
    assert result["audio_end_seconds"] == 12


def test_one_speech_and_one_bgm_can_overlap() -> None:
    scenes = [{"layers": [layer("host", role="speech", enabled=True), layer("music", role="bgm", enabled=True)]}]

    normalized = AudioPlanValidator().normalize_scenes(scenes)

    assert [item["audio_role"] for item in normalized[0]["layers"]] == ["speech", "bgm"]


def test_two_overlapping_speech_layers_are_blocked() -> None:
    scenes = [{"layers": [layer("host", role="speech", enabled=True), layer("product", role="speech", enabled=True)]}]

    with pytest.raises(AudioPlanError, match="overlaps"):
        AudioPlanValidator().normalize_scenes(scenes)


def test_original_audio_requires_completed_classification() -> None:
    candidate = layer("product", role="original_audio", enabled=True)
    candidate["audio_classification_status"] = "unknown"

    with pytest.raises(AudioPlanError, match="must be classified"):
        AudioPlanValidator().normalize_layer(candidate)


def test_build_plan_freezes_fresh_blank_room_preflight() -> None:
    plan = ScriptLayoutBuildPlanBuilder().build(
        {
            "build_mode": "strict",
            "status": "ready_for_build_plan",
            "can_generate_executable_build_plan": True,
            "scenes": [],
        },
        target_live_room_id="47000002",
        expected_title="新品空白草稿",
    )

    preflight = plan["operations"][0]
    assert preflight["require_fresh_blank_room"] is True
    assert plan["expected_title"] == "新品空白草稿"
    assert preflight["expected_live_room_title"] == "新品空白草稿"
    assert set(preflight["protected_reference_room_ids"]) == {"38336", "38995"}
