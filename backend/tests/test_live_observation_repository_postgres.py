from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.repositories.live_observations import LiveObservationRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="ASSETGRAPH_TEST_DATABASE_URL is not configured",
)


ANALYSIS_SPECS = [
    {
        "analysis_type": "frame_sampling",
        "model_provider": "ffmpeg",
        "model_version": "frame-sampling.v1",
        "parameters": {"interval_seconds": 5},
    },
    {
        "analysis_type": "asr",
        "model_provider": "openai",
        "model_version": "transcribe-v1",
        "parameters": {"language": "zh"},
    },
    {
        "analysis_type": "ocr",
        "model_provider": "openai",
        "model_version": "vision-v1",
        "parameters": {"sample_times_seconds": [0]},
    },
    {
        "analysis_type": "layout_inference",
        "model_provider": "openai",
        "model_version": "vision-v1",
        "parameters": {"sample_times_seconds": [0]},
    },
]
AGGREGATION_SPEC = {
    "model_provider": "deepseek",
    "model_version": "deepseek-test",
}


def test_postgres_analysis_dag_work_heartbeat_retention_reclaim_and_stale_capture() -> None:
    schema = f"live_research_test_{uuid4().hex[:12]}"
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "024_live_research_observations.sql"
    ).read_text(encoding="utf-8")
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                cursor.execute(
                    sql.SQL("SET search_path TO {}, public").format(
                        sql.Identifier(schema)
                    )
                )
                cursor.execute(sql.SQL(migration))
                cursor.execute(sql.SQL(migration))
            connection.commit()
            repository = LiveObservationRepository(connection)
            target = repository.create_watch_target(
                {
                    "display_name": "integration room",
                    "room_url": "https://live.douyin.com/123456",
                }
            )
            claim = repository.claim_watch_target("capture-worker", 120)
            assert claim is not None
            session = repository.create_capture_session(
                {
                    "target_code": target["target_code"],
                    "worker_id": "capture-worker",
                    "claim_token": claim["claim_token"],
                    "lease_version": claim["lease_version"],
                    "recorder_engine": "streamcap",
                    "recorder_version": "v1.0.3",
                    "recorder_build_fingerprint": "ba9f1e6e6a861ad489e738cf5f5bee491774e972",
                    "event_adapter": "douyinlive",
                    "event_adapter_version": "v2.0.24",
                    "observed_started_at": datetime.now(UTC),
                    "metadata": {},
                }
            )
            chunk = repository.finalize_capture_chunk(
                session["session_code"],
                {
                    "part_index": 0,
                    "relative_path": f"raw-recordings/{session['session_code']}/chunks/chunk.ts",
                    "container_format": "mpegts",
                    "file_size": 100,
                    "checksum_sha256": "a" * 64,
                    "capture_started_at": datetime.now(UTC),
                    "capture_ended_at": datetime.now(UTC),
                    "decoded_duration_seconds": 60,
                    "stream_timing": {},
                    "media_probe": {},
                },
                analysis_specs=ANALYSIS_SPECS,
            )
            queued = repository.list_analysis_runs(
                session_code=session["session_code"],
                analysis_type=None,
                status=None,
                limit=20,
                offset=0,
            )
            assert {run["analysis_type"] for run in queued} == {
                "frame_sampling",
                "asr",
                "ocr",
                "layout_inference",
            }
            repository.finish_capture_session(
                session["session_code"],
                {
                    "status": "completed",
                    "observed_ended_at": datetime.now(UTC),
                    "metadata": {},
                },
                analysis_specs=ANALYSIS_SPECS,
                aggregation_spec=AGGREGATION_SPEC,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE live_capture_chunks
                    SET finalized_at = now() - interval '25 days',
                        retention_expires_at = now() + interval '5 days'
                    WHERE id = %s
                    """,
                    (chunk["id"],),
                )
            connection.commit()
            overview = repository.overview()
            assert overview["queued_analysis_runs"] == 4
            assert overview["expiring_capture_chunks"] == 1
            assert overview["draft_templates"] == 0
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE live_capture_chunks
                    SET finalized_at = now() - interval '31 days',
                        retention_expires_at = now() - interval '1 day'
                    WHERE id = %s
                    """,
                    (chunk["id"],),
                )
            connection.commit()
            assert repository.claim_retention_candidates("retention-worker", 300, 10) == []

            completed_count = 0
            exercised_manual_retry = False
            retried_run_code: str | None = None
            while completed_count < 4:
                run = repository.claim_analysis_run("analysis-worker", 60)
                assert run is not None
                assert run["analysis_type"] != "template_aggregation"
                if not exercised_manual_retry:
                    failed = repository.fail_work(
                        table="live_analysis_runs",
                        code_column="analysis_run_code",
                        code=run["analysis_run_code"],
                        worker_id="analysis-worker",
                        lease_token=run["lease_token"],
                        error_code="MISSING_OPENAI_KEY",
                        error_message="OPENAI_API_KEY is not configured",
                        retryable=False,
                    )
                    assert failed is not None
                    assert failed["status"] == "failed"
                    blocked_session = repository.get_capture_session(
                        session["session_code"], include_children=False
                    )
                    assert blocked_session is not None
                    assert blocked_session["analysis_blockers"][0]["error_code"] == (
                        "MISSING_OPENAI_KEY"
                    )
                    retried = repository.retry_analysis_run(
                        run["analysis_run_code"],
                        "analysis-worker",
                        "Credentials were configured",
                    )
                    assert retried is not None
                    assert retried["status"] == "queued"
                    assert len(retried["retry_history"]) == 1
                    retried_run_code = run["analysis_run_code"]
                    exercised_manual_retry = True
                    continue
                if run["analysis_run_code"] == retried_run_code:
                    assert run["attempt_count"] == 2
                if completed_count == 0:
                    assert (
                        repository.heartbeat_work(
                            table="live_analysis_runs",
                            code_column="analysis_run_code",
                            code=run["analysis_run_code"],
                            worker_id="wrong-worker",
                            lease_token=run["lease_token"],
                            lease_seconds=60,
                        )
                        is None
                    )
                    assert repository.heartbeat_work(
                        table="live_analysis_runs",
                        code_column="analysis_run_code",
                        code=run["analysis_run_code"],
                        worker_id="analysis-worker",
                        lease_token=run["lease_token"],
                        lease_seconds=60,
                    ) is not None
                completed = repository.complete_analysis_run(
                    run["analysis_run_code"],
                    "analysis-worker",
                    run["lease_token"],
                    {
                        "output_payload": {
                            "observations": [
                                {"kind": run["analysis_type"], "confidence": 0.9}
                            ]
                        },
                        "output_relative_path": (
                            f"templates/analysis/{run['analysis_run_code']}/result.json"
                        ),
                        "output_checksum_sha256": f"{completed_count + 1:064x}",
                    },
                    aggregation_spec=AGGREGATION_SPEC,
                )
                assert completed is not None
                completed_count += 1

            all_runs = repository.list_analysis_runs(
                session_code=session["session_code"],
                analysis_type=None,
                status=None,
                limit=20,
                offset=0,
            )
            aggregation = next(
                run for run in all_runs if run["analysis_type"] == "template_aggregation"
            )
            assert len(aggregation["parameters"]["observations"]) == 4
            claimed_aggregation = repository.claim_analysis_run("analysis-worker", 60)
            assert claimed_aggregation is not None
            assert claimed_aggregation["analysis_type"] == "template_aggregation"
            repository.complete_analysis_run(
                claimed_aggregation["analysis_run_code"],
                "analysis-worker",
                claimed_aggregation["lease_token"],
                {
                    "output_payload": {"template": {"canvas": {"width": 1080}}},
                    "output_relative_path": "templates/analysis/aggregation/result.json",
                    "output_checksum_sha256": "f" * 64,
                },
                aggregation_spec=AGGREGATION_SPEC,
            )

            first_retention = repository.claim_retention_candidates(
                "retention-worker-1", 30, 10
            )
            assert len(first_retention) == 1
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE live_capture_chunks
                    SET delete_claim_expires_at = now() - interval '1 second'
                    WHERE id = %s
                    """,
                    (chunk["id"],),
                )
            connection.commit()
            second_retention = repository.claim_retention_candidates(
                "retention-worker-2", 30, 10
            )
            assert len(second_retention) == 1
            assert second_retention[0]["claim_token"] != first_retention[0]["claim_token"]
            attempt_id = str(uuid4())
            assert (
                repository.complete_retention(
                    {
                        "entity_type": "capture_chunk",
                        "entity_id": chunk["id"],
                        "worker_id": "retention-worker-1",
                        "claim_token": first_retention[0]["claim_token"],
                        "deletion_attempt_id": str(uuid4()),
                        "deletion_reason": "retention_30_days",
                        "details": {},
                    }
                )
                is None
            )
            completion_payload = {
                "entity_type": "capture_chunk",
                "entity_id": chunk["id"],
                "worker_id": "retention-worker-2",
                "claim_token": second_retention[0]["claim_token"],
                "deletion_attempt_id": attempt_id,
                "deletion_reason": "retention_30_days",
                "details": {"file_was_present": False},
            }
            tombstone = repository.complete_retention(completion_payload)
            assert tombstone is not None
            assert repository.complete_retention(completion_payload) == tombstone

            template = repository.create_room_template(
                {"name": "integration template", "description": None}
            )
            revision_payload = {
                "source_session_code": session["session_code"],
                "contract_version": "layout-hypothesis.v1",
                "canvas": {"width": 1080, "height": 1920},
                "scenes": [{"scene_key": "main"}],
                "components": [],
                "audio_policy": {},
                "provenance": {"source_session_codes": [session["session_code"]]},
                "confidence": 0.8,
                "created_by": "integration-test",
                "content_fingerprint": "b" * 64,
            }
            first_revision = repository.create_room_template_revision(
                template["template_code"], revision_payload
            )
            publication_payload = {
                "reviewed_by": "integration-reviewer",
                "review_notes": "reviewed",
                "published_by": "integration-publisher",
                "publication_reason": "integration test",
            }
            projection = {
                "projection_contract": "maitu-layout-projection.v1",
                "projection_fingerprint": "c" * 64,
                "projection_ready": False,
                "manual_review_required": True,
                "blocking_reasons": ["integration"],
                "canvas": revision_payload["canvas"],
                "scenes": revision_payload["scenes"],
                "components": [],
                "audio_policy": {},
                "provenance": revision_payload["provenance"],
            }
            repository.publish_room_template_revision(
                template["template_code"],
                first_revision["revision_number"],
                publication_payload,
                projection,
            )
            second_revision = repository.create_room_template_revision(
                template["template_code"],
                {**revision_payload, "content_fingerprint": "d" * 64},
            )
            draft_template = repository.get_room_template(
                template["template_code"], include_revisions=True
            )
            assert draft_template is not None
            assert draft_template["status"] == "draft"
            assert draft_template["published_revision_number"] == 1
            assert draft_template["latest_revision_number"] == 2
            previous_projection = repository.get_room_template_projection(
                template["template_code"]
            )
            assert previous_projection is not None
            assert previous_projection["revision_number"] == 1
            repository.publish_room_template_revision(
                template["template_code"],
                second_revision["revision_number"],
                publication_payload,
                {**projection, "projection_fingerprint": "e" * 64},
            )
            republished = repository.get_room_template(
                template["template_code"], include_revisions=True
            )
            assert republished is not None
            assert republished["status"] == "published"
            assert republished["published_revision_number"] == 2

            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE live_watch_targets SET lease_expires_at = now() - interval '1 second'"
                )
            connection.commit()
            recovery_claim = repository.claim_watch_target("recovery-worker", 60)
            assert recovery_claim is not None
            stale_session = repository.create_capture_session(
                {
                    "target_code": target["target_code"],
                    "worker_id": "recovery-worker",
                    "claim_token": recovery_claim["claim_token"],
                    "lease_version": recovery_claim["lease_version"],
                    "recorder_engine": "streamcap",
                    "recorder_version": "v1.0.3",
                    "recorder_build_fingerprint": "ba9f1e6e6a861ad489e738cf5f5bee491774e972",
                    "event_adapter": "douyinlive",
                    "event_adapter_version": "v2.0.24",
                    "observed_started_at": datetime.now(UTC),
                    "metadata": {},
                }
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE live_watch_targets SET lease_expires_at = now() - interval '1 second'"
                )
            connection.commit()
            assert repository.claim_watch_target("next-worker", 60) is not None
            recovered = repository.get_capture_session(
                stale_session["session_code"], include_children=False
            )
            assert recovered is not None
            assert recovered["status"] == "abandoned"
            assert recovered["failure_code"] == "CAPTURE_LEASE_EXPIRED"
    finally:
        if DATABASE_URL:
            with psycopg.connect(DATABASE_URL) as cleanup:
                with cleanup.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(schema)
                        )
                    )
                cleanup.commit()
