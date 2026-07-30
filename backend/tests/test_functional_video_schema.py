from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.functional_videos import (
    FunctionalVideoPlanCreate,
    FunctionalVideoTimelineClipUpdate,
)
from app.services.functional_videos import build_video_reproducibility_evidence


def test_video_plan_create_requires_exactly_one_content_source() -> None:
    assert FunctionalVideoPlanCreate(project_code="CONTENT-001").project_code == "CONTENT-001"
    assert FunctionalVideoPlanCreate(live_room_plan_code="LIVEPLAN-001").live_room_plan_code == "LIVEPLAN-001"

    with pytest.raises(ValidationError, match="exactly one"):
        FunctionalVideoPlanCreate()
    with pytest.raises(ValidationError, match="exactly one"):
        FunctionalVideoPlanCreate(project_code="CONTENT-001", live_room_plan_code="LIVEPLAN-001")


def test_video_plan_create_validates_each_visual_selection_list() -> None:
    plan = FunctionalVideoPlanCreate(
        project_code="CONTENT-001",
        visual_asset_codes=["AG-VID-001"],
        visual_group_codes=["AG-GRP-001"],
        visual_material_pack_codes=["AG-PACK-001"],
    )

    assert plan.visual_group_codes == ["AG-GRP-001"]
    assert plan.visual_material_pack_codes == ["AG-PACK-001"]
    with pytest.raises(ValidationError, match="unique"):
        FunctionalVideoPlanCreate(
            project_code="CONTENT-001",
            visual_material_pack_codes=["AG-PACK-001", "AG-PACK-001"],
        )


def test_video_plan_create_bounds_local_audio_gains() -> None:
    plan = FunctionalVideoPlanCreate(
        project_code="CONTENT-001",
        brand_logo_asset_code="AG-IMG-000",
        product_sticker_asset_code="AG-IMG-001",
        background_music_asset_code="AG-AUD-001",
        background_music_gain_db=-20,
        sound_effect_asset_code="AG-AUD-002",
        sound_effect_gain_db=-9,
    )

    assert plan.background_music_asset_code == "AG-AUD-001"
    assert plan.brand_logo_asset_code == "AG-IMG-000"
    assert plan.product_sticker_asset_code == "AG-IMG-001"
    assert plan.background_music_gain_db == -20
    assert plan.sound_effect_asset_code == "AG-AUD-002"
    assert plan.sound_effect_gain_db == -9
    with pytest.raises(ValidationError):
        FunctionalVideoPlanCreate(
            project_code="CONTENT-001",
            background_music_asset_code="AG-AUD-001",
            background_music_gain_db=-40,
        )
    with pytest.raises(ValidationError):
        FunctionalVideoPlanCreate(
            project_code="CONTENT-001",
            sound_effect_asset_code="AG-AUD-002",
            sound_effect_gain_db=7,
        )


def test_timeline_product_sticker_layout_requires_all_bounded_values() -> None:
    clip = FunctionalVideoTimelineClipUpdate(
        clip_code="SHOT-01",
        duration_ms=30_000,
        show_product_sticker=True,
        product_sticker_x=0.25,
        product_sticker_y=0.8,
        product_sticker_width_ratio=0.5,
    )

    assert clip.product_sticker_width_ratio == 0.5
    with pytest.raises(ValidationError, match="must be supplied together"):
        FunctionalVideoTimelineClipUpdate(
            clip_code="SHOT-01",
            duration_ms=30_000,
            product_sticker_x=0.25,
        )
    with pytest.raises(ValidationError):
        FunctionalVideoTimelineClipUpdate(
            clip_code="SHOT-01",
            duration_ms=30_000,
            product_sticker_x=0.25,
            product_sticker_y=0.8,
            product_sticker_width_ratio=1.1,
        )


def test_reproducibility_evidence_projects_stable_timeline_and_render_identities() -> None:
    timeline = {
        "schema_version": "timeline.v2",
        "tracks": [{"track_kind": "video", "clips": [{"clip_code": "SHOT-01"}]}],
    }
    evidence = build_video_reproducibility_evidence(
        timeline_revision=3,
        production_timeline=timeline,
        artifacts=[
            {
                "artifact_key": "render_manifest",
                "checksum_sha256": "a" * 64,
                "download_url": "/api/video-productions/VIDJOB-001/artifacts/render_manifest",
                "metadata": {"manifest_fingerprint": "b" * 64},
            },
            {
                "artifact_key": "render_manifest_diff",
                "checksum_sha256": "c" * 64,
                "download_url": "/api/video-productions/VIDJOB-001/artifacts/render_manifest_diff",
                "metadata": {"classification": "output_changed_with_fixed_inputs"},
            },
        ],
    )

    assert evidence["timeline_revision"] == 3
    assert len(evidence["timeline_fingerprint_sha256"]) == 64
    assert evidence["render_manifest"]["metadata"]["manifest_fingerprint"] == "b" * 64
    assert evidence["render_manifest_difference"]["metadata"]["classification"] == (
        "output_changed_with_fixed_inputs"
    )
    assert evidence["retry_difference_recorded"] is True
    assert "ffmpeg_ffprobe_versions" in evidence["manifest_covers"]
