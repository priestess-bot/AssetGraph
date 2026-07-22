from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.repositories.video_productions import VideoProductionRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_video_production_repository_persists_checkpoints_leases_and_retry_boundary() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "022_video_production_jobs.sql"
    ).read_text(encoding="utf-8")
    topic = f"integration-{uuid4().hex}"

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(migration)
        connection.commit()
        repository = VideoProductionRepository(connection)
        created = repository.create(
            {
                "topic": topic,
                "preset_code": "zhangyu_wine_demo_v1",
                "target_duration_seconds": 70,
            }
        )
        job_code = created["job_code"]
        try:
            assert job_code.startswith("AG-VJOB-")
            assert len(created["stages"]) == 8
            assert created["status"] == "queued"

            claimed = repository.claim_next("video-worker-a", 60)
            assert claimed is not None
            assert claimed["job_code"] == job_code
            lease_token = claimed["lease_token"]
            assert repository.renew_lease(job_code, "video-worker-a", lease_token, 60) is not None

            stage = repository.start_stage(
                job_code, "brief_generation", "video-worker-a", lease_token
            )
            assert stage is not None
            assert stage["status"] == "running"
            completed = repository.complete_stage(
                job_code,
                "brief_generation",
                {"title": "商业短视频底稿"},
                [
                    {
                        "artifact_key": "story_brief",
                        "relative_path": f"{job_code}/attempt-1/story-brief.json",
                        "mime_type": "application/json",
                        "file_size": 2,
                        "checksum_sha256": "a" * 64,
                        "metadata": {"contract": "story_brief_v1"},
                    }
                ],
                "video-worker-a",
                lease_token,
            )
            assert completed is not None
            assert completed["story_brief"] == {"title": "商业短视频底稿"}
            assert completed["progress_percent"] == 12

            assert repository.start_stage(
                job_code, "script_generation", "video-worker-a", lease_token
            ) is not None
            failed = repository.fail_stage(
                job_code,
                "script_generation",
                "script_failed",
                "script generation failed",
                "video-worker-a",
                lease_token,
            )
            assert failed is not None
            assert failed["status"] == "failed"

            retried = repository.retry(job_code)
            assert retried is not None
            assert retried["status"] == "queued"
            assert retried["attempt"] == 2
            assert retried["story_brief"] == {"title": "商业短视频底稿"}
            assert retried["script"] == {}
            assert retried["artifacts"][0]["artifact_key"] == "story_brief"
            stages = {stage["stage_name"]: stage for stage in retried["stages"]}
            assert stages["brief_generation"]["status"] == "succeeded"
            assert stages["brief_generation"]["attempt"] == 1
            assert stages["script_generation"]["status"] == "pending"
            assert stages["script_generation"]["attempt"] == 2

            claimed_again = repository.claim_next("video-worker-b", 60)
            assert claimed_again is not None
            assert claimed_again["job_code"] == job_code
            assert repository.renew_lease(
                job_code, "video-worker-a", lease_token, 60
            ) is None
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM video_production_jobs WHERE job_code = %s", (job_code,))
            connection.commit()


def test_quality_gate_failure_retries_from_rendering_and_discards_render_artifacts() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "022_video_production_jobs.sql"
    ).read_text(encoding="utf-8")
    topic = f"quality-retry-{uuid4().hex}"

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
        connection.commit()
        repository = VideoProductionRepository(connection)
        created = repository.create(
            {
                "topic": topic,
                "preset_code": "zhangyu_wine_demo_v1",
                "target_duration_seconds": 70,
            }
        )
        job_code = created["job_code"]
        try:
            claimed = repository.claim_next("quality-worker", 60)
            assert claimed is not None
            assert claimed["job_code"] == job_code
            lease_token = claimed["lease_token"]

            for stage_name in repository.STAGES:
                assert repository.start_stage(
                    job_code, stage_name, "quality-worker", lease_token
                ) is not None
                artifacts = []
                if stage_name == "brief_generation":
                    artifacts = [
                        {
                            "artifact_key": "story_brief",
                            "relative_path": f"{job_code}/attempt-1/story_brief.json",
                            "mime_type": "application/json",
                            "file_size": 2,
                            "checksum_sha256": "a" * 64,
                        }
                    ]
                elif stage_name == "rendering":
                    artifacts = [
                        {
                            "artifact_key": "video",
                            "relative_path": f"{job_code}/attempt-1/final.mp4",
                            "mime_type": "video/mp4",
                            "file_size": 100,
                            "checksum_sha256": "b" * 64,
                        }
                    ]
                elif stage_name == "quality_check":
                    artifacts = [
                        {
                            "artifact_key": "quality_report",
                            "relative_path": f"{job_code}/attempt-1/quality_report.json",
                            "mime_type": "application/json",
                            "file_size": 2,
                            "checksum_sha256": "c" * 64,
                        }
                    ]
                output = {"passed": False} if stage_name == "quality_check" else {"stage": stage_name}
                assert repository.complete_stage(
                    job_code,
                    stage_name,
                    output,
                    artifacts,
                    "quality-worker",
                    lease_token,
                ) is not None

            failed = repository.fail_job(
                job_code,
                "QUALITY_GATE_FAILED",
                "rendered video did not pass the quality gate",
                "quality-worker",
                lease_token,
            )
            assert failed is not None
            assert failed["status"] == "failed"
            assert all(stage["status"] == "succeeded" for stage in failed["stages"])

            retried = repository.retry(job_code)
            assert retried is not None
            assert retried["status"] == "queued"
            assert retried["current_stage"] == "rendering"
            assert retried["progress_percent"] == 75
            assert retried["attempt"] == 2
            assert retried["quality_report"] == {}
            stages = {stage["stage_name"]: stage for stage in retried["stages"]}
            assert stages["subtitle_generation"]["status"] == "succeeded"
            assert stages["rendering"]["status"] == "pending"
            assert stages["rendering"]["attempt"] == 2
            assert stages["quality_check"]["status"] == "pending"
            assert stages["quality_check"]["attempt"] == 2
            assert [artifact["artifact_key"] for artifact in retried["artifacts"]] == [
                "story_brief"
            ]
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM video_production_jobs WHERE job_code = %s", (job_code,))
            connection.commit()


def test_artifact_registration_requires_current_job_attempt_scope() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "022_video_production_jobs.sql"
    ).read_text(encoding="utf-8")
    topic = f"artifact-scope-{uuid4().hex}"

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
        connection.commit()
        repository = VideoProductionRepository(connection)
        created = repository.create(
            {
                "topic": topic,
                "preset_code": "zhangyu_wine_demo_v1",
                "target_duration_seconds": 70,
            }
        )
        job_code = created["job_code"]
        try:
            claimed = repository.claim_next("artifact-worker", 60)
            assert claimed is not None
            assert claimed["job_code"] == job_code
            lease_token = claimed["lease_token"]
            assert repository.start_stage(
                job_code, "brief_generation", "artifact-worker", lease_token
            ) is not None

            base_artifact = {
                "artifact_key": "story_brief",
                "mime_type": "application/json",
                "file_size": 2,
                "checksum_sha256": "d" * 64,
            }
            with pytest.raises(ValueError, match="current job attempt"):
                repository.complete_stage(
                    job_code,
                    "brief_generation",
                    {"title": "wrong job"},
                    [
                        {
                            **base_artifact,
                            "relative_path": "AG-VJOB-20260717-999999/attempt-1/story_brief.json",
                        }
                    ],
                    "artifact-worker",
                    lease_token,
                )
            with pytest.raises(ValueError, match="current job attempt"):
                repository.complete_stage(
                    job_code,
                    "brief_generation",
                    {"title": "wrong attempt"},
                    [
                        {
                            **base_artifact,
                            "relative_path": f"{job_code}/attempt-2/story_brief.json",
                        }
                    ],
                    "artifact-worker",
                    lease_token,
                )

            row = repository.get_by_code(job_code)
            assert row is not None
            assert row["artifacts"] == []
            assert row["stages"][0]["status"] == "running"
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM video_production_jobs WHERE job_code = %s", (job_code,))
            connection.commit()
