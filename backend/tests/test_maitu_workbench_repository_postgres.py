from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from app.repositories.maitu_workbench import MaituWorkbenchConflictError, MaituWorkbenchRepository
from app.services.maitu_workbench import sanitize_reference_template


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_postgres_workbench_version_snapshot_replan_preflight_and_execution_state_machine() -> None:
    schema = f"maitu_workbench_test_{uuid4().hex[:12]}"
    migration_root = Path(__file__).resolve().parents[1] / "migrations"
    migrations = [
        (migration_root / name).read_text(encoding="utf-8")
        for name in (
            "023_maitu_production_workbench.sql",
            "024_live_research_observations.sql",
            "026_maitu_reference_template_handoff.sql",
        )
    ]
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                cursor.execute(
                    sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE {}.business_sequences "
                        "(LIKE public.business_sequences INCLUDING ALL)"
                    ).format(sql.Identifier(schema))
                )
                for migration in migrations:
                    cursor.execute(sql.SQL(migration))
                    cursor.execute(sql.SQL(migration))
            connection.commit()
            repository = MaituWorkbenchRepository(connection)

            card = repository.create_product_fact_card(
                {
                    "title": "Workbench integration product",
                    "product_code": None,
                    "content": {
                        "product_name": "Integration product",
                        "positioning": "Verified positioning",
                        "verified_facts": ["fact one", "fact two"],
                    },
                    "approve": False,
                    "created_by": "integration-test",
                },
                content_sha256="a" * 64,
            )
            version = repository.create_product_fact_card_version(
                card["fact_card_code"],
                {
                    "content": {
                        "product_name": "Integration product",
                        "positioning": "Approved positioning",
                        "verified_facts": ["fact one", "fact two"],
                    },
                    "change_reason": "Approve integration facts",
                    "created_by": "integration-test",
                    "approve": False,
                },
                content_sha256="b" * 64,
            )
            approved = repository.approve_product_fact_card_version(
                card["fact_card_code"], version["version_number"], "integration-test"
            )
            assert approved is not None
            assert approved["status"] == "approved"

            sync = repository.create_inventory_sync_job(
                {
                    "source_system": "maitu",
                    "project_code": "INTEGRATION",
                    "sync_mode": "full",
                    "config": {},
                    "requested_by": "integration-test",
                    "idempotency_key": f"inventory-{uuid4().hex}",
                },
                request_fingerprint="c" * 64,
            )
            claimed = repository.claim_inventory_sync_job(
                "inventory-worker", 60, sync_job_code=sync["sync_job_code"]
            )
            assert claimed is not None
            assert repository.heartbeat_inventory_sync_job(
                sync["sync_job_code"], "wrong-worker", claimed["lease_token"], 60
            ) is None
            completed_sync = repository.complete_inventory_sync_job(
                sync["sync_job_code"],
                "inventory-worker",
                claimed["lease_token"],
                {
                    "source_revision": "integration-revision-1",
                    "schema_version": "maitu-inventory-snapshot-v1",
                    "quality_status": "complete",
                    "captured_at": datetime.now(UTC),
                    "summary": {"available": 1},
                    "items": [
                        {
                            "item_key": "material:integration:1",
                            "material_id": "1",
                            "title": "Integration material",
                            "material_type": "image",
                            "category": "background_image",
                            "availability_status": "available",
                            "metadata": {},
                        }
                    ],
                },
                snapshot_fingerprint="d" * 64,
            )
            assert completed_sync is not None
            snapshot = completed_sync["snapshot"]
            assert snapshot["item_count"] == 1
            listed_sync = repository.list_inventory_sync_jobs(limit=10, offset=0)[0]
            assert listed_sync["snapshot"]["snapshot_code"] == snapshot["snapshot_code"]
            assert listed_sync["snapshot"]["fingerprint_sha256"] == "d" * 64

            projection_fingerprint = "8" * 64
            projection = {
                "template_code": "LR-TPL-PG-001",
                "revision_number": 1,
                "projection_contract": "maitu-layout-projection.v1",
                "projection_fingerprint": projection_fingerprint,
                "projection_ready": False,
                "manual_review_required": True,
                "blocking_reasons": ["component_internal-id_source_is_not_verified"],
                "canvas": {"width": 1080, "height": 1920},
                "scenes": [
                    {
                        "scene_key": "internal-scene-id",
                        "name": "PG reference opening",
                        "start_seconds": 0,
                        "end_seconds": 20,
                        "purpose": "Opening rhythm",
                    }
                ],
                "components": [
                    {
                        "component_id": "internal-id",
                        "scene_key": "internal-scene-id",
                        "asset_code": "ASSET-INTERNAL",
                        "role": "host",
                        "geometry": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                    }
                ],
                "audio_policy": {"max_active_speech": 1, "max_active_bgm": 1},
                "provenance": {"source_session_codes": ["PRIVATE-SESSION"]},
            }
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO live_room_templates (template_code, name)
                    VALUES ('LR-TPL-PG-001', 'PG reference')
                    RETURNING id
                    """
                )
                template_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO live_room_template_revisions (
                        template_id, template_code, revision_number, status, canvas,
                        scenes, components, audio_policy, provenance, confidence,
                        review_status, content_fingerprint, reviewed_by, reviewed_at, published_at
                    )
                    VALUES (
                        %s, 'LR-TPL-PG-001', 1, 'published', %s, %s, %s, %s, %s,
                        0.9, 'accepted', %s, 'pg-reviewer', now(), now()
                    )
                    RETURNING id
                    """,
                    (
                        template_id,
                        Jsonb(projection["canvas"]),
                        Jsonb(projection["scenes"]),
                        Jsonb(projection["components"]),
                        Jsonb(projection["audio_policy"]),
                        Jsonb(projection["provenance"]),
                        "6" * 64,
                    ),
                )
                published_revision_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO live_room_template_publications (
                        publication_code, template_id, template_code, revision_id,
                        revision_number, projection_payload, projection_fingerprint,
                        projection_ready, manual_review_required, published_by
                    )
                    VALUES (
                        'LR-PUB-PG-001', %s, 'LR-TPL-PG-001', %s, 1, %s, %s,
                        false, true, 'pg-publisher'
                    )
                    """,
                    (
                        template_id,
                        published_revision_id,
                        Jsonb(projection),
                        projection_fingerprint,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE live_room_templates
                    SET published_revision_id = %s, status = 'draft'
                    WHERE id = %s
                    """,
                    (published_revision_id, template_id),
                )
                cursor.execute(
                    """
                    INSERT INTO live_room_template_revisions (
                        template_id, template_code, revision_number, status, canvas,
                        scenes, components, audio_policy, provenance, confidence,
                        review_status, content_fingerprint
                    )
                    VALUES (
                        %s, 'LR-TPL-PG-001', 2, 'draft', %s, '[]'::jsonb,
                        '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, 0.9, 'pending', %s
                    )
                    """,
                    (template_id, Jsonb(projection["canvas"]), "7" * 64),
                )
            connection.commit()
            published_reference = repository.resolve_published_reference_template(
                "LR-TPL-PG-001"
            )
            assert published_reference is not None
            assert published_reference["revision_number"] == 1
            assert published_reference["projection_fingerprint"] == projection_fingerprint
            reference_template = {
                "template_code": published_reference["template_code"],
                "revision_number": published_reference["revision_number"],
                "projection_fingerprint": published_reference["projection_fingerprint"],
                "snapshot": sanitize_reference_template(published_reference),
            }

            run = repository.create_run(
                {
                    "title": "Workbench integration run",
                    "topic": "Generate a grounded integration demo",
                    "target_live_room_id": "integration-draft-room",
                    "target_duration_minutes": 1,
                    "build_mode": "strict",
                    "include_default_host": True,
                    "max_candidates_per_need": 1,
                    "canvas_width": 1080,
                    "canvas_height": 1920,
                    "created_by": "integration-test",
                },
                fact_card_version=approved,
                inventory_snapshot=snapshot,
                reference_template=reference_template,
            )
            assert run["reference_template_code"] == "LR-TPL-PG-001"
            assert run["reference_template_revision_number"] == 1
            assert run["reference_template_projection_fingerprint"] == projection_fingerprint
            assert "ASSET-INTERNAL" not in str(run["reference_template_snapshot"])
            with pytest.raises(psycopg.errors.RaiseException, match="reference template is immutable"):
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE maitu_workbench_runs
                        SET reference_template_revision_number = 2
                        WHERE run_code = %s
                        """,
                        (run["run_code"],),
                    )
            connection.rollback()
            listed_run = repository.list_runs(limit=10, offset=0)[0]
            assert listed_run["fact_card_code"] == card["fact_card_code"]
            assert listed_run["fact_card_version_number"] == version["version_number"]
            rebound = repository.update_run_target_live_room(
                run["run_code"], "integration-draft-room-2"
            )
            assert rebound is not None
            assert rebound["target_live_room_id"] == "integration-draft-room-2"
            assert rebound["status"] == "draft"
            repository.mark_run_planning(run["run_code"], expected_revision=0)
            with pytest.raises(MaituWorkbenchConflictError):
                repository.mark_run_planning(run["run_code"], expected_revision=0)
            common = {
                "fact_card_version": approved,
                "inventory_snapshot": snapshot,
                "source_build_plan_code": None,
                "generation_provider": "deepseek",
                "generation_requested_model": "deepseek-test",
                "generation_actual_model": "deepseek-test",
                "generation_prompt_version": "integration-v1",
                "generation_request_id": "integration-request",
                "generation_input_fingerprint": "e" * 64,
                "generation_output_fingerprint": "f" * 64,
                "generation_usage": {},
                "generation_latency_ms": 1,
                "pipeline_source": "integration-test",
                "gap_report": {},
                "reason": "integration test",
                "created_by": "integration-test",
            }
            first_plan = repository.create_plan_revision(
                run["run_code"],
                expected_revision=0,
                trigger_type="initial",
                status="blocked",
                input_fingerprint="1" * 64,
                pipeline_output={"build_plan": {"can_execute": False, "operations": []}},
                blocked_reasons=["missing_required_assets"],
                requirements=[_requirement(status="missing")],
                **common,
            )
            target_changed_after_plan = repository.update_run_target_live_room(
                run["run_code"], "integration-draft-room-3"
            )
            assert target_changed_after_plan is not None
            assert target_changed_after_plan["status"] == "replan_required"
            requirement = repository.list_material_requirements(run["run_code"])[0]
            decision = repository.create_material_decision(
                run["run_code"],
                requirement["requirement_code"],
                {
                    "decision": "selected",
                    "selected_asset_code": None,
                    "selected_material_key": "material:integration:1",
                    "reason": "Use captured inventory material",
                    "decided_by": "integration-test",
                },
            )
            assert decision is not None
            assert repository.get_run(run["run_code"])["status"] == "replan_required"

            repository.mark_run_planning(run["run_code"], expected_revision=1)
            second_requirement = _requirement(status="selected")
            second_requirement["initial_decision"] = {
                "decision": "selected",
                "selected_asset_code": None,
                "selected_material_key": "material:integration:1",
                "reason": "Carried forward",
                "decision_source": "carried_forward",
                "decided_by": "integration-test",
            }
            second_plan = repository.create_plan_revision(
                run["run_code"],
                expected_revision=1,
                trigger_type="replan",
                status="ready",
                input_fingerprint="2" * 64,
                pipeline_output={
                    "build_plan": {
                        "can_execute": True,
                        "operations": [{"operation_type": "save_draft"}],
                    }
                },
                blocked_reasons=[],
                requirements=[second_requirement],
                **common,
            )
            assert repository.get_plan_revision(
                run["run_code"], first_plan["revision_number"]
            )["status"] == "superseded"
            assert second_plan["revision_number"] == 2
            assert second_plan["generation_provider"] == "deepseek"

            preflight = repository.create_preflight(
                run["run_code"],
                expected_plan_revision=2,
                status="passed",
                input_fingerprint="3" * 64,
                checks=[{"code": "draft_only", "passed": True}],
                blocked_reasons=[],
                performed_by="integration-test",
            )
            job = repository.create_draft_execution_job(
                run["run_code"],
                expected_plan_revision=2,
                input_fingerprint="4" * 64,
                payload={"ready_for_go_live": False},
                idempotency_key=f"execution-{uuid4().hex}",
                queued_by="integration-test",
            )
            execution = repository.claim_draft_execution_job(
                "draft-worker", 60, execution_job_code=job["execution_job_code"]
            )
            assert execution is not None
            completed = repository.complete_draft_execution_job(
                job["execution_job_code"],
                "draft-worker",
                execution["lease_token"],
                {"saved": True},
            )
            assert preflight["status"] == "passed"
            assert completed["status"] == "succeeded"
            assert repository.get_run(run["run_code"])["status"] == "completed"
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


def _requirement(*, status: str) -> dict[str, object]:
    return {
        "requirement_key": "9" * 64,
        "scene_index": 0,
        "scene_name": "Integration scene",
        "need_index": 0,
        "need_type": "background_image",
        "required_category": "background_image",
        "accepted_asset_types": ["IMG"],
        "description": "Integration background",
        "keywords": ["integration"],
        "priority": "high",
        "is_required": True,
        "status": status,
        "pipeline_selection": {},
    }
