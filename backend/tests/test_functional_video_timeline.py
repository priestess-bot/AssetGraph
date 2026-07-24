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
                    {"clip_code": "VOICE-SHOT-01", "linked_shot_code": "SHOT-01", "timeline_range": {"start_ms": 0, "duration_ms": 30_000}, "gain_db": 0},
                    {"clip_code": "VOICE-SHOT-02", "linked_shot_code": "SHOT-02", "timeline_range": {"start_ms": 30_000, "duration_ms": 30_000}, "gain_db": 0},
                    {"clip_code": "BGM-01", "timeline_range": {"start_ms": 0, "duration_ms": 60_000}},
                ],
            },
            {
                "track_kind": "subtitle",
                "clips": [
                    {"clip_code": "SUBTITLE-SHOT-01", "linked_shot_code": "SHOT-01", "timeline_range": {"start_ms": 0, "duration_ms": 30_000}, "subtitle_text": "第一段字幕", "headline_text": "第一段标题"},
                    {"clip_code": "SUBTITLE-SHOT-02", "linked_shot_code": "SHOT-02", "timeline_range": {"start_ms": 30_000, "duration_ms": 30_000}, "subtitle_text": "第二段字幕", "headline_text": "第二段标题"},
                ],
            },
        ],
    }


def test_timeline_update_preserves_requested_clip_order_across_tracks_and_shots() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-02", "duration_ms": 35_000, "transition": "fade", "source_start_seconds": 12, "source_end_seconds": 45, "fit": "cover", "crop_x": 0.2, "crop_y": 0.8, "playback_rate": 1.5, "show_product_sticker": True},
            {"clip_code": "SHOT-01", "duration_ms": 25_000, "transition": "fade_out"},
        ],
    )
    video_track, audio_track, subtitle_track = updated["tracks"]
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
    assert video_track["clips"][0]["fit"] == "cover"
    assert video_track["clips"][0]["crop_x"] == 0.2
    assert video_track["clips"][0]["crop_y"] == 0.8
    assert video_track["clips"][0]["playback_rate"] == 1.5
    assert video_track["clips"][0]["overlay_roles"] == ["product_sticker"]
    assert [clip["clip_code"] for clip in subtitle_track["clips"]] == ["SUBTITLE-SHOT-02", "SUBTITLE-SHOT-01"]
    assert [clip["timeline_range"] for clip in subtitle_track["clips"]] == [
        {"start_ms": 0, "duration_ms": 35_000},
        {"start_ms": 35_000, "duration_ms": 25_000},
    ]

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
    assert rendered_input["shots"][0]["fit"] == "cover"
    assert rendered_input["shots"][0]["crop_x"] == 0.2
    assert rendered_input["shots"][0]["crop_y"] == 0.8
    assert rendered_input["shots"][0]["playback_rate"] == 1.5
    assert rendered_input["shots"][0]["overlay_roles"] == ["product_sticker"]
    assert rendered_input["shots"][0]["subtitle_text"] == "第二段字幕"
    assert rendered_input["shots"][0]["screen_text"] == "第二段标题"
    assert rendered_input["shots"][0]["voice_gain_db"] == 0.0


def test_timeline_voice_gains_remain_bound_to_fixed_shots() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
            {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut"},
        ],
        audio_updates=[
            {"clip_code": "VOICE-SHOT-01", "gain_db": -6.5},
            {"clip_code": "VOICE-SHOT-02", "gain_db": 3},
        ],
    )
    audio_track = updated["tracks"][1]
    assert [(clip["clip_code"], clip["gain_db"]) for clip in audio_track["clips"][:2]] == [
        ("VOICE-SHOT-02", 3.0),
        ("VOICE-SHOT-01", -6.5),
    ]
    rendered_input = FunctionalVideoService._timeline_shot_list(
        {"shots": [{"shot_code": "SHOT-01"}, {"shot_code": "SHOT-02"}]},
        updated,
    )
    assert [shot["voice_gain_db"] for shot in rendered_input["shots"]] == [3.0, -6.5]


def test_timeline_rejects_incomplete_or_out_of_range_voice_gains() -> None:
    from app.domain.errors import DomainValidationError

    try:
        FunctionalVideoService._apply_timeline_update(
            _timeline(),
            [
                {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut"},
                {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
            ],
            audio_updates=[{"clip_code": "VOICE-SHOT-01", "gain_db": 0}],
        )
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_AUDIO_CLIP_SET_MISMATCH"
    else:
        raise AssertionError("audio updates must retain the complete fixed voice set")

    try:
        FunctionalVideoService._apply_timeline_update(
            _timeline(),
            [
                {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut"},
                {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
            ],
            audio_updates=[
                {"clip_code": "VOICE-SHOT-01", "gain_db": 15},
                {"clip_code": "VOICE-SHOT-02", "gain_db": 0},
            ],
        )
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_AUDIO_GAIN_INVALID"
    else:
        raise AssertionError("voice gain outside the bounded range must be rejected")


def test_timeline_subtitle_updates_remain_bound_to_fixed_shots() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut"},
            {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
        ],
        [
            {"clip_code": "SUBTITLE-SHOT-01", "subtitle_text": "更新后的第一段字幕", "headline_text": "更新标题", "caption_position": "center"},
            {"clip_code": "SUBTITLE-SHOT-02", "subtitle_text": "更新后的第二段字幕", "headline_text": ""},
        ],
    )

    subtitle_track = next(track for track in updated["tracks"] if track["track_kind"] == "subtitle")
    assert subtitle_track["clips"][0]["subtitle_text"] == "更新后的第一段字幕"
    assert subtitle_track["clips"][0]["headline_text"] == "更新标题"
    assert subtitle_track["clips"][0]["caption_position"] == "center"

    from app.domain.errors import DomainValidationError

    try:
        FunctionalVideoService._apply_timeline_update(
            _timeline(),
            [
                {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut"},
                {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
            ],
            [{"clip_code": "SUBTITLE-SHOT-01", "subtitle_text": "不完整", "headline_text": ""}],
        )
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_SUBTITLE_SET_MISMATCH"
    else:
        raise AssertionError("subtitle updates must retain the complete fixed subtitle set")


def test_timeline_subtitle_update_payload_preserves_historical_text() -> None:
    timeline = _timeline()

    assert FunctionalVideoService._timeline_subtitle_updates(timeline) == [
        {
            "clip_code": "SUBTITLE-SHOT-01",
            "subtitle_text": "第一段字幕",
            "headline_text": "第一段标题",
            "caption_position": "bottom",
        },
        {
            "clip_code": "SUBTITLE-SHOT-02",
            "subtitle_text": "第二段字幕",
            "headline_text": "第二段标题",
            "caption_position": "bottom",
        },
    ]


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


def test_timeline_crop_position_requires_a_complete_normalized_cover_pair() -> None:
    from app.domain.errors import DomainValidationError

    updates = [
        {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut", "crop_x": 0.25},
        {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
    ]
    try:
        FunctionalVideoService._apply_timeline_update(_timeline(), updates)
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_CROP_POSITION_INCOMPLETE"
    else:
        raise AssertionError("crop position must include both coordinates")

    updates[0] = {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut", "crop_x": 1.1, "crop_y": 0.5}
    try:
        FunctionalVideoService._apply_timeline_update(_timeline(), updates)
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_CROP_POSITION_INVALID"
    else:
        raise AssertionError("crop position must remain normalized")

    contain_timeline = _timeline()
    contain_timeline["tracks"][0]["clips"][0]["fit"] = "contain"
    updates[0] = {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut", "crop_x": 0.5, "crop_y": 0.5}
    try:
        FunctionalVideoService._apply_timeline_update(contain_timeline, updates)
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_CROP_POSITION_UNSUPPORTED"
    else:
        raise AssertionError("contain must not accept crop focus")


def test_timeline_playback_rate_is_bounded() -> None:
    from app.domain.errors import DomainValidationError

    updates = [
        {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut", "playback_rate": 0.5},
        {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut", "playback_rate": 2},
    ]
    updated = FunctionalVideoService._apply_timeline_update(_timeline(), updates)
    assert [clip["playback_rate"] for clip in updated["tracks"][0]["clips"]] == [0.5, 2.0]

    updates[0]["playback_rate"] = 2.5
    try:
        FunctionalVideoService._apply_timeline_update(_timeline(), updates)
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_PLAYBACK_RATE_INVALID"
    else:
        raise AssertionError("playback rate must remain in the bounded range")


def test_release_subject_refs_pin_every_required_content_revision() -> None:
    refs = FunctionalVideoService._release_subject_refs(
        {
            "source_project_code": "CONTENT-001",
            "source_project_revision": 3,
            "variant_code": "VARIANT-001",
            "variant_revision": 1,
            "story_brief_code": "STORY-001",
            "story_brief_revision": 3,
            "script_revision_code": "SCRIPT-003",
            "script_revision": 3,
            "program_revision_code": "PROGRAM-003",
            "program_revision": 3,
            "shot_list_revision_code": "SHOTLIST-003",
            "shot_list_revision": 3,
        }
    )

    assert refs["content_project_revision"] == {"code": "CONTENT-001", "revision": 3}
    assert refs["production_variant_revision"] == {"code": "VARIANT-001", "revision": 1}
    assert refs["shot_list_revision"] == {"code": "SHOTLIST-003", "revision": 3}
