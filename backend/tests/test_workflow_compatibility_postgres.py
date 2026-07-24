from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.repositories.video_productions import VideoProductionRepository
from app.repositories.workflow_compatibility import WorkflowCompatibilityRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def _insert_workbench_run(connection: psycopg.Connection, suffix: str) -> str:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO maitu_workbench_product_fact_cards (
                fact_card_code, title, current_approved_version
            ) VALUES (%s, 'Compatibility fact', 1) RETURNING id
            """,
            (f"COMPAT-FACT-{suffix}",),
        )
        card_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO maitu_workbench_product_fact_card_versions (
                fact_card_id, fact_card_code, version_code, version_number,
                status, content, content_sha256, approved_by, approved_at
            ) VALUES (%s, %s, %s, 1, 'approved', '{}'::jsonb, %s, 'compatibility', now())
            RETURNING id
            """,
            (card_id, f"COMPAT-FACT-{suffix}", f"COMPAT-FACT-{suffix}-V001", "a" * 64),
        )
        version_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO maitu_workbench_inventory_sync_jobs (
                sync_job_code, status, request_fingerprint, completed_at
            ) VALUES (%s, 'succeeded', %s, now()) RETURNING id
            """,
            (f"COMPAT-SYNC-{suffix}", "b" * 64),
        )
        sync_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO maitu_workbench_inventory_snapshots (
                snapshot_code, sync_job_id, source_system, fingerprint_sha256,
                item_count, captured_at
            ) VALUES (%s, %s, 'maitu', %s, 0, now()) RETURNING id
            """,
            (f"COMPAT-SNAPSHOT-{suffix}", sync_id, "c" * 64),
        )
        snapshot_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            UPDATE maitu_workbench_inventory_sync_jobs
            SET snapshot_id = %s, snapshot_code = %s WHERE id = %s
            """,
            (snapshot_id, f"COMPAT-SNAPSHOT-{suffix}", sync_id),
        )
        run_code = f"COMPAT-WB-{suffix}"
        cursor.execute(
            """
            INSERT INTO maitu_workbench_runs (
                run_code, title, topic, status, fact_card_version_id,
                fact_card_version_code, inventory_snapshot_id, inventory_snapshot_code
            ) VALUES (%s, 'Compatibility run', 'Compatibility topic', 'ready', %s, %s, %s, %s)
            """,
            (
                run_code,
                version_id,
                f"COMPAT-FACT-{suffix}-V001",
                snapshot_id,
                f"COMPAT-SNAPSHOT-{suffix}",
            ),
        )
    connection.commit()
    return run_code


def _insert_capture_session(connection: psycopg.Connection, suffix: str) -> str:
    now = datetime.now(UTC)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO live_watch_targets (
                target_code, room_url, canonical_room_id, display_name
            ) VALUES (%s, %s, %s, 'Compatibility room') RETURNING id
            """,
            (f"COMPAT-TARGET-{suffix}", f"https://live.douyin.com/{suffix}", suffix),
        )
        target_id = cursor.fetchone()["id"]
        session_code = f"COMPAT-SESSION-{suffix}"
        cursor.execute(
            """
            INSERT INTO live_capture_sessions (
                session_code, target_id, target_code, recorder_engine,
                recorder_version, recorder_build_fingerprint, status,
                observed_started_at, observed_ended_at, ended_at
            ) VALUES (%s, %s, %s, 'streamcap', '1.0', %s, 'completed', %s, %s, %s)
            """,
            (
                session_code,
                target_id,
                f"COMPAT-TARGET-{suffix}",
                f"build-{suffix}",
                now - timedelta(minutes=1),
                now,
                now,
            ),
        )
    connection.commit()
    return session_code


def _insert_clip_and_analysis_runs(
    connection: psycopg.Connection,
    *,
    session_code: str,
    suffix: str,
) -> tuple[str, str]:
    clip_code = f"COMPAT-CLIP-{suffix}"
    analysis_code = f"COMPAT-ANALYSIS-{suffix}"
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT id FROM live_capture_sessions WHERE session_code = %s",
            (session_code,),
        )
        session_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO live_clip_jobs (
                clip_job_code, session_id, session_code,
                requested_start_seconds, requested_end_seconds,
                cut_mode, status, source_fingerprint
            ) VALUES (%s, %s, %s, 0, 30, 'exact_reencode', 'queued', %s)
            """,
            (clip_code, session_id, session_code, "d" * 64),
        )
        cursor.execute(
            """
            INSERT INTO live_analysis_runs (
                analysis_run_code, session_id, session_code, analysis_type,
                status, input_fingerprint, strategy_revision, parameters
            ) VALUES (%s, %s, %s, 'asr', 'queued', %s, %s, '{}'::jsonb)
            """,
            (
                analysis_code,
                session_id,
                session_code,
                "e" * 64,
                "test.compatibility-audit.v1",
            ),
        )
    connection.commit()
    return clip_code, analysis_code


def _insert_retry_task(connection: psycopg.Connection, suffix: str) -> str:
    retry_code = f"COMPAT-RETRY-{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO maitu_execution_retry_tasks (
                retry_task_code, plan_code, execution_code, failure_type,
                retry_instruction, status
            ) VALUES (%s, %s, %s, 'transient_ui', 'Retry the verified operation', 'pending')
            """,
            (retry_code, f"PLAN-{suffix}", f"EXEC-{suffix}"),
        )
    connection.commit()
    return retry_code


def _insert_legacy_asset(connection: psycopg.Connection, suffix: str) -> str:
    asset_code = f"CMPA-{suffix[:12]}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assets (
                asset_code, asset_type, title, original_filename, status,
                source_system, maitu_category, maitu_scene_name, maitu_scene_index,
                maitu_layer_name, maitu_layer_index, layer_left, layer_top,
                layer_width, layer_height, layer_z_index, duplicate_group,
                duplicate_rank, duplicate_count
            ) VALUES (
                %s, 'IMG', 'Compatibility asset', %s, 'ready',
                'legacy-import', 'product', 'Scene 1', 1, 'Product', 2,
                10, 20, 300, 400, 8, %s, 1, 2
            )
            """,
            (asset_code, f"{asset_code}.png", f"DUP-{suffix[:12]}"),
        )
    connection.commit()
    return asset_code


def _insert_layout_hypothesis(connection: psycopg.Connection, suffix: str) -> str:
    template_code = f"COMPAT-TPL-{suffix[:16]}"
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO live_room_templates (template_code, name)
            VALUES (%s, 'Compatibility layout') RETURNING id
            """,
            (template_code,),
        )
        template_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO live_room_template_revisions (
                template_id, template_code, revision_number, status,
                contract_version, canvas, scenes, components, audio_policy,
                provenance, confidence, review_status, content_fingerprint
            ) VALUES (
                %s, %s, 1, 'draft', 'layout-hypothesis.v1', '{}'::jsonb,
                '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb,
                0.5, 'pending', %s
            )
            """,
            (template_id, template_code, suffix * 2),
        )
    connection.commit()
    return template_code


def test_legacy_workbench_video_research_and_retry_are_read_only_workflow_projections() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        workbench_code = _insert_workbench_run(connection, suffix)
        video = VideoProductionRepository(connection).create(
            {"topic": f"Compatibility video {suffix}", "target_duration_seconds": 55}
        )
        capture_code = _insert_capture_session(connection, suffix)
        clip_code, analysis_code = _insert_clip_and_analysis_runs(
            connection,
            session_code=capture_code,
            suffix=suffix,
        )
        retry_code = _insert_retry_task(connection, suffix)

        repository = WorkflowCompatibilityRepository(connection)
        expected = {
            "maitu_workbench_run": f"LEGACY-WORKBENCH:{workbench_code}",
            "video_production_job": f"LEGACY-VIDEO:{video['job_code']}",
            "live_capture_session": f"LEGACY-CAPTURE:{capture_code}",
            "live_clip_job": f"LEGACY-CLIP:{clip_code}",
            "live_analysis_run": f"LEGACY-ANALYSIS:{analysis_code}",
            "maitu_retry_task": f"LEGACY-RETRY:{retry_code}",
        }
        for source_type, projection_code in expected.items():
            rows = repository.list_runs(source_type=source_type, limit=100)
            projection = next(
                row for row in rows if row["projection_run_code"] == projection_code
            )
            detail = repository.get_run(projection_code)
            assert projection["read_only"] is True
            assert projection["mapping_quality"] == "legacy_import"
            assert detail is not None and detail["steps"]
            assert all(step["read_only"] for step in detail["steps"])

        assert (
            repository.get_run(expected["maitu_workbench_run"])["status"]
            == "waiting_human"
        )
        assert (
            repository.get_run(expected["video_production_job"])["status"] == "queued"
        )
        assert (
            repository.get_run(expected["live_capture_session"])["status"]
            == "succeeded"
        )
        assert repository.get_run(expected["live_clip_job"])["status"] == "queued"
        assert repository.get_run(expected["live_analysis_run"])["status"] == "queued"
        assert repository.get_run(expected["maitu_retry_task"])["status"] == "queued"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM workflow_runs
                WHERE run_code = ANY(%s)
                """,
                (list(expected.values()),),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET status = 'failed', error_code = 'COMPATIBILITY_TEST_COMPLETE',
                    error_message = 'Compatibility projection fixture retired',
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = now(), updated_at = now()
                WHERE job_code = %s
                """,
                (video["job_code"],),
            )
            cursor.execute(
                """
                UPDATE maitu_execution_retry_tasks
                SET status = 'failed', retryable = false,
                    result_summary = 'Compatibility projection fixture retired',
                    updated_at = now()
                WHERE retry_task_code = %s
                """,
                (retry_code,),
            )
            cursor.execute(
                """
                UPDATE live_clip_jobs
                SET status = 'failed', error_code = 'COMPATIBILITY_TEST_COMPLETE',
                    error_message = 'Compatibility projection fixture retired',
                    completed_at = now(), updated_at = now()
                WHERE clip_job_code = %s
                """,
                (clip_code,),
            )
            cursor.execute(
                """
                UPDATE live_analysis_runs
                SET status = 'failed', error_code = 'COMPATIBILITY_TEST_COMPLETE',
                    error_message = 'Compatibility projection fixture retired',
                    completed_at = now(), updated_at = now()
                WHERE analysis_run_code = %s
                """,
                (analysis_code,),
            )
        connection.commit()


def test_legacy_asset_geometry_and_duplicate_group_remain_read_only_observations() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        asset_code = _insert_legacy_asset(connection, suffix)
        repository = WorkflowCompatibilityRepository(connection)

        projection = next(
            row
            for row in repository.list_asset_observations(limit=100)
            if row["asset_code"] == asset_code
        )
        assert projection["observed_geometry"] == {
            "left": 10.000,
            "top": 20.000,
            "width": 300.000,
            "height": 400.000,
            "z_index": 8,
        }
        assert projection["geometry_semantics"] == "observed_legacy_placement"
        assert projection["duplicate_group_semantics"] == "legacy_duplicate_candidate"
        assert projection["is_constraint"] is False
        assert projection["is_user_group"] is False
        assert projection["read_only"] is True

        with pytest.raises(
            psycopg.Error, match="legacy compatibility projections are read-only"
        ):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE legacy_asset_observations_v1 SET title = 'mutated' WHERE asset_code = %s",
                    (asset_code,),
                )
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT title FROM assets WHERE asset_code = %s", (asset_code,)
            )
            assert cursor.fetchone()[0] == "Compatibility asset"


def test_legacy_content_variant_and_delivery_projections_do_not_fabricate_new_facts() -> (
    None
):
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        run_code = _insert_workbench_run(connection, suffix)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'completed', target_live_room_id = '38336', completed_at = now()
                WHERE run_code = %s
                """,
                (run_code,),
            )
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM content_projects),
                    (SELECT count(*) FROM production_variants),
                    (SELECT count(*) FROM delivery_attempts)
                """
            )
            before_counts = cursor.fetchone()
        connection.commit()

        repository = WorkflowCompatibilityRepository(connection)
        project = next(
            row
            for row in repository.list_content_projects(limit=100)
            if row["source_code"] == run_code
        )
        assert project["mapping_quality"] == "legacy_import"
        assert "confirmed_content_project_revision" in project["missing_provenance"]

        variant = next(
            row
            for row in repository.list_live_room_variants(limit=100)
            if row["source_code"] == run_code
        )
        assert variant["variant_code"] is None
        assert variant["configuration_code"] is None
        assert variant["mapping_quality"] == "legacy_import"

        delivery = next(
            row
            for row in repository.list_delivery_unknown(limit=100)
            if row["source_code"] == run_code
        )
        assert delivery["delivery_semantics"] == "legacy_delivery_unknown"
        assert delivery["release_code"] is None
        assert delivery["delivery_code"] is None
        assert delivery["external_identity"] is None
        assert delivery["readback_evidence"] is None
        assert delivery["is_actual_delivery"] is False
        assert delivery["is_exposure"] is False

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM content_projects),
                    (SELECT count(*) FROM production_variants),
                    (SELECT count(*) FROM delivery_attempts)
                """
            )
            assert cursor.fetchone() == before_counts


def test_layout_hypothesis_remains_read_only_approximate_reference() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        template_code = _insert_layout_hypothesis(connection, suffix)
        repository = WorkflowCompatibilityRepository(connection)
        projection = next(
            row
            for row in repository.list_layout_hypotheses(limit=100)
            if row["template_code"] == template_code
        )
        assert projection["contract_version"] == "layout-hypothesis.v1"
        assert projection["reference_mode"] == "reference_only"
        assert projection["layout_fidelity"] == "approximate"
        assert projection["buildability"] == "reference_only"
        assert projection["conversion_allowed"] is False
        assert projection["mapping_quality"] == "descriptive_only"
        assert projection["read_only"] is True

        with pytest.raises(
            psycopg.Error, match="legacy compatibility projections are read-only"
        ):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE legacy_layout_hypothesis_projections_v1
                    SET conversion_allowed = true WHERE template_code = %s
                    """,
                    (template_code,),
                )
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT contract_version FROM live_room_template_revisions
                WHERE template_code = %s AND revision_number = 1
                """,
                (template_code,),
            )
            assert cursor.fetchone()[0] == "layout-hypothesis.v1"
