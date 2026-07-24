from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.errors import DomainValidationError
from app.services.functional_content import FunctionalContentService
from app.services.functional_videos import FunctionalVideoService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_functional_video_plan_seeds_content_stages_and_queues_renderer() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
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
        content.confirm_project(project["project_code"], expected_revision=1, actor_id="test-operator")
        content.parse_design_brief(
            project["project_code"],
            expected_revision=1,
            raw_input="Create the project baseline before the rendered-video branch.",
            actor_id="test-operator",
        )
        content.confirm_design_brief(project["project_code"], expected_revision=1, actor_id="test-operator")
        generated = content.generate_chain(project["project_code"], actor_id="test-operator")
        plan = FunctionalVideoService(connection).create_plan(
            {"project_code": generated["project_code"], "target_duration_seconds": 55},
            actor_id="test-operator",
        )

        assert plan["job_status"] == "queued"
        assert plan["current_stage"] == "asset_selection"
        assert plan["progress_percent"] == 37
        assert plan["production_timeline"]["schema_version"] == "otio-compatible-production-timeline.v1"
        assert len(plan["production_timeline"]["tracks"][0]["clips"]) == 6
        assert plan["render_profile"]["visual_asset_mode"] == "baseline_verified_video_assets"

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
                        "transition": "fade" if index == 0 else "fade_out" if index == 5 else "cut",
                    }
                    for index, (clip, duration) in enumerate(zip(clips, durations, strict=True))
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
        assert updated["production_timeline"]["global_end_ms"] == 55_000
        assert updated["production_timeline"]["tracks"][0]["clips"][0]["transition"] == "fade"
        assert updated["production_timeline"]["tracks"][2]["clips"][0]["subtitle_text"] == "Edited 0"
        with pytest.raises(DomainValidationError) as stale:
            FunctionalVideoService(connection).update_timeline(
                plan["plan_code"],
                {"expected_revision": 1, "video_clips": [{"clip_code": clip["clip_code"], "duration_ms": 9_000} for clip in clips]},
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
        assert restored["production_timeline"]["tracks"][0]["clips"][0]["transition"] == clips[0]["transition"]
        assert restored["production_timeline"]["tracks"][2]["clips"][0]["subtitle_text"] == subtitles[0]["subtitle_text"]

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

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM video_production_stages WHERE job_code = %s ORDER BY stage_order",
                (plan["video_job_code"],),
            )
            assert [row[0] for row in cursor.fetchall()] == ["succeeded", "succeeded", "succeeded", "pending", "pending", "pending", "pending", "pending"]
            cursor.execute(
                "SELECT production_variant_revision_id IS NOT NULL FROM video_production_jobs WHERE job_code = %s",
                (plan["video_job_code"],),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute("SELECT count(*) FROM functional_video_timeline_revisions WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)", (plan["plan_code"],))
            assert cursor.fetchone()[0] == 3


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
        content.confirm_project(project["project_code"], expected_revision=1, actor_id="test-operator")
        content.parse_design_brief(project["project_code"], expected_revision=1, raw_input="Create a release fixture.", actor_id="test-operator")
        content.confirm_design_brief(project["project_code"], expected_revision=1, actor_id="test-operator")
        generated = content.generate_chain(project["project_code"], actor_id="test-operator")
        service = FunctionalVideoService(connection, release_signing_key=b"test-release-key", release_signing_key_id="test-key")
        plan = service.create_plan({"project_code": generated["project_code"], "target_duration_seconds": 55}, actor_id="test-operator")

        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE video_production_jobs
                   SET status = 'succeeded', current_stage = 'quality_check', progress_percent = 100,
                       quality_report = %s, completed_at = now()
                   WHERE job_code = %s""",
                (Jsonb({"passed": True, "checks": {"video_stream": True}}), plan["video_job_code"]),
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

        released = service.create_release_candidate(plan["plan_code"], actor_id="test-operator")

        assert released["release"] is not None
        assert released["release"]["status"] == "candidate"
        assert released["release_snapshot_artifact_code"]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM functional_video_plan_release_snapshots WHERE plan_id = (SELECT id FROM functional_video_plans WHERE plan_code = %s)",
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == 1
