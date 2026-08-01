from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.auth import require_maitu_script_layout_worker
from app.api.routes.maitu_workbench import get_maitu_workbench_repository, router
from app.repositories.maitu import MaituMaterialSlotRepository
from app.repositories.maitu_workbench import (
    MaituWorkbenchConflictError,
    MaituWorkbenchRepository,
)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")


def _receipt_payload(
    *,
    lease_token: str,
    asset_code: str = "AG-IMG-BUILDPLAN",
    material_id: int = 37262,
    source_url: str = "https://cdn.example.test/materials/37262.png?x-oss-process=image/resize,w_320",
) -> dict[str, object]:
    return {
        "lease_token": lease_token,
        "asset_code": asset_code,
        "maitu_material_id": material_id,
        "maitu_source_material_id": material_id,
        "source_material_type": "image",
        "source_material_url": source_url,
        "source_cover_url": (
            f"https://cdn.example.test/covers/{material_id}.png"
            "?x-oss-process=image/resize,w_320"
        ),
        "speaker_id": None,
        "digital_human_image_id": None,
        "inventory_item_fingerprint": "f" * 64,
    }


class RecordingReceiptRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def refresh_functional_draft_material_receipt(
        self,
        execution_job_code: str,
        worker_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((execution_job_code, worker_id, payload))
        return {
            "id": str(uuid4()),
            "asset_code": payload["asset_code"],
            "asset_type": "IMG",
            "title": "BuildPlan background",
            "original_filename": "background.png",
            "status": "created",
            "media_kind": "image",
            "material_roles": ["background"],
            "execution_capability": "maitu_bound",
            "rights_status": "pending",
            "source_material_type": payload["source_material_type"],
            "source_material_url": "https://cdn.example.test/materials/37262.png",
            "source_cover_url": "https://cdn.example.test/covers/37262.png",
            "maitu_material_id": payload["maitu_material_id"],
            "maitu_source_material_id": payload["maitu_source_material_id"],
            "maitu_binding_verification_source": "worker_maitu_inventory_readback",
            "maitu_binding_verified_at": "2026-07-31T00:00:00Z",
            "maitu_binding_scope": "assetgraph_script_layout_material_binding_v2",
            "maitu_binding_evidence": {"source": "active_functional_worker_inventory_readback"},
        }


def test_material_receipt_route_forwards_real_job_shape_under_worker_identity() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    repository = RecordingReceiptRepository()
    app.dependency_overrides[get_maitu_workbench_repository] = lambda: repository
    app.dependency_overrides[require_maitu_script_layout_worker] = lambda: "receipt-worker"
    lease_token = str(uuid4())

    with TestClient(app) as client:
        response = client.post(
            "/api/maitu/workbench/draft-execution-jobs/MT-WB-EXEC-001/material-binding-receipts",
            json=_receipt_payload(lease_token=lease_token),
        )

    assert response.status_code == 200
    assert response.json()["maitu_binding_scope"] == (
        "assetgraph_script_layout_material_binding_v2"
    )
    assert repository.calls == [
        (
            "MT-WB-EXEC-001",
            "receipt-worker",
            _receipt_payload(lease_token=lease_token),
        )
    ]


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="ASSETGRAPH_TEST_DATABASE_URL is not configured",
)
def test_postgres_receipt_refresh_uses_frozen_build_plan_operations_and_preserves_asset() -> None:
    schema = f"functional_receipt_test_{uuid4().hex[:12]}"
    lease_token = uuid4()
    build_plan_code = "MT-BUILD-RECEIPT-001"
    execution_job_code = "MT-WB-EXEC-RECEIPT-001"
    authorized_asset_code = "AG-IMG-BUILDPLAN"
    ui_only_asset_code = "AG-IMG-UI-ONLY"
    cloned_tables = (
        "assets",
        "functional_live_room_plans",
        "maitu_live_room_build_plans",
        "maitu_live_room_build_plan_operations",
        "maitu_workbench_draft_execution_jobs",
    )
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                cursor.execute(
                    sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
                )
                for table in cloned_tables:
                    cursor.execute(
                        sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)").format(
                            sql.Identifier(schema),
                            sql.Identifier(table),
                            sql.Identifier(table),
                        )
                    )
                cursor.execute(
                    """
                    INSERT INTO assets (
                        asset_code, asset_type, title, original_filename, status,
                        media_kind, material_roles, execution_capability,
                        rights_status, rights_note, rights_updated_at, rights_updated_by,
                        maitu_material_id, maitu_source_material_id, source_material_type,
                        source_material_url, source_cover_url,
                        maitu_binding_verification_source, maitu_binding_verified_at,
                        maitu_binding_scope, maitu_binding_inventory_fingerprint,
                        maitu_binding_readback_nonce, maitu_binding_attestation,
                        maitu_binding_evidence
                    ) VALUES
                    (
                        %s, 'IMG', 'Frozen operation material', '37262.png', 'created',
                        'image', '["background"]'::jsonb, 'maitu_bound',
                        'approved', 'licensed for integration test', now() - interval '2 days',
                        'rights-reviewer', 37262, 37262, 'image',
                        'https://cdn.example.test/materials/37262.png',
                        'https://cdn.example.test/covers/37262.png',
                        'worker_maitu_inventory_readback', now() - interval '11 days',
                        'assetgraph_test_draft_material_binding_v1', %s, %s, %s,
                        '{"source":"old_worker_readback"}'::jsonb
                    ),
                    (
                        %s, 'IMG', 'UI-only selected material', '42419.png', 'created',
                        'image', '["background"]'::jsonb, 'maitu_bound',
                        'pending', 'not reviewed', NULL, NULL, 42419, 42419, 'image',
                        'https://cdn.example.test/materials/42419.png',
                        'https://cdn.example.test/covers/42419.png',
                        'worker_maitu_inventory_readback', now() - interval '11 days',
                        'assetgraph_test_draft_material_binding_v1', %s, NULL, NULL,
                        '{"source":"old_worker_readback"}'::jsonb
                    )
                    """,
                    (
                        authorized_asset_code,
                        "a" * 64,
                        uuid4(),
                        "b" * 64,
                        ui_only_asset_code,
                        "c" * 64,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO functional_live_room_plans (
                        plan_code, project_code, variant_code, configuration_code,
                        target_live_room_id, expected_title, selected_asset_codes,
                        blueprint, build_plan, status, blocked_reasons
                    ) VALUES (
                        'LIVEPLAN-RECEIPT-001', 'CONTENT-RECEIPT-001',
                        'VARIANT-RECEIPT-001', 'ROOMCFG-RECEIPT-001',
                        '41172', 'asser测试', %s, '{}'::jsonb, %s, 'ready', '[]'::jsonb
                    ) RETURNING id
                    """,
                    (
                        Jsonb([ui_only_asset_code]),
                        Jsonb(
                            {
                                "build_plan_code": build_plan_code,
                                "target_live_room_id": "41172",
                                "expected_title": "asser测试",
                                "inventory_snapshot": {
                                    "asset_codes": [authorized_asset_code],
                                    "assets": [{"asset_code": authorized_asset_code}],
                                },
                            }
                        ),
                    ),
                )
                functional_plan_id = cursor.fetchone()[0]
                plan_details = {
                    "contract_version": "script_layout_build_plan_v1",
                    "script_layout_build_plan": {
                        "source": "functional-live-room-receipt-test",
                        "status": "ready",
                        "target_live_room_id": "41172",
                        "expected_title": "asser测试",
                        "build_mode": "strict",
                        "can_execute": True,
                        "manual_review_required": False,
                        "blocked_reasons": [],
                    },
                }
                cursor.execute(
                    """
                    INSERT INTO maitu_live_room_build_plans (
                        build_plan_code, blueprint_code, plan_name, target_app,
                        executor, status, strategy, description, details
                    ) VALUES (
                        %s, NULL, 'Receipt authority plan', 'maitu', 'browser_use',
                        'ready', 'script_driven_layout_v1', 'receipt test', %s
                    ) RETURNING id
                    """,
                    (build_plan_code, Jsonb(plan_details)),
                )
                build_plan_id = cursor.fetchone()[0]
                operations = [
                    {
                        "operation_type": "preflight_content_build_plan",
                        "operation_name": "Verify the test room",
                        "sort_order": 1,
                        "status": "ready",
                        "target_live_room_id": "41172",
                        "expected_live_room_title": "asser测试",
                    },
                    {
                        "operation_type": "insert_asset_layer",
                        "operation_name": "Insert frozen background",
                        "sort_order": 2,
                        "status": "ready",
                        "scene_name": "Opening",
                        "layer_id": "LAYER-BG-001",
                        "layer_type": "background",
                        "asset_code": authorized_asset_code,
                    },
                ]
                for operation in operations:
                    cursor.execute(
                        """
                        INSERT INTO maitu_live_room_build_plan_operations (
                            build_plan_id, build_plan_code, operation_type,
                            operation_name, sort_order, status, scene_name,
                            layer_name, layer_role, selected_asset_code,
                            selected_asset_title, instruction, details
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'execute frozen operation', %s
                        )
                        """,
                        (
                            build_plan_id,
                            build_plan_code,
                            operation["operation_type"],
                            operation["operation_name"],
                            operation["sort_order"],
                            operation["status"],
                            operation.get("scene_name"),
                            operation.get("layer_id"),
                            operation.get("layer_type"),
                            operation.get("asset_code"),
                            "Frozen operation material"
                            if operation.get("asset_code")
                            else None,
                            Jsonb(
                                {
                                    "contract_version": "script_layout_operation_v1",
                                    "script_layout_operation": operation,
                                }
                            ),
                        ),
                    )
            connection.commit()

            operation_plan = MaituMaterialSlotRepository(
                connection
            ).get_live_room_build_plan_operations(build_plan_code)
            assert operation_plan is not None
            source_plan_fingerprint = operation_plan["checkpoint_source_fingerprint"]
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO maitu_workbench_draft_execution_jobs (
                        execution_job_code, source_kind, functional_plan_id,
                        functional_plan_code, execution_mode, authority_mode,
                        status, input_fingerprint, payload, ready_for_go_live,
                        claimed_by, lease_token, lease_expires_at, heartbeat_at,
                        stage, progress_current, progress_total
                    ) VALUES (
                        %s, 'functional_live_room_plan', %s,
                        'LIVEPLAN-RECEIPT-001', 'replace_test_draft',
                        'worker_readback', 'running', %s, %s, false,
                        'receipt-worker', %s, now() + interval '5 minutes', now(),
                        'preparing_materials', 0, 5
                    )
                    """,
                    (
                        execution_job_code,
                        functional_plan_id,
                        "d" * 64,
                        Jsonb(
                            {
                                "execution_mode": "replace_test_draft",
                                "test_use_acknowledged": True,
                                "non_releasable": True,
                                "build_plan": {
                                    "build_plan_code": build_plan_code,
                                    "target_live_room_id": "41172",
                                    "expected_title": "asser测试",
                                    "source_plan_fingerprint": source_plan_fingerprint,
                                },
                                "ready_for_go_live": False,
                            }
                        ),
                        lease_token,
                    ),
                )
            connection.commit()

            repository = MaituWorkbenchRepository(connection)
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM assets WHERE asset_code = %s",
                    (authorized_asset_code,),
                )
                before = cursor.fetchone()
            refreshed = repository.refresh_functional_draft_material_receipt(
                execution_job_code,
                "receipt-worker",
                _receipt_payload(lease_token=str(lease_token)),
            )

            assert refreshed["maitu_binding_scope"] == (
                "assetgraph_script_layout_material_binding_v2"
            )
            assert refreshed["maitu_binding_verified_at"] > datetime.now(UTC) - timedelta(
                seconds=10
            )
            assert refreshed["maitu_binding_inventory_fingerprint"] == "f" * 64
            assert refreshed["maitu_binding_readback_nonce"] is None
            assert refreshed["maitu_binding_attestation"] is None
            assert refreshed["maitu_binding_evidence"]["build_plan_code"] == build_plan_code
            assert refreshed["maitu_binding_evidence"]["source_plan_fingerprint"] == (
                source_plan_fingerprint
            )
            immutable_fields = (
                "maitu_material_id",
                "maitu_source_material_id",
                "source_material_type",
                "source_material_url",
                "source_cover_url",
                "speaker_id",
                "digital_human_image_id",
                "execution_capability",
                "rights_status",
                "rights_note",
                "rights_updated_at",
                "rights_updated_by",
            )
            assert {field: refreshed[field] for field in immutable_fields} == {
                field: before[field] for field in immutable_fields
            }

            with pytest.raises(
                MaituWorkbenchConflictError,
                match="active allowlisted test job",
            ):
                repository.refresh_functional_draft_material_receipt(
                    execution_job_code,
                    "receipt-worker",
                    _receipt_payload(
                        lease_token=str(lease_token),
                        asset_code=ui_only_asset_code,
                        material_id=42419,
                    ),
                )

            for tampered in (
                _receipt_payload(lease_token=str(lease_token), material_id=99999),
                _receipt_payload(
                    lease_token=str(lease_token),
                    source_url="https://other.example.test/materials/37262.png",
                ),
            ):
                with pytest.raises(
                    MaituWorkbenchConflictError,
                    match="identity differs",
                ):
                    repository.refresh_functional_draft_material_receipt(
                        execution_job_code,
                        "receipt-worker",
                        tampered,
                    )

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_operations
                    SET selected_asset_title = 'BuildPlan changed after queueing'
                    WHERE build_plan_code = %s AND operation_type = 'insert_asset_layer'
                    """,
                    (build_plan_code,),
                )
            connection.commit()
            with pytest.raises(
                MaituWorkbenchConflictError,
                match="active allowlisted test job",
            ):
                repository.refresh_functional_draft_material_receipt(
                    execution_job_code,
                    "receipt-worker",
                    _receipt_payload(lease_token=str(lease_token)),
                )
    finally:
        if DATABASE_URL:
            with psycopg.connect(DATABASE_URL) as cleanup_connection:
                with cleanup_connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(schema)
                        )
                    )
                cleanup_connection.commit()
