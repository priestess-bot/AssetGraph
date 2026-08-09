from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.errors import DomainValidationError
from app.repositories.assets import AssetRepository
from app.repositories.material_library import MaterialLibraryRepository
from app.repositories.releases import ReleaseRepository
from app.repositories.video_productions import VideoProductionRepository
from app.services.functional_content import FunctionalContentService
from app.services.functional_live_rooms import FunctionalLiveRoomService
from app.services.functional_videos import FunctionalVideoService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def _generated_project(connection: psycopg.Connection, suffix: str) -> dict:
    content = FunctionalContentService(connection)
    project = content.create_project(
        {
            "title": f"Video plan {suffix}",
            "generation_goal": "Explain a product choice in a short vertical video",
            "theme": "Summer choice",
            "story": "Start with a real question from the audience.",
            "must_include": [],
            "must_avoid": [],
            "fact_card_codes": [],
            "secondary_template_codes": [],
        },
        actor_id="test-operator",
    )
    content.confirm_project(
        project["project_code"], expected_revision=1, actor_id="test-operator"
    )
    content.parse_design_brief(
        project["project_code"],
        expected_revision=1,
        raw_input="Create the project baseline before the rendered-video branch.",
        actor_id="test-operator",
    )
    content.confirm_design_brief(
        project["project_code"], expected_revision=1, actor_id="test-operator"
    )
    return content.generate_chain(project["project_code"], actor_id="test-operator")


def test_functional_video_plan_seeds_content_stages_and_queues_renderer() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        generated = _generated_project(connection, suffix)
        plan = FunctionalVideoService(connection).create_plan(
            {"project_code": generated["project_code"], "target_duration_seconds": 55},
            actor_id="test-operator",
        )

        assert plan["job_status"] == "queued"
        assert plan["current_stage"] == "asset_selection"
        assert plan["progress_percent"] == 37
        assert (
            plan["production_timeline"]["schema_version"]
            == "otio-compatible-production-timeline.v2"
        )
        assert plan["production_timeline"]["otio_schema"] == "OTIO_SCHEMA:Timeline.1"
        assert plan["production_timeline"]["global_time_range"] == {
            "start_time": {"value": 0, "rate": 1000},
            "duration": {"value": 55_000, "rate": 1000},
        }
        assert len(plan["production_timeline"]["tracks"][0]["clips"]) == 6
        assert len(plan["timeline_segments"]) == 6
        assert {segment["source_shot_code"] for segment in plan["timeline_segments"]}
        assert all(
            segment["source_script_block_codes"]
            for segment in plan["timeline_segments"]
        )
        assert (
            plan["render_profile"]["visual_asset_mode"]
            == "baseline_verified_video_assets"
        )
        assert plan["material_selection_decision_code"].startswith("DEC-")
        job = VideoProductionRepository(connection).get_by_code(plan["video_job_code"])
        assert job is not None
        assert job["shot_list"]["production_timeline"] == plan["production_timeline"]
        assert all(
            shot["source_script_block_codes"] for shot in job["shot_list"]["shots"]
        )

        clips = plan["production_timeline"]["tracks"][0]["clips"]
        subtitles = next(
            track["clips"]
            for track in plan["production_timeline"]["tracks"]
            if track["track_kind"] == "subtitle"
        )
        durations = [8_000, 9_000, 9_000, 10_000, 9_000, 10_000]
        updated = FunctionalVideoService(connection).update_timeline(
            plan["plan_code"],
            {
                "expected_revision": 1,
                "video_clips": [
                    {
                        "clip_code": clip["clip_code"],
                        "duration_ms": duration,
                        "transition": "fade"
                        if index == 0
                        else "fade_out"
                        if index == 5
                        else "cut",
                    }
                    for index, (clip, duration) in enumerate(
                        zip(clips, durations, strict=True)
                    )
                ],
                "subtitle_clips": [
                    {
                        "clip_code": clip["clip_code"],
                        "subtitle_text": f"Edited {index}",
                        "headline_text": f"Headline {index}",
                    }
                    for index, clip in enumerate(subtitles)
                ],
            },
            actor_id="test-operator",
        )
        assert updated is not None
        assert updated["timeline_revision"] == 2
        assert len(updated["timeline_segments"]) == 6
        assert {
            segment["timeline_start_ms"] for segment in updated["timeline_segments"]
        } == {
            0,
            8_000,
            17_000,
            26_000,
            36_000,
            45_000,
        }
        assert updated["production_timeline"]["global_end_ms"] == 55_000
        assert (
            updated["production_timeline"]["tracks"][0]["clips"][0]["transition"]
            == "fade"
        )
        assert (
            updated["production_timeline"]["tracks"][2]["clips"][0]["subtitle_text"]
            == "Edited 0"
        )
        with pytest.raises(DomainValidationError) as stale:
            FunctionalVideoService(connection).update_timeline(
                plan["plan_code"],
                {
                    "expected_revision": 1,
                    "video_clips": [
                        {"clip_code": clip["clip_code"], "duration_ms": 9_000}
                        for clip in clips
                    ],
                },
                actor_id="test-operator",
            )
        assert stale.value.code == "VIDEO_TIMELINE_REVISION_CONFLICT"
        connection.rollback()

        restored = FunctionalVideoService(connection).restore_timeline_revision(
            plan["plan_code"],
            1,
            expected_revision=2,
            actor_id="test-operator",
        )
        assert restored is not None
        assert restored["timeline_revision"] == 3
        assert (
            restored["production_timeline"]["tracks"][0]["clips"][0]["transition"]
            == clips[0]["transition"]
        )
        assert (
            restored["production_timeline"]["tracks"][2]["clips"][0]["subtitle_text"]
            == subtitles[0]["subtitle_text"]
        )

        branch = FunctionalVideoService(connection).branch_plan(
            plan["plan_code"], {"title": "Video branch"}, actor_id="test-operator"
        )
        assert branch is not None
        assert branch["plan_code"] != plan["plan_code"]
        assert branch["video_job_code"] != plan["video_job_code"]
        assert branch["title"] == "Video branch"
        assert branch["production_timeline"] == restored["production_timeline"]
        assert branch["render_profile"]["branched_from_plan_code"] == plan["plan_code"]
        assert branch["job_status"] == "queued"
        assert branch["material_selection_decision_code"].startswith("DEC-")
        assert (
            branch["material_selection_decision_code"]
            != plan["material_selection_decision_code"]
        )
        branch_job = VideoProductionRepository(connection).get_by_code(
            branch["video_job_code"]
        )
        assert branch_job is not None
        assert branch_job["edit_locked"] is True
        assert (
            VideoProductionRepository(connection).claim_next(
                "timeline-edit-worker", 60, job_code=branch["video_job_code"]
            )
            is None
        )
        branch_clips = branch["production_timeline"]["tracks"][0]["clips"]
        edited_branch = FunctionalVideoService(connection).update_timeline(
            branch["plan_code"],
            {
                "expected_revision": 1,
                "video_clips": [
                    {
                        "clip_code": clip["clip_code"],
                        "duration_ms": clip["timeline_range"]["duration_ms"],
                        "transition": clip.get("transition", "cut"),
                    }
                    for clip in branch_clips
                ],
            },
            actor_id="test-operator",
        )
        assert edited_branch is not None
        assert (
            VideoProductionRepository(connection).get_by_code(branch["video_job_code"])[
                "edit_locked"
            ]
            is False
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM video_production_stages WHERE job_code = %s ORDER BY stage_order",
                (plan["video_job_code"],),
            )
            assert [row[0] for row in cursor.fetchall()] == [
                "succeeded",
                "succeeded",
                "succeeded",
                "pending",
                "pending",
                "pending",
                "pending",
                "pending",
            ]
            cursor.execute(
                "SELECT production_variant_revision_id IS NOT NULL FROM video_production_jobs WHERE job_code = %s",
                (plan["video_job_code"],),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                """SELECT decision_type, decision_payload->>'plan_code', source_revision_refs
                   FROM functional_decision_logs
                   WHERE decision_code = %s""",
                (plan["material_selection_decision_code"],),
            )
            selection_decision = cursor.fetchone()
            assert selection_decision[0] == "rendered_video_material_selection"
            assert selection_decision[1] == plan["plan_code"]
            assert any(
                ref["relation_type"] == "selection_output_variant"
                for ref in selection_decision[2]
            )
            cursor.execute(
                "SELECT count(*) FROM functional_video_timeline_revisions WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)",
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == 3
            cursor.execute(
                """SELECT count(*) FROM functional_video_timeline_segments
                   WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)""",
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == 18
            cursor.execute(
                """SELECT count(*) FROM functional_video_timeline_segments
                   WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)
                     AND jsonb_array_length(source_script_block_codes) > 0""",
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == 18
            cursor.execute(
                """SELECT count(*) FROM shot_projection_links
                   WHERE target_type = 'timeline_segment'
                     AND target_code LIKE %s""",
                (f"VTLSEG-{plan['plan_code']}-%",),
            )
            assert cursor.fetchone()[0] == 18
            cursor.execute(
                """SELECT timeline_revision, transition
                   FROM functional_video_timeline_segments
                   WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)
                     AND clip_code = 'SHOT-01'
                   ORDER BY timeline_revision""",
                (plan["plan_code"],),
            )
            assert cursor.fetchall() == [(1, "cut"), (2, "fade"), (3, "cut")]


def test_functional_video_timeline_segments_link_registered_voice_and_subtitle_artifacts() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        generated = _generated_project(connection, suffix)
        service = FunctionalVideoService(connection)
        plan = service.create_plan(
            {"project_code": generated["project_code"], "target_duration_seconds": 55},
            actor_id="test-operator",
        )
        repository = VideoProductionRepository(connection)
        claimed = repository.claim_next(
            "timeline-artifact-worker", 60, job_code=plan["video_job_code"]
        )
        assert claimed is not None
        assert claimed["job_code"] == plan["video_job_code"]
        lease_token = claimed["lease_token"]
        job_code = plan["video_job_code"]

        assert (
            repository.start_stage(
                job_code, "asset_selection", "timeline-artifact-worker", lease_token
            )
            is not None
        )
        assert (
            repository.complete_stage(
                job_code,
                "asset_selection",
                {
                    "shot_assets": [
                        {
                            "shot_index": index,
                            "asset_code": "AG-VID-FIXTURE",
                            "relative_path": "video/fixture.mp4",
                            "source_start_seconds": 0.0,
                            "source_end_seconds": 6.0,
                            "playback_rate": 1.0,
                            "stream_time_base": "1/90000",
                            "stream_start_pts": "3600",
                            "stream_start_time_seconds": 0.04,
                            "stream_frame_rate": "30000/1001",
                        }
                        for index in range(6)
                    ]
                },
                [
                    {
                        "artifact_key": "asset_plan",
                        "relative_path": f"{job_code}/attempt-1/assets/plan.json",
                        "mime_type": "application/json",
                        "file_size": 128,
                        "checksum_sha256": "9" * 64,
                    }
                ],
                "timeline-artifact-worker",
                lease_token,
            )
            is not None
        )

        voice_segments = [
            {
                "shot_index": index,
                "shot_code": f"SHOT-{index + 1:02d}",
                "relative_path": f"{job_code}/attempt-1/voice/segment-{index + 1:02d}.wav",
                "checksum_sha256": "a" * 64,
                "voice": "fixture-voice",
                "gain_db": 0.0,
                "target_duration_seconds": 8.0,
            }
            for index in range(6)
        ]
        assert (
            repository.start_stage(
                job_code, "voice_synthesis", "timeline-artifact-worker", lease_token
            )
            is not None
        )
        assert (
            repository.complete_stage(
                job_code,
                "voice_synthesis",
                {"segments": voice_segments},
                [
                    {
                        "artifact_key": "voice",
                        "relative_path": f"{job_code}/attempt-1/voice/manifest.json",
                        "mime_type": "application/json",
                        "file_size": 128,
                        "checksum_sha256": "b" * 64,
                    }
                ],
                "timeline-artifact-worker",
                lease_token,
            )
            is not None
        )

        subtitle_events = [
            {
                "kind": "caption",
                "shot_index": index,
                "start_seconds": index * 8.0,
                "end_seconds": (index + 1) * 8.0,
            }
            for index in range(6)
        ]
        assert (
            repository.start_stage(
                job_code, "subtitle_generation", "timeline-artifact-worker", lease_token
            )
            is not None
        )
        assert (
            repository.complete_stage(
                job_code,
                "subtitle_generation",
                {"events": subtitle_events, "text_complete": True},
                [
                    {
                        "artifact_key": "subtitles",
                        "relative_path": f"{job_code}/attempt-1/subtitles/subtitles.ass",
                        "mime_type": "text/x-ssa",
                        "file_size": 128,
                        "checksum_sha256": "c" * 64,
                    }
                ],
                "timeline-artifact-worker",
                lease_token,
            )
            is not None
        )

        assert (
            repository.start_stage(
                job_code, "rendering", "timeline-artifact-worker", lease_token
            )
            is not None
        )
        assert (
            repository.complete_stage(
                job_code,
                "rendering",
                {
                    "manifest_fingerprint": "d" * 64,
                    "outputs": {"poster": {"at_seconds": 2.0}},
                },
                [
                    {
                        "artifact_key": "render_manifest",
                        "relative_path": f"{job_code}/attempt-1/render/manifest.json",
                        "mime_type": "application/json",
                        "file_size": 128,
                        "checksum_sha256": "e" * 64,
                    },
                    {
                        "artifact_key": "video",
                        "relative_path": f"{job_code}/attempt-1/render/final.mp4",
                        "mime_type": "video/mp4",
                        "file_size": 128,
                        "checksum_sha256": "f" * 64,
                    },
                    {
                        "artifact_key": "poster",
                        "relative_path": f"{job_code}/attempt-1/render/poster.jpg",
                        "mime_type": "image/jpeg",
                        "file_size": 128,
                        "checksum_sha256": "0" * 64,
                    },
                ],
                "timeline-artifact-worker",
                lease_token,
            )
            is not None
        )

        refreshed = service.get_plan(plan["plan_code"])
        assert refreshed is not None
        assert all(
            {
                reference["artifact_role"]
                for reference in segment["execution_artifact_refs"]
            }
            >= {
                "source_media_probe",
                "voice_segment",
                "subtitle_track",
                "render_manifest",
                "rendered_video",
            }
            for segment in refreshed["timeline_segments"]
        )
        assert "poster" in {
            reference["artifact_role"]
            for reference in refreshed["timeline_segments"][0][
                "execution_artifact_refs"
            ]
        }
        assert all(
            "poster"
            not in {
                reference["artifact_role"]
                for reference in segment["execution_artifact_refs"]
            }
            for segment in refreshed["timeline_segments"][1:]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT count(*)
                   FROM functional_video_timeline_segment_execution_artifacts AS link
                   JOIN functional_video_timeline_segments AS segment
                     ON segment.id = link.timeline_segment_id
                   WHERE segment.plan_id = (
                       SELECT id FROM functional_video_plans WHERE plan_code = %s
                   )""",
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == 31


def test_functional_video_plan_freezes_selected_downloaded_maitu_library_videos() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        generated = _generated_project(connection, suffix)
        asset = AssetRepository(connection).create(
            {
                "asset_type": "VID",
                "title": f"Local clip {suffix}",
                "original_filename": f"local-{suffix}.mp4",
                "media_kind": "video",
                "material_roles": ["supporting_video"],
                "execution_capability": "maitu_bound",
                "local_relative_path": f"video/local-{suffix}.mp4",
                "checksum_sha256": "a" * 64,
                "rights_status": "approved",
                "rights_note": "Test-owned downloaded Maitu fixture",
            }
        )
        asset_file = AssetRepository(connection).create_file_record(
            asset["asset_code"],
            {
                "file_role": "original",
                "bucket_name": "assetgraph-test",
                "object_key": f"assets/{asset['asset_code']}/original/local-{suffix}.mp4",
                "mime_type": "video/mp4",
                "file_size": 128,
                "checksum_sha256": "a" * 64,
                "source_relative_path": f"video/local-{suffix}.mp4",
                "storage_status": "stored",
            },
        )
        assert asset_file is not None

        plan = FunctionalVideoService(connection).create_plan(
            {
                "project_code": generated["project_code"],
                "target_duration_seconds": 55,
                "visual_asset_codes": [asset["asset_code"]],
            },
            actor_id="test-operator",
        )

        assert (
            plan["render_profile"]["visual_asset_mode"]
            == "asset_library_local_video_assets"
        )
        assert plan["render_profile"]["visual_asset_codes"] == [asset["asset_code"]]
        assert plan["render_profile"]["visual_assets"] == [
            {"asset_code": asset["asset_code"], "checksum_sha256": "a" * 64}
        ]
        assert {
            clip["source_range"]["asset_code"]
            for clip in plan["production_timeline"]["tracks"][0]["clips"]
        } == {asset["asset_code"]}
        assert all(
            len(segment["source_asset_file_refs"]) == 1
            for segment in plan["timeline_segments"]
        )
        for segment in plan["timeline_segments"]:
            reference = segment["source_asset_file_refs"][0]
            assert {
                key: reference[key]
                for key in (
                    "asset_file_id",
                    "relation_role",
                    "asset_code",
                    "file_role",
                    "bucket_name",
                    "object_key",
                    "source_relative_path",
                    "mime_type",
                    "file_size",
                    "checksum_sha256",
                )
            } == {
                "asset_file_id": asset_file["id"],
                "relation_role": "source_video",
                "asset_code": asset["asset_code"],
                "file_role": "original",
                "bucket_name": "assetgraph-test",
                "object_key": f"assets/{asset['asset_code']}/original/local-{suffix}.mp4",
                "source_relative_path": f"video/local-{suffix}.mp4",
                "mime_type": "video/mp4",
                "file_size": 128,
                "checksum_sha256": "a" * 64,
            }
            assert reference["created_at"] is not None
        connection.rollback()


def test_functional_video_plan_freezes_local_video_group_and_published_pack_expansion() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        generated = _generated_project(connection, suffix)
        assets = AssetRepository(connection)
        library = MaterialLibraryRepository(connection)
        grouped_asset = assets.create(
            {
                "asset_type": "VID",
                "title": f"Grouped clip {suffix}",
                "original_filename": f"grouped-{suffix}.mp4",
                "media_kind": "video",
                "material_roles": ["supporting_video"],
                "execution_capability": "local_only",
                "local_relative_path": f"video/grouped-{suffix}.mp4",
                "checksum_sha256": "b" * 64,
            }
        )
        direct_asset = assets.create(
            {
                "asset_type": "VID",
                "title": f"Direct clip {suffix}",
                "original_filename": f"direct-{suffix}.mp4",
                "media_kind": "video",
                "material_roles": ["supporting_video"],
                "execution_capability": "local_only",
                "local_relative_path": f"video/direct-{suffix}.mp4",
                "checksum_sha256": "c" * 64,
            }
        )
        music_asset = assets.create(
            {
                "asset_type": "AUD",
                "title": f"Background music {suffix}",
                "original_filename": f"music-{suffix}.mp3",
                "media_kind": "audio",
                "material_roles": ["background_music"],
                "execution_capability": "local_only",
                "local_relative_path": f"audio/music-{suffix}.mp3",
                "checksum_sha256": "d" * 64,
            }
        )
        sound_effect_asset = assets.create(
            {
                "asset_type": "AUD",
                "title": f"Sound effect {suffix}",
                "original_filename": f"effect-{suffix}.mp3",
                "media_kind": "audio",
                "material_roles": ["sound_effect"],
                "execution_capability": "local_only",
                "local_relative_path": f"audio/effect-{suffix}.mp3",
                "checksum_sha256": "a" * 64,
            }
        )
        sticker_asset = assets.create(
            {
                "asset_type": "IMG",
                "title": f"Product sticker {suffix}",
                "original_filename": f"product-{suffix}.png",
                "media_kind": "image",
                "material_roles": ["product_display"],
                "execution_capability": "local_only",
                "local_relative_path": f"image/product-{suffix}.png",
                "checksum_sha256": "e" * 64,
            }
        )
        logo_asset = assets.create(
            {
                "asset_type": "IMG",
                "title": f"Brand logo {suffix}",
                "original_filename": f"brand-{suffix}.png",
                "media_kind": "image",
                "material_roles": ["brand_title"],
                "execution_capability": "local_only",
                "local_relative_path": f"image/brand-{suffix}.png",
                "checksum_sha256": "f" * 64,
            }
        )
        group = library.create_group(
            {
                "title": f"Video group {suffix}",
                "asset_codes": [grouped_asset["asset_code"]],
            }
        )
        pack = library.create_pack(
            {
                "title": f"Video pack {suffix}",
                "role": "supporting_video",
                "entries": [
                    {
                        "selection_kind": "group",
                        "selection_code": group["group_code"],
                        "mode": "required",
                        "min_occurrences": 1,
                    }
                ],
            }
        )
        published = library.publish_pack(pack["pack_code"])
        assert published is not None

        plan = FunctionalVideoService(connection).create_plan(
            {
                "project_code": generated["project_code"],
                "target_duration_seconds": 55,
                "visual_asset_codes": [direct_asset["asset_code"]],
                "visual_group_codes": [group["group_code"]],
                "visual_material_pack_codes": [pack["pack_code"]],
                "brand_logo_asset_code": logo_asset["asset_code"],
                "product_sticker_asset_code": sticker_asset["asset_code"],
                "background_music_asset_code": music_asset["asset_code"],
                "background_music_gain_db": -20,
                "sound_effect_asset_code": sound_effect_asset["asset_code"],
                "sound_effect_gain_db": -9,
            },
            actor_id="test-operator",
        )

        selection = plan["render_profile"]["visual_selection"]
        assert plan["render_profile"]["visual_asset_codes"] == [
            direct_asset["asset_code"],
            grouped_asset["asset_code"],
        ]
        assert selection["direct_asset_codes"] == [direct_asset["asset_code"]]
        assert selection["group_refs"] == [
            {
                "group_code": group["group_code"],
                "title": group["title"],
                "asset_codes": [grouped_asset["asset_code"]],
            }
        ]
        assert selection["material_pack_refs"][0]["pack_code"] == pack["pack_code"]
        assert selection["material_pack_refs"][0]["revision_number"] == 1
        assert selection["selection_sources"][grouped_asset["asset_code"]] == [
            {"kind": "asset_group", "code": group["group_code"]},
            {"kind": "material_pack", "code": pack["pack_code"]},
        ]
        assert plan["render_profile"]["background_music"] == {
            "asset_code": music_asset["asset_code"],
            "checksum_sha256": "d" * 64,
            "gain_db": -20.0,
        }
        assert plan["render_profile"]["sound_effect"] == {
            "asset_code": sound_effect_asset["asset_code"],
            "checksum_sha256": "a" * 64,
            "gain_db": -9.0,
        }
        assert plan["render_profile"]["product_sticker"] == {
            "asset_code": sticker_asset["asset_code"],
            "checksum_sha256": "e" * 64,
        }
        assert plan["material_snapshot_ref"]["product_sticker"] == {
            "asset_code": sticker_asset["asset_code"],
            "relative_path": f"image/product-{suffix}.png",
            "checksum_sha256": "e" * 64,
            "constraint_profile": None,
        }
        assert plan["render_profile"]["brand_logo"] == {
            "asset_code": logo_asset["asset_code"],
            "checksum_sha256": "f" * 64,
        }
        assert plan["material_snapshot_ref"]["brand_logo"] == {
            "asset_code": logo_asset["asset_code"],
            "relative_path": f"image/brand-{suffix}.png",
            "checksum_sha256": "f" * 64,
            "constraint_profile": None,
        }
        assert plan["material_snapshot_ref"]["asset_codes"][-4:] == [
            music_asset["asset_code"],
            sound_effect_asset["asset_code"],
            sticker_asset["asset_code"],
            logo_asset["asset_code"],
        ]
        assert plan["production_timeline"]["tracks"][0]["clips"][0]["audio_roles"] == [
            "sound_effect"
        ]
        audio_track = next(
            track
            for track in plan["production_timeline"]["tracks"]
            if track["track_kind"] == "audio"
        )
        bgm_clip = audio_track["clips"][-1]
        assert {
            key: bgm_clip[key]
            for key in ("clip_code", "timeline_range", "asset_code", "gain_db")
        } == {
            "clip_code": "BGM-01",
            "timeline_range": {"start_ms": 0, "duration_ms": 55_000},
            "asset_code": music_asset["asset_code"],
            "gain_db": -20.0,
        }
        assert bgm_clip["timeline_time_range"] == {
            "start_time": {"value": 0, "rate": 1_000},
            "duration": {"value": 55_000, "rate": 1_000},
        }

        library.replace_group_members(group["group_code"], [direct_asset["asset_code"]])
        frozen = FunctionalVideoService(connection).get_plan(plan["plan_code"])
        assert frozen is not None
        assert frozen["render_profile"]["visual_selection"] == selection
        connection.rollback()


def test_functional_video_plan_can_use_the_fixed_content_chain_of_a_live_room_plan() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        generated = _generated_project(connection, suffix)
        assets = AssetRepository(connection)
        selected = [
            assets.create(
                {
                    "asset_type": "IMG",
                    "title": f"{role} {suffix}",
                    "original_filename": f"{role}-{suffix}.png",
                    "media_kind": "image",
                    "material_roles": [role],
                    "execution_capability": "maitu_bound",
                    "rights_status": "approved",
                    "rights_note": "Test-owned fixture",
                }
            )
            for role in ("digital_human", "background", "promotion_text")
        ]
        live_room = FunctionalLiveRoomService(connection).create_plan(
            {
                "project_code": generated["project_code"],
                "target_live_room_id": f"room-{suffix}",
                "expected_title": "Fixed live-room source",
                "asset_codes": [asset["asset_code"] for asset in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )

        video = FunctionalVideoService(connection).create_plan(
            {
                "live_room_plan_code": live_room["plan_code"],
                "target_duration_seconds": 55,
            },
            actor_id="test-operator",
        )

        assert video["project_code"] == generated["project_code"]
        assert video["job_status"] == "queued"
        assert (
            video["render_profile"]["source_live_room_plan_code"]
            == live_room["plan_code"]
        )
        inherited = video["material_snapshot_ref"][
            "inherited_live_room_material_snapshot"
        ]
        assert inherited["live_room_plan_code"] == live_room["plan_code"]
        assert inherited["production_variant_code"] == live_room["variant_code"]
        assert inherited["production_variant_revision"] == 1
        assert (
            inherited["asset_codes"]
            == live_room["build_plan"]["inventory_snapshot"]["asset_codes"]
        )
        assert inherited["snapshot"] == live_room["build_plan"]["inventory_snapshot"]
        assert video["render_profile"]["inherited_live_room_material_snapshot"] == {
            key: value for key, value in inherited.items() if key != "snapshot"
        }


def test_functional_video_release_candidate_freezes_a_qc_passed_plan() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        content = FunctionalContentService(connection)
        project = content.create_project(
            {
                "title": f"Release video {suffix}",
                "generation_goal": "Explain a product choice in a short vertical video",
                "theme": "Release candidate",
                "story": "Show the verified rendered output.",
                "must_include": [],
                "must_avoid": [],
                "fact_card_codes": [],
                "secondary_template_codes": [],
            },
            actor_id="test-operator",
        )
        content.confirm_project(
            project["project_code"], expected_revision=1, actor_id="test-operator"
        )
        content.parse_design_brief(
            project["project_code"],
            expected_revision=1,
            raw_input="Create a release fixture.",
            actor_id="test-operator",
        )
        content.confirm_design_brief(
            project["project_code"], expected_revision=1, actor_id="test-operator"
        )
        generated = content.generate_chain(
            project["project_code"], actor_id="test-operator"
        )
        service = FunctionalVideoService(
            connection,
            release_signing_key=b"test-release-key",
            release_signing_key_id="test-key",
        )
        plan = service.create_plan(
            {"project_code": generated["project_code"], "target_duration_seconds": 55},
            actor_id="test-operator",
        )

        local_input_codes = {
            code: f"{code}-{suffix}"
            for code in (
                "MT-VID-0016",
                "MT-VID-0024",
                "MT-VID-0027",
                "MT-DEC-0003",
                "MT-DEC-0024",
            )
        }
        fixed_inputs = (
            (
                "MT-VID-0016",
                local_input_codes["MT-VID-0016"],
                f"fixture/video/{local_input_codes['MT-VID-0016']}.mov",
                "1" * 64,
                "VID",
            ),
            (
                "MT-VID-0024",
                local_input_codes["MT-VID-0024"],
                f"fixture/video/{local_input_codes['MT-VID-0024']}.mp4",
                "2" * 64,
                "VID",
            ),
            (
                "MT-VID-0027",
                local_input_codes["MT-VID-0027"],
                f"fixture/video/{local_input_codes['MT-VID-0027']}.mp4",
                "3" * 64,
                "VID",
            ),
            (
                "MT-DEC-0003",
                local_input_codes["MT-DEC-0003"],
                f"fixture/overlay/{local_input_codes['MT-DEC-0003']}.png",
                "4" * 64,
                "IMG",
            ),
            (
                "MT-DEC-0024",
                local_input_codes["MT-DEC-0024"],
                f"fixture/overlay/{local_input_codes['MT-DEC-0024']}.png",
                "5" * 64,
                "IMG",
            ),
        )
        assets = AssetRepository(connection)
        catalog_assets = [
            assets.create(
                {
                    "asset_type": asset_type,
                    "title": f"Release input {local_file_code} {suffix}",
                    "original_filename": relative_path.rsplit("/", 1)[-1],
                    "checksum_sha256": checksum,
                    "local_file_code": local_file_code,
                    "source_system": f"functional-video-release-{suffix}",
                    "rights_status": "approved",
                    "rights_note": "Test-owned rendered input fixture",
                }
            )
            for _rendered_code, local_file_code, relative_path, checksum, asset_type in fixed_inputs
        ]
        asset_plan = {
            "source": "fixed_maitu_asset_plan_v1",
            "asset_count": len(fixed_inputs),
            "assets": [
                {
                    "asset_code": rendered_code,
                    "local_file_code": local_file_code,
                    "relative_path": relative_path,
                    "checksum_sha256": checksum,
                }
                for rendered_code, local_file_code, relative_path, checksum, _asset_type in fixed_inputs
            ],
            "shot_assets": [
                {"asset_code": code}
                for code in ("MT-VID-0027", "MT-VID-0016", "MT-VID-0024")
            ],
            "overlays": {
                "brand_logo": fixed_inputs[3][2],
                "product_sticker": fixed_inputs[4][2],
            },
        }

        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE video_production_jobs
                   SET status = 'succeeded', current_stage = 'quality_check', progress_percent = 100,
                       asset_plan = %s, quality_report = %s, completed_at = now()
                   WHERE job_code = %s""",
                (
                    Jsonb(asset_plan),
                    Jsonb({"passed": True, "checks": {"video_stream": True}}),
                    plan["video_job_code"],
                ),
            )
            cursor.execute(
                """UPDATE video_production_stages
                   SET status = 'succeeded', completed_at = now()
                   WHERE job_code = %s""",
                (plan["video_job_code"],),
            )
            cursor.execute(
                "SELECT id FROM video_production_stages WHERE job_code = %s AND stage_name = 'rendering'",
                (plan["video_job_code"],),
            )
            rendering_stage_id = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO video_production_artifacts
                   (job_id, stage_id, job_code, artifact_key, relative_path, mime_type, file_size, checksum_sha256)
                   SELECT id, %s, job_code, 'video', 'fixture/attempt-1/video.mp4', 'video/mp4', 128, %s
                   FROM video_production_jobs WHERE job_code = %s""",
                (rendering_stage_id, "b" * 64, plan["video_job_code"]),
            )
        connection.commit()

        released = service.create_release_candidate(
            plan["plan_code"], actor_id="test-operator"
        )

        assert released["release"] is not None
        assert released["release"]["status"] == "candidate"
        assert released["release_snapshot_artifact_code"]
        release = ReleaseRepository(connection).get_release(
            released["release"]["release_code"]
        )
        assert release is not None
        rights_snapshot = release["manifest"]["rights_snapshot"]
        assert rights_snapshot["status"] == "valid"
        assert rights_snapshot["asset_count"] == 5
        assert set(rights_snapshot["asset_codes"]) == {
            asset["asset_code"] for asset in catalog_assets
        }
        assert {
            code
            for asset in rights_snapshot["assets"]
            for code in asset["rendered_input_codes"]
        } == {code for item in fixed_inputs for code in item[:2]}
        gates = release["manifest"]["quality_snapshot"]["gates"]
        assert [gate["code"] for gate in gates] == [
            "GATE_VIDEO_RENDER_SUCCEEDED",
            "GATE_VIDEO_QC",
            "GATE_VIDEO_ASSET_RIGHTS",
        ]
        assert all(gate["status"] == "pass" for gate in gates)
        assert all("AUTHORIZATION" not in gate["code"] for gate in gates)

        validated = service._release_service().validate_candidate(
            released["release"]["release_code"],
            actor_id="test-release-validator",
        )
        assert validated["status"] == "awaiting_approval"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM functional_video_plan_release_snapshots WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)",
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == 1
