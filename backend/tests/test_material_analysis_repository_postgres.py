from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.repositories.maitu_workbench import MaituWorkbenchRepository
from app.services.material_analysis import MaterialAnalysisWorkbenchService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
FINGERPRINT = "a" * 64


def test_postgres_video_analysis_queue_gemini_conflict_and_selection_gate() -> None:
    schema = f"material_analysis_test_{uuid4().hex[:12]}"
    migration_root = Path(__file__).resolve().parents[1] / "migrations"
    migrations = [
        (migration_root / name).read_text(encoding="utf-8")
        for name in (
            "023_maitu_production_workbench.sql",
            "024_live_research_observations.sql",
            "025_maitu_material_analysis.sql",
            "026_maitu_reference_template_handoff.sql",
            "043_provider_neutral_producer_contracts.sql",
        )
    ]
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
                for table in ("business_sequences", "products", "assets"):
                    cursor.execute(
                        sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)").format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                            sql.Identifier(table),
                        )
                    )
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE {}.artifact_refs "
                        "(LIKE public.artifact_refs INCLUDING ALL)"
                    ).format(sql.Identifier(schema))
                )
                for migration in migrations:
                    cursor.execute(sql.SQL(migration))
                cursor.execute(
                    """
                    INSERT INTO assets (
                        asset_code, asset_type, title, original_filename, checksum_sha256,
                        status, local_relative_path
                    ) VALUES ('AG-VID-INT', 'VID', 'Integration video', 'integration.mp4',
                              %s, 'stored', '视频/integration.mp4')
                    """,
                    (FINGERPRINT,),
                )
            connection.commit()
            repository = MaituWorkbenchRepository(connection)
            card = repository.create_product_fact_card(
                {
                    "title": "Analysis integration product",
                    "product_code": None,
                    "content": {
                        "product_name": "Integration product",
                        "positioning": "Verified",
                        "verified_facts": ["verified fact"],
                    },
                    "approve": True,
                    "created_by": "integration-test",
                    "approved_by": "integration-test",
                },
                content_sha256="b" * 64,
            )
            approved = repository.resolve_product_fact_card_version(
                card["fact_card_code"],
                1,
                require_approved=True,
            )
            assert approved is not None
            sync = repository.create_inventory_sync_job(
                {
                    "source_system": "maitu",
                    "project_code": "ANALYSIS",
                    "sync_mode": "full",
                    "config": {},
                    "requested_by": "integration-test",
                },
                request_fingerprint="c" * 64,
            )
            sync_claim = repository.claim_inventory_sync_job(
                "inventory-worker",
                60,
                sync_job_code=sync["sync_job_code"],
            )
            assert sync_claim is not None
            completed_sync = repository.complete_inventory_sync_job(
                sync["sync_job_code"],
                "inventory-worker",
                sync_claim["lease_token"],
                {
                    "source_revision": "analysis-integration",
                    "schema_version": "maitu-inventory-snapshot-v1",
                    "quality_status": "complete",
                    "captured_at": datetime.now(UTC),
                    "summary": {},
                    "items": [
                        {
                            "item_key": "maitu:video:1",
                            "material_id": "1",
                            "asset_code": "AG-VID-INT",
                            "title": "Integration video",
                            "material_type": "video",
                            "category": "product_video",
                            "availability_status": "available",
                            "checksum_sha256": FINGERPRINT,
                            "metadata": {
                                "local_relative_path": "视频/integration.mp4",
                                "mirror_downloaded": False,
                            },
                        }
                    ],
                },
                snapshot_fingerprint="d" * 64,
            )
            assert completed_sync is not None
            snapshot = completed_sync["snapshot"]
            run = repository.create_run(
                {
                    "title": "Analysis integration run",
                    "topic": "Analyze selected product video",
                    "target_live_room_id": "draft-room",
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
            )
            repository.mark_run_planning(run["run_code"], expected_revision=0)
            repository.create_plan_revision(
                run["run_code"],
                expected_revision=0,
                trigger_type="initial",
                status="ready",
                fact_card_version=approved,
                inventory_snapshot=snapshot,
                source_build_plan_code=None,
                input_fingerprint="e" * 64,
                generation_provider="deepseek",
                generation_requested_model="deepseek-v4-pro",
                generation_actual_model="deepseek-v4-pro",
                generation_prompt_version="test-v1",
                generation_request_id="test",
                generation_input_fingerprint="f" * 64,
                generation_output_fingerprint="1" * 64,
                generation_usage={},
                generation_latency_ms=1,
                pipeline_source="integration",
                pipeline_output={"build_plan": {"can_execute": True, "operations": []}},
                gap_report={},
                blocked_reasons=[],
                requirements=[
                    {
                        "requirement_key": "2" * 64,
                        "scene_index": 0,
                        "scene_name": "Product",
                        "need_index": 0,
                        "need_type": "product_video",
                        "required_category": "product_video",
                        "accepted_asset_types": ["VID"],
                        "description": "Product video",
                        "keywords": [],
                        "priority": "high",
                        "is_required": True,
                        "status": "selected",
                        "pipeline_selection": {},
                        "initial_decision": {
                            "decision": "selected",
                            "selected_asset_code": "AG-VID-INT",
                            "selected_material_key": None,
                            "reason": "pipeline",
                            "decision_source": "pipeline_auto",
                            "decided_by": None,
                        },
                    }
                ],
                reason="integration",
                created_by="integration-test",
            )
            analyses = repository.synchronize_selected_video_analyses(run["run_code"])
            assert analyses and analyses[0]["status"] == "queued" and analyses[0]["selected"] is True
            claim = repository.claim_video_analysis("analysis-worker", 60)
            assert claim is not None
            failed = repository.fail_video_analysis(
                claim["analysis_code"],
                "analysis-worker",
                claim["lease_token"],
                error_code="OPENAI_NOT_CONFIGURED",
                error_message="fail closed integration check",
            )
            assert failed["status"] == "failed"
            retried = repository.retry_video_analysis(claim["analysis_code"])
            assert retried and retried["status"] == "queued" and retried["attempt"] == 2
            claim = repository.claim_video_analysis("analysis-worker", 60)
            assert claim is not None
            service = MaterialAnalysisWorkbenchService(repository)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO artifact_refs (
                        artifact_code, artifact_kind, media_type, schema_version,
                        storage_uri, checksum_sha256, byte_size, producer_type,
                        producer_code, sensitivity, retention_policy_code
                    ) VALUES (
                        'ART-MATERIAL-TEST', 'provider_invocation_evidence',
                        'application/json', 'provider-invocation-evidence.v1',
                        's3://test/material-evidence', %s, 1,
                        'provider_strategy', 'test-material-worker',
                        'confidential', 'critical-audit-evidence'
                    )
                    """,
                    ("9" * 64,),
                )
            connection.commit()
            service.complete_video_analysis(
                claim["analysis_code"],
                "analysis-worker",
                {
                    "lease_token": claim["lease_token"],
                    "technical": {"duration_seconds": 10},
                    "frame_manifest": {"frames": []},
                    "observation": _observation("AG-VID-INT", ["PRO"]),
                    "analysis_strategy_revision": "material.semantic-observation.v2",
                    "invocation_evidence_ref": "ART-MATERIAL-TEST",
                    "analysis_prompt_revision": "material-observation-v1",
                    "analysis_input_fingerprint": "3" * 64,
                    "analysis_output_fingerprint": "4" * 64,
                },
            )
            raw = {
                "analysis_task_code": claim["analysis_code"],
                "asset_code": "AG-VID-INT",
                "asset_fingerprint": FINGERPRINT,
                "prompt_schema_version": "gemini-material-analysis-v1",
                "observation": _observation("AG-VID-INT", ["OTHER"]),
            }
            service.submit_gemini_backfill(
                run["run_code"],
                claim["analysis_code"],
                {
                    "raw_json": raw,
                    "asset_code": "AG-VID-INT",
                    "asset_fingerprint": FINGERPRINT,
                    "submitted_by": "reviewer",
                },
            )
            conflicts = repository.list_analysis_conflicts(run["run_code"])
            assert conflicts and conflicts[0]["severity"] == "critical"
            assert repository.list_selected_analysis_blockers(run["run_code"])

            requirement = repository.list_material_requirements(run["run_code"])[0]
            repository.create_material_decision(
                run["run_code"],
                requirement["requirement_code"],
                {
                    "decision": "waived",
                    "selected_asset_code": None,
                    "selected_material_key": None,
                    "reason": "do not use this video",
                    "decided_by": "reviewer",
                },
            )
            assert repository.list_video_analyses(run["run_code"])[0]["selected"] is False
            assert repository.list_analysis_conflicts(run["run_code"]) == []
            assert repository.list_selected_analysis_blockers(run["run_code"]) == []
    finally:
        if DATABASE_URL:
            with psycopg.connect(DATABASE_URL) as cleanup:
                with cleanup.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                    )
                cleanup.commit()


def _observation(asset_code: str, product_identities: list[str]) -> dict[str, object]:
    return {
        "schema_version": "material-profile-observation-v1",
        "asset_code": asset_code,
        "asset_fingerprint": FINGERPRINT,
        "summary": "integration video",
        "semantic_roles": ["product_visual"],
        "product_identities": product_identities,
        "people": [],
        "visible_text": [],
        "palette": [],
        "style_tags": [],
        "audio_class": "unknown",
        "original_audio_recommended": False,
        "reusable_as_whole": True,
        "scenes": [],
        "warnings": [],
    }
