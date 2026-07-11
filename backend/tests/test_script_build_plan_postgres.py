from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.repositories.maitu import MaituMaterialSlotRepository
from app.schemas.maitu import (
    MaituLiveRoomBuildPlanExecutionResultCreate,
    MaituLiveRoomBuildPlanOperationPlanResponse,
)

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_postgres_persists_script_layout_plan_and_round_trips_worker_fields() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "020_script_driven_build_plan_persistence.sql"
    ).read_text(encoding="utf-8")
    build_plan: dict[str, Any] = {
        "source": "script_content_layout_build_plan_rule_v1",
        "status": "ready",
        "target_live_room_id": "47000002",
        "build_mode": "strict",
        "can_execute": True,
        "manual_review_required": False,
        "blocked_reasons": [],
        "operation_count": 3,
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "operation_name": "内容驱动搭建计划预检",
                "sort_order": 1,
                "status": "ready",
                "target_live_room_id": "47000002",
                "instruction": "只读预检草稿。",
            },
            {
                "operation_type": "insert_asset_layer",
                "operation_name": "插入商品图",
                "sort_order": 10,
                "status": "ready",
                "scene_index": 0,
                "scene_name": "品酒大师PRO",
                "layer_id": "scene-00-product_image",
                "layer_type": "product_image",
                "need_type": "product_image",
                "asset_code": "AG-IMG-20260709-000069",
                "asset_display_code": "MT-DECOR-0069",
                "material_id": 40999,
                "source_material_type": "image",
                "source_material_url": "https://static.example/product-pro.png",
                "x": 720,
                "y": 980,
                "width": 280,
                "height": 280,
                "z_index": 5,
                "future_worker_field": {"contract": "must-survive-http-schema"},
                "instruction": "插入商品图并回读验证。",
            },
            {
                "operation_type": "write_script",
                "operation_name": "写入脚本",
                "sort_order": 20,
                "status": "ready",
                "scene_index": 0,
                "scene_name": "品酒大师PRO",
                "script_text": "这段脚本必须原样回读。",
                "instruction": "写入场景脚本并回读验证。",
            },
        ],
    }

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(migration)
        connection.commit()
        repository = MaituMaterialSlotRepository(connection)
        persisted = repository.create_script_layout_build_plan(
            build_plan,
            plan_name="超长剧本标题" * 50 + " 剧本驱动 BuildPlan",
        )
        code = persisted["build_plan_code"]
        try:
            operation_plan = repository.get_live_room_build_plan_operations(code)
            assert operation_plan is not None
            assert operation_plan["build_plan_code"] == code
            assert operation_plan["source"] == build_plan["source"]
            assert operation_plan["status"] == "ready"
            assert operation_plan["target_live_room_id"] == "47000002"
            assert operation_plan["can_execute"] is True
            assert operation_plan["manual_review_required"] is False
            assert operation_plan["operations"] == build_plan["operations"]
            persisted_plan = repository.get_live_room_build_plan_by_code(code)
            assert persisted_plan is not None
            assert len(persisted_plan["plan_name"]) == 255
            assert persisted_plan["blueprint_code"] is None
            serialized = MaituLiveRoomBuildPlanOperationPlanResponse.model_validate(operation_plan).model_dump()
            insert_operation = serialized["operations"][1]
            assert insert_operation["asset_code"] == "AG-IMG-20260709-000069"
            assert insert_operation["future_worker_field"] == {"contract": "must-survive-http-schema"}

            execution_payload = MaituLiveRoomBuildPlanExecutionResultCreate.model_validate(
                {
                    "executor": "browser_use",
                    "execution_status": "completed_with_manual_review",
                    "mode": "script_layout_draft",
                    "ready_for_go_live": False,
                    "manual_review_required": True,
                    "result_summary": "草稿步骤完成，仍需人工复核。",
                    "operation_results": [
                        {
                            "operation_index": 1,
                            "operation_type": "insert_asset_layer",
                            "operation_name": "插入商品图",
                            "scene_index": 0,
                            "scene_name": "品酒大师PRO",
                            "clip_id": 470001,
                            "layer_id": "scene-00-product_image",
                            "layer_type": "product_image",
                            "asset_code": "AG-IMG-20260709-000069",
                            "action_type": "insert_asset_layer",
                            "status": "completed",
                            "details": {"summary": "插入并回读完成"},
                        }
                    ],
                }
            ).model_dump(exclude_none=True)
            execution = repository.create_live_room_build_plan_execution_result(code, execution_payload)
            assert execution is not None
            assert execution["blueprint_code"] is None
            assert execution["ready_for_go_live"] is False
            assert execution["manual_review_required"] is True
            assert execution["operation_results"][0]["scene_index"] == 0
            assert execution["operation_results"][0]["clip_id"] == 470001
            assert execution["operation_results"][0]["layer_id"] == "scene-00-product_image"
            persisted_plan = repository.get_live_room_build_plan_by_code(code)
            assert persisted_plan is not None
            assert persisted_plan["status"] == "execution_manual_review"
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plan_operation_results WHERE build_plan_code = %s",
                    (code,),
                )
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plan_executions WHERE build_plan_code = %s",
                    (code,),
                )
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plan_operations WHERE build_plan_code = %s",
                    (code,),
                )
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plans WHERE build_plan_code = %s",
                    (code,),
                )
            connection.commit()


def test_postgres_rolls_back_script_layout_plan_when_any_operation_insert_fails() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "020_script_driven_build_plan_persistence.sql"
    ).read_text(encoding="utf-8")
    plan_name = "Phase A rollback atomicity test"
    build_plan = {
        "source": "script_content_layout_build_plan_rule_v1",
        "status": "ready",
        "build_mode": "strict",
        "can_execute": True,
        "manual_review_required": False,
        "blocked_reasons": [],
        "operation_count": 2,
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "operation_name": "valid operation",
                "sort_order": 1,
                "status": "ready",
                "instruction": "valid",
            },
            {
                "operation_type": "write_script",
                "operation_name": "x" * 256,
                "sort_order": 2,
                "status": "ready",
                "instruction": "must trigger VARCHAR(255) rejection",
            },
        ],
    }

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
        connection.commit()
        repository = MaituMaterialSlotRepository(connection)

        with pytest.raises(psycopg.errors.StringDataRightTruncation):
            repository.create_script_layout_build_plan(build_plan, plan_name=plan_name)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM maitu_live_room_build_plans WHERE plan_name = %s",
                (plan_name,),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                """
                SELECT count(*)
                FROM maitu_live_room_build_plan_operations o
                JOIN maitu_live_room_build_plans p ON p.id = o.build_plan_id
                WHERE p.plan_name = %s
                """,
                (plan_name,),
            )
            assert cursor.fetchone()[0] == 0
