from __future__ import annotations

from app.services.functional_videos import FunctionalVideoService


def _timeline() -> dict[str, object]:
    return {
        "global_start_ms": 0,
        "global_end_ms": 60_000,
        "tracks": [
            {
                "track_kind": "video",
                "clips": [
                    {"clip_code": "SHOT-01", "timeline_range": {"start_ms": 0, "duration_ms": 30_000}, "source_range": {"asset_code": "ASSET-01", "start_seconds": 0, "end_seconds": 40}},
                    {"clip_code": "SHOT-02", "timeline_range": {"start_ms": 30_000, "duration_ms": 30_000}, "source_range": {"asset_code": "ASSET-02", "start_seconds": 10, "end_seconds": 50}},
                ],
            },
            {
                "track_kind": "audio",
                "clips": [
                    {"clip_code": "VOICE-SHOT-01", "timeline_range": {"start_ms": 0, "duration_ms": 30_000}},
                    {"clip_code": "VOICE-SHOT-02", "timeline_range": {"start_ms": 30_000, "duration_ms": 30_000}},
                    {"clip_code": "BGM-01", "timeline_range": {"start_ms": 0, "duration_ms": 60_000}},
                ],
            },
        ],
    }


def test_timeline_update_preserves_requested_clip_order_across_tracks_and_shots() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-02", "duration_ms": 35_000, "transition": "fade", "source_start_seconds": 12, "source_end_seconds": 45},
            {"clip_code": "SHOT-01", "duration_ms": 25_000, "transition": "fade_out"},
        ],
    )
    video_track, audio_track = updated["tracks"]
    assert [clip["clip_code"] for clip in video_track["clips"]] == ["SHOT-02", "SHOT-01"]
    assert [clip["timeline_range"] for clip in video_track["clips"]] == [
        {"start_ms": 0, "duration_ms": 35_000},
        {"start_ms": 35_000, "duration_ms": 25_000},
    ]
    assert [clip["clip_code"] for clip in audio_track["clips"]] == ["VOICE-SHOT-02", "VOICE-SHOT-01", "BGM-01"]
    assert [clip["timeline_range"] for clip in audio_track["clips"][:2]] == [
        {"start_ms": 0, "duration_ms": 35_000},
        {"start_ms": 35_000, "duration_ms": 25_000},
    ]
    assert video_track["clips"][0]["source_range"]["start_seconds"] == 12
    assert video_track["clips"][0]["source_range"]["end_seconds"] == 45

    shot_list = {
        "shots": [
            {"shot_code": "SHOT-01", "shot_index": 0, "narration": "one"},
            {"shot_code": "SHOT-02", "shot_index": 1, "narration": "two"},
        ]
    }
    rendered_input = FunctionalVideoService._timeline_shot_list(shot_list, updated)
    assert [shot["shot_code"] for shot in rendered_input["shots"]] == ["SHOT-02", "SHOT-01"]
    assert [shot["start_seconds"] for shot in rendered_input["shots"]] == [0.0, 35.0]
    assert rendered_input["shots"][0]["source_start_seconds"] == 12.0


def test_timeline_source_range_cannot_escape_its_fixed_available_range() -> None:
    from app.domain.errors import DomainValidationError

    try:
        FunctionalVideoService._apply_timeline_update(
            _timeline(),
            [
                {"clip_code": "SHOT-01", "duration_ms": 30_000, "source_start_seconds": 0, "source_end_seconds": 41},
                {"clip_code": "SHOT-02", "duration_ms": 30_000},
            ],
        )
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_SOURCE_RANGE_INVALID"
    else:
        raise AssertionError("source ranges outside the fixed evidence range must be rejected")
