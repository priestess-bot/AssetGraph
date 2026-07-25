from __future__ import annotations

import pytest

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
            {"clip_code": "SHOT-02", "duration_ms": 35_000, "transition": "fade", "source_start_seconds": 12, "source_end_seconds": 45, "fit": "cover", "crop_x": 0.2, "crop_y": 0.8, "playback_rate": 1.5, "show_product_sticker": True, "product_sticker_x": 0.2, "product_sticker_y": 0.7, "product_sticker_width_ratio": 0.4},
            {"clip_code": "SHOT-01", "duration_ms": 25_000, "transition": "fade_out"},
        ],
        poster_time_ms=12_000,
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
    assert video_track["clips"][0]["product_sticker_layout"] == {
        "x": 0.2,
        "y": 0.7,
        "width_ratio": 0.4,
    }
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
    assert rendered_input["shots"][0]["product_sticker_layout"] == {
        "x": 0.2,
        "y": 0.7,
        "width_ratio": 0.4,
    }
    assert rendered_input["shots"][0]["subtitle_text"] == "第二段字幕"
    assert rendered_input["shots"][0]["screen_text"] == "第二段标题"
    assert rendered_input["shots"][0]["voice_gain_db"] == 0.0
    assert updated["poster_time_ms"] == 12_000
    assert rendered_input["poster_time_seconds"] == 12.0


def test_timeline_rejects_product_sticker_layout_when_the_sticker_is_disabled() -> None:
    from app.domain.errors import DomainValidationError

    with pytest.raises(DomainValidationError) as error:
        FunctionalVideoService._apply_timeline_update(
            _timeline(),
            [
                {
                    "clip_code": "SHOT-01",
                    "duration_ms": 30_000,
                    "product_sticker_x": 0.5,
                    "product_sticker_y": 0.8,
                    "product_sticker_width_ratio": 0.5,
                },
                {"clip_code": "SHOT-02", "duration_ms": 30_000},
            ],
        )
    assert error.value.code == "VIDEO_TIMELINE_PRODUCT_STICKER_LAYOUT_UNAVAILABLE"


def test_timeline_removes_product_sticker_layout_when_the_sticker_is_disabled() -> None:
    timeline = _timeline()
    video_clip = timeline["tracks"][0]["clips"][0]
    video_clip["overlay_roles"] = ["product_sticker"]
    video_clip["product_sticker_layout"] = {"x": 0.2, "y": 0.7, "width_ratio": 0.4}

    updated = FunctionalVideoService._apply_timeline_update(
        timeline,
        [
            {
                "clip_code": "SHOT-01",
                "duration_ms": 30_000,
                "show_product_sticker": False,
            },
            {"clip_code": "SHOT-02", "duration_ms": 30_000},
        ],
    )

    clip = updated["tracks"][0]["clips"][0]
    assert clip["overlay_roles"] == []
    assert "product_sticker_layout" not in clip


def test_timeline_can_enable_the_brand_logo_for_an_individual_shot() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {
                "clip_code": "SHOT-01",
                "duration_ms": 30_000,
                "show_brand_logo": True,
            },
            {"clip_code": "SHOT-02", "duration_ms": 30_000},
        ],
    )

    assert updated["tracks"][0]["clips"][0]["overlay_roles"] == ["brand_logo"]
    assert FunctionalVideoService._timeline_shot_list(
        {"shots": [{"shot_code": "SHOT-01"}, {"shot_code": "SHOT-02"}]},
        updated,
    )["shots"][0]["overlay_roles"] == ["brand_logo"]


def test_timeline_rebinds_a_shot_only_to_its_frozen_visual_source_pool() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {
                "clip_code": "SHOT-01",
                "duration_ms": 30_000,
                "source_asset_code": "ASSET-02",
            },
            {"clip_code": "SHOT-02", "duration_ms": 30_000},
        ],
    )
    source = updated["tracks"][0]["clips"][0]["source_range"]
    assert source == {
        "asset_code": "ASSET-02",
        "start_seconds": 0.0,
        "end_seconds": 6.0,
        "available_start_seconds": 0.0,
        "available_end_seconds": 6.0,
    }
    shot_list = {
        "visual_source_pool": [
            {
                "asset_code": "ASSET-01",
                "relative_path": "video/one.mp4",
                "checksum_sha256": "a" * 64,
            },
            {
                "asset_code": "ASSET-02",
                "relative_path": "video/two.mp4",
                "checksum_sha256": "b" * 64,
            },
        ],
        "shots": [
            {
                "shot_code": "SHOT-01",
                "shot_index": 0,
                "asset_code": "ASSET-01",
                "asset_relative_path": "video/one.mp4",
                "asset_expected_checksum": "a" * 64,
            },
            {"shot_code": "SHOT-02", "shot_index": 1, "asset_code": "ASSET-02"},
        ],
    }
    rendered = FunctionalVideoService._timeline_shot_list(shot_list, updated)

    assert rendered["shots"][0]["asset_code"] == "ASSET-02"
    assert rendered["shots"][0]["asset_relative_path"] == "video/two.mp4"
    assert rendered["shots"][0]["asset_expected_checksum"] == "b" * 64

    from app.domain.errors import DomainValidationError

    invalid = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {
                "clip_code": "SHOT-01",
                "duration_ms": 30_000,
                "source_asset_code": "ASSET-UNKNOWN",
            },
            {"clip_code": "SHOT-02", "duration_ms": 30_000},
        ],
    )
    try:
        FunctionalVideoService._timeline_shot_list(shot_list, invalid)
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_SOURCE_ASSET_NOT_FROZEN"
    else:
        raise AssertionError("timeline source must be drawn from the frozen visual pool")


def test_compiled_video_shot_list_freezes_the_full_visual_source_pool() -> None:
    detail = {
        "project_code": "CONTENT-001",
        "title": "Frozen sources",
        "generation_goal": "Explain the selected product",
        "story_brief": {"content": "A compact product story."},
        "script": {"blocks": [{"content": "One source for every fixed shot."}]},
    }
    visual_assets = [
        {
            "asset_code": "AG-VID-000001",
            "relative_path": "video/one.mp4",
            "checksum_sha256": "a" * 64,
        },
        {
            "asset_code": "AG-VID-000002",
            "relative_path": "video/two.mp4",
            "checksum_sha256": "b" * 64,
        },
    ]

    _, _, shot_list, timeline = FunctionalVideoService._compile_content(
        detail,
        60,
        visual_assets=visual_assets,
    )

    assert shot_list["visual_source_pool"] == visual_assets
    assert {clip["source_range"]["asset_code"] for clip in timeline["tracks"][0]["clips"]} == {
        "AG-VID-000001",
        "AG-VID-000002",
    }


def test_compiled_video_exposes_a_table_surface_product_layout_suggestion() -> None:
    detail = {
        "project_code": "CONTENT-001",
        "title": "Table placement",
        "generation_goal": "Show the product on the table",
        "story_brief": {"content": "A compact product story."},
        "script": {"blocks": [{"content": "Put the product on the table."}]},
    }
    visual_asset = {
        "asset_code": "AG-VID-000001",
        "relative_path": "video/table.mp4",
        "checksum_sha256": "a" * 64,
        "constraint_profile": {
            "profile_code": "AG-CP-001",
            "revision_number": 2,
            "fingerprint_sha256": "b" * 64,
            "constraints": [
                {
                    "kind": "table_surface",
                    "hard": True,
                    "parameters": {
                        "name": "hero_table",
                        "x": 0.1,
                        "y": 0.58,
                        "width": 0.8,
                        "height": 0.28,
                        "product_role": "product_display",
                        "product_anchor": "bottom_center",
                    },
                }
            ],
        },
    }
    product_sticker = {
        "asset_code": "AG-IMG-000001",
        "relative_path": "image/product.png",
        "checksum_sha256": "c" * 64,
        "constraint_profile": {
            "profile_code": "AG-CP-002",
            "revision_number": 3,
            "fingerprint_sha256": "d" * 64,
            "constraints": [
                {
                    "kind": "size_range",
                    "hard": True,
                    "parameters": {"min_width": 0.2, "max_width": 0.5},
                }
            ],
        },
    }

    _, _, _, timeline = FunctionalVideoService._compile_content(
        detail,
        60,
        visual_assets=[visual_asset],
        product_sticker=product_sticker,
    )

    suggestion = timeline["tracks"][0]["clips"][0][
        "product_sticker_layout_suggestion"
    ]
    assert suggestion == {
        "x": 0.5,
        "y": 0.72,
        "width_ratio": 0.5,
        "source": "table_surface",
        "table_surface_name": "hero_table",
        "constraint_profile": {
            "profile_code": "AG-CP-001",
            "revision_number": 2,
            "fingerprint_sha256": "b" * 64,
        },
        "approximate": True,
    }
    assert FunctionalVideoService._video_constraint_snapshot(
        visual_assets=[visual_asset],
        product_sticker=product_sticker,
    )["profiles"] == [
        {
            "asset_code": "AG-VID-000001",
            "profile_code": "AG-CP-001",
            "revision_number": 2,
            "fingerprint_sha256": "b" * 64,
            "constraints": visual_asset["constraint_profile"]["constraints"],
        },
        {
            "asset_code": "AG-IMG-000001",
            "profile_code": "AG-CP-002",
            "revision_number": 3,
            "fingerprint_sha256": "d" * 64,
            "constraints": product_sticker["constraint_profile"]["constraints"],
        },
    ]
    left_anchor_asset = {
        **visual_asset,
        "constraint_profile": {
            **visual_asset["constraint_profile"],
            "constraints": [
                {
                    **visual_asset["constraint_profile"]["constraints"][0],
                    "parameters": {
                        **visual_asset["constraint_profile"]["constraints"][0][
                            "parameters"
                        ],
                        "product_anchor": "bottom_left",
                    },
                }
            ],
        },
    }
    assert FunctionalVideoService._product_sticker_layout_suggestion(
        left_anchor_asset,
        product_sticker,
    )["x"] == 0.2


def test_compiled_video_freezes_top_and_bottom_overlay_constraints() -> None:
    detail = {
        "project_code": "CONTENT-001",
        "title": "Overlay order",
        "generation_goal": "Keep the brand on top",
        "story_brief": {"content": "A compact product story."},
        "script": {"blocks": [{"content": "Show the product and brand."}]},
    }
    product_sticker = {
        "asset_code": "AG-IMG-000001",
        "relative_path": "image/product.png",
        "checksum_sha256": "a" * 64,
        "constraint_profile": {
            "profile_code": "AG-CP-001",
            "revision_number": 1,
            "fingerprint_sha256": "b" * 64,
            "constraints": [{"kind": "pin_layer_bottom", "hard": True}],
        },
    }
    brand_logo = {
        "asset_code": "AG-IMG-000002",
        "relative_path": "image/brand.png",
        "checksum_sha256": "c" * 64,
        "constraint_profile": {
            "profile_code": "AG-CP-002",
            "revision_number": 1,
            "fingerprint_sha256": "d" * 64,
            "constraints": [{"kind": "pin_layer_top", "hard": True}],
        },
    }

    _, _, shots, timeline = FunctionalVideoService._compile_content(
        detail,
        60,
        product_sticker=product_sticker,
        brand_logo=brand_logo,
    )

    assert shots["shots"][0]["overlay_z_order"] == {
        "brand_logo": 1000,
        "product_sticker": -1000,
    }
    assert timeline["tracks"][0]["clips"][0]["overlay_z_order"] == {
        "brand_logo": 1000,
        "product_sticker": -1000,
    }
    assert FunctionalVideoService._timeline_shot_list(shots, timeline)["shots"][0][
        "overlay_z_order"
    ] == {"brand_logo": 1000, "product_sticker": -1000}


def test_timeline_poster_time_must_remain_inside_the_rendered_duration() -> None:
    from app.domain.errors import DomainValidationError

    try:
        FunctionalVideoService._apply_timeline_update(
            _timeline(),
            [
                {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut"},
                {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
            ],
            poster_time_ms=60_000,
        )
    except DomainValidationError as exc:
        assert exc.code == "VIDEO_TIMELINE_POSTER_TIME_INVALID"
    else:
        raise AssertionError("poster time at or beyond the rendered duration must be rejected")


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


def test_timeline_reflows_the_fixed_background_music_to_the_new_duration() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-01", "duration_ms": 25_000, "transition": "cut"},
            {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
        ],
    )

    audio_track = next(track for track in updated["tracks"] if track["track_kind"] == "audio")
    assert audio_track["clips"][-1]["clip_code"] == "BGM-01"
    assert audio_track["clips"][-1]["timeline_range"] == {"start_ms": 0, "duration_ms": 55_000}


def test_selected_material_codes_include_background_music_for_snapshot_and_release() -> None:
    assert FunctionalVideoService._selected_material_codes(
        {
            "shots": [
                {"asset_code": "AG-VID-001"},
                {"asset_code": "AG-VID-001"},
                {"asset_code": "AG-VID-002"},
            ],
            "background_music": {"asset_code": "AG-AUD-001"},
            "sound_effect": {"asset_code": "AG-AUD-002"},
        }
    ) == ["AG-VID-001", "AG-VID-002", "AG-AUD-001", "AG-AUD-002"]


def test_timeline_keeps_sound_effects_bound_to_selected_shot_starts() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut", "play_sound_effect": True},
            {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut", "play_sound_effect": False},
        ],
    )

    video_track = next(track for track in updated["tracks"] if track["track_kind"] == "video")
    assert video_track["clips"][0]["audio_roles"] == ["sound_effect"]
    rendered = FunctionalVideoService._timeline_shot_list(
        {
            "sound_effect": {"asset_code": "AG-AUD-002"},
            "shots": [{"shot_code": "SHOT-01"}, {"shot_code": "SHOT-02"}],
        },
        updated,
    )
    assert rendered["shots"][0]["shot_code"] == "SHOT-02"
    assert rendered["shots"][0]["start_seconds"] == 0.0
    assert rendered["shots"][0]["audio_roles"] == ["sound_effect"]


def test_timeline_rejects_sound_effect_without_frozen_source() -> None:
    updated = FunctionalVideoService._apply_timeline_update(
        _timeline(),
        [
            {"clip_code": "SHOT-01", "duration_ms": 30_000, "transition": "cut", "play_sound_effect": True},
            {"clip_code": "SHOT-02", "duration_ms": 30_000, "transition": "cut"},
        ],
    )
    with pytest.raises(Exception, match="frozen local sound-effect"):
        FunctionalVideoService._timeline_shot_list(
            {"shots": [{"shot_code": "SHOT-01"}, {"shot_code": "SHOT-02"}]},
            updated,
        )


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
