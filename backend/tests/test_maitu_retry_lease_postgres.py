from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.repositories.assets import AssetBindingReceiptReplayError, AssetRepository
from app.repositories.maitu import (
    MaituMaterialSlotRepository,
    RetryExecutionConflictError,
    RetryLeaseConflictError,
)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _insert_retry_task(
    connection: psycopg.Connection[Any],
    retry_task_code: str,
    *,
    slot_code: str | None = None,
    failure_type: str = "missing_layer",
) -> None:
    asset_code = f"AG-IMG-IT-{retry_task_code[-12:]}"
    canonical_slot_code = slot_code or f"MT-SLOT-IT-{retry_task_code[-12:]}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE maitu_execution_retry_tasks
            SET status = 'succeeded', claimed_by = NULL, claimed_at = NULL,
                claim_token = NULL, claim_expires_at = NULL, updated_at = now()
            WHERE retry_task_code LIKE 'MT-RETRY-IT-%'
                AND status IN ('pending', 'in_progress', 'manual_required', 'failed')
            """
        )
        cursor.execute(
            """
            INSERT INTO maitu_execution_retry_tasks (
                retry_task_code, plan_code, execution_code, slot_code, asset_code,
                failure_type, retryable, status, retry_attempt_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, true, 'pending', 0)
            """,
            (
                retry_task_code,
                f"PLAN-{retry_task_code}",
                f"EXEC-{retry_task_code}",
                slot_code,
                asset_code,
                failure_type,
            ),
        )
        layer_name = "integration-layer"
        if slot_code is not None:
            cursor.execute(
                "SELECT layer_name FROM maitu_material_slots WHERE slot_code = %s",
                (slot_code,),
            )
            slot_row = cursor.fetchone()
            layer_name = slot_row[0] if slot_row is not None else layer_name
        task = {
            "retry_task_code": retry_task_code,
            "slot_code": canonical_slot_code,
            "asset_code": asset_code,
            "failure_type": failure_type,
            "retryable": True,
            "status": "pending",
        }
        plan = {
            "maitu_project_code": "MT-PROJ-IT",
            "target_live_room_id": "38336",
            "scene_name": "integration-scene",
        }
        slot = {
            "scene_name": "integration-scene",
            "layer_name": layer_name,
            "slot_name": "integration-slot",
            "target_live_room_id": "38336",
            "target_clip_id": 501,
            "target_layer_id": 601,
            "accepted_asset_types": ["IMG"],
            "replacement_policy": "keep_layout",
            "expected_before_state": {
                "layer_id": 601,
                "material_id": 101,
                "left": 12.0,
                "top": 24.0,
                "width": 320.0,
                "height": 180.0,
                "z_index": 4,
            },
        }
        plan_item = {
            "selected_asset_code": asset_code,
            "binding_asset_code": asset_code,
            "selected_asset_type": "IMG",
            "selected_asset_status": "stored",
            "selected_asset_title": "integration asset",
            "replacement_policy": "keep_layout",
            "selected_asset_maitu_material_id": 202,
            "selected_asset_source_material_type": "image",
            "selected_asset_binding_verification_source": "maitu_readback",
            "selected_asset_binding_verified_at": datetime(2026, 7, 11, tzinfo=UTC),
            "selected_asset_binding_scope": "live_room:38336",
        }
        operations = MaituMaterialSlotRepository._build_retry_operations(task, plan, slot, plan_item)
        MaituMaterialSlotRepository._insert_retry_operation_intents(cursor, operations)
    connection.commit()


def _claim(repository: MaituMaterialSlotRepository, worker_id: str) -> dict[str, Any]:
    claimed = repository.claim_next_retry_task(
        {"claimed_by": worker_id, "lock_ttl_seconds": 60, "max_attempts": 3}
    )
    assert claimed is not None
    return claimed



def test_postgres_operation_checkpoint_migration_replays() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "017_maitu_retry_operation_checkpoints.sql"
    ).read_text(encoding="utf-8")
    reconciliation_migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "018_maitu_retry_operation_reconciliation.sql"
    ).read_text(encoding="utf-8")
    intent_migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "019_maitu_retry_mutation_intent.sql"
    ).read_text(encoding="utf-8")
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(reconciliation_migration)
            cursor.execute(intent_migration)
            cursor.execute(migration)
            cursor.execute(reconciliation_migration)
            cursor.execute(intent_migration)
        connection.commit()


def test_postgres_retry_operation_intent_rows_reject_update_and_delete() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    with psycopg.connect(DATABASE_URL) as connection:
        _insert_retry_task(connection, retry_task_code)
        for statement in (
            "UPDATE maitu_retry_operation_intents SET readiness_status = 'blocked' WHERE retry_task_code = %s",
            "DELETE FROM maitu_retry_operation_intents WHERE retry_task_code = %s",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="intents are immutable"):
                with connection.cursor() as cursor:
                    cursor.execute(statement, (retry_task_code,))
            connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
        connection.commit()


def test_postgres_retry_task_creation_freezes_immutable_operation_intents() -> None:
    suffix = uuid4().hex[:10]
    plan_code = f"PLAN-{suffix}"
    execution_code = f"EXEC-{suffix}"
    slot_code = f"SLOT-{suffix}"
    asset_code = f"AG-IMG-{suffix}"
    before_state = {
        "layer_id": 601,
        "material_id": 101,
        "left": 12.0,
        "top": 24.0,
        "width": 320.0,
        "height": 180.0,
        "z_index": 4,
    }
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO assets (
                    asset_code, asset_type, original_filename, status, maitu_material_id,
                    source_material_type, maitu_binding_verification_source,
                    maitu_binding_verified_at, maitu_binding_scope
                ) VALUES (%s, 'IMG', 'product.png', 'stored', 202, 'image', 'maitu_readback', %s, 'live_room:38336')
                """,
                (asset_code, datetime(2026, 7, 11, tzinfo=UTC)),
            )
            cursor.execute(
                """
                INSERT INTO maitu_material_slots (
                    slot_code, slot_name, required_category, accepted_asset_types,
                    scene_name, layer_name,
                    target_live_room_id, target_clip_id, target_layer_id,
                    expected_before_state, replacement_policy
                ) VALUES (%s, '商品主图', 'product_image', 'IMG', '场景一', 'layer-8',
                          '38336', 501, 601, %s, 'keep_layout')
                """,
                (slot_code, Jsonb(before_state)),
            )
            cursor.execute(
                """
                INSERT INTO maitu_replacement_plans (
                    plan_code, plan_name, maitu_project_code, target_live_room_id, scene_name
                ) VALUES (%s, '冻结意图测试', 'MT-PROJ-1', '38336', '场景一')
                RETURNING id
                """,
                (plan_code,),
            )
            plan_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO maitu_replacement_plan_items (
                    plan_id, plan_code, slot_code, slot_name, selected_asset_code,
                    selected_asset_title, replacement_policy
                ) VALUES (%s, %s, %s, '商品主图', %s, '商品图', 'keep_layout')
                """,
                (plan_id, plan_code, slot_code, asset_code),
            )
            repository._insert_retry_task(
                cursor,
                execution_code,
                plan_code,
                {"executor": "browser_use"},
                {
                    "slot_code": slot_code,
                    "asset_code": asset_code,
                    "failure_type": "missing_layer",
                    "retryable": True,
                },
            )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT retry_task_code FROM maitu_execution_retry_tasks WHERE execution_code = %s",
                (execution_code,),
            )
            retry_task_code = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT operation_key, readiness_status, intent_payload
                FROM maitu_retry_operation_intents
                WHERE retry_task_code = %s
                ORDER BY CASE operation_key WHEN 'primary' THEN 0 ELSE 1 END
                """,
                (retry_task_code,),
            )
            snapshots = cursor.fetchall()
        assert [(row[0], row[1]) for row in snapshots] == [
            ("primary", "ready"),
            ("save_project", "blocked"),
        ]
        frozen_primary = snapshots[0][2]
        assert frozen_primary["maitu_material_id"] == 202
        assert frozen_primary["binding_verification_source"] == "maitu_readback"

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE assets SET maitu_material_id = 999 WHERE asset_code = %s",
                (asset_code,),
            )
            cursor.execute(
                "UPDATE maitu_material_slots SET target_layer_id = 999 WHERE slot_code = %s",
                (slot_code,),
            )
        connection.commit()

        operation_plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert operation_plan is not None
        assert operation_plan["operations"][0] == frozen_primary
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
        connection.commit()


def test_postgres_reclaim_issues_new_token_and_rejects_stale_lease() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code)
        first = _claim(repository, "worker-a")
        repository.release_retry_task(
            retry_task_code,
            {
                "status": "pending",
                "claimed_by": "worker-a",
                "claim_token": first["claim_token"],
                "lease_version": first["lease_version"],
            },
        )
        second = _claim(repository, "worker-b")

        assert second["claim_token"] != first["claim_token"]
        assert second["lease_version"] == first["lease_version"] + 1
        with pytest.raises(RetryLeaseConflictError):
            repository.heartbeat_retry_task(
                retry_task_code,
                {
                    "claimed_by": "worker-a",
                    "claim_token": first["claim_token"],
                    "lease_version": first["lease_version"],
                    "lock_ttl_seconds": 60,
                },
            )
        with pytest.raises(RetryLeaseConflictError):
            repository.update_retry_task(retry_task_code, {"result_summary": "unsafe active-lease edit"})


def test_postgres_recoverable_release_receipt_is_idempotent_without_attempt_increment() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    retry_execution_id = str(uuid4())
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code)
        claim = _claim(repository, "worker-a")
        payload = {
            "retry_execution_id": retry_execution_id,
            "retry_execution_status": "released",
            "claimed_by": "worker-a",
            "claim_token": claim["claim_token"],
            "lease_version": claim["lease_version"],
            "result_summary": "temporary browser failure",
        }

        first = repository.create_retry_task_execution_result(retry_task_code, payload)
        duplicate = repository.create_retry_task_execution_result(retry_task_code, payload)

        assert first is not None
        assert duplicate is not None
        assert duplicate["status"] == "pending"
        assert duplicate["retry_attempt_count"] == 0
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT retry_attempt_count,
                       (SELECT count(*) FROM maitu_retry_execution_receipts WHERE retry_execution_id = %s)
                FROM maitu_execution_retry_tasks
                WHERE retry_task_code = %s
                """,
                (retry_execution_id, retry_task_code),
            )
            assert cursor.fetchone() == (0, 1)
            cursor.execute(
                "DELETE FROM maitu_retry_execution_receipts WHERE retry_execution_id = %s",
                (retry_execution_id,),
            )
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
        connection.commit()


def test_postgres_completed_checkpoint_skips_after_reclaim_and_blocked_save_stays_closed() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code)
        first_claim = _claim(repository, "worker-a")
        plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert plan is not None
        primary, save = plan["operations"]
        assert primary["status"] == "ready"
        assert save["status"] == "blocked"
        assert save["blocked_reasons"] == ["save_project_not_implemented"]

        primary_attempt = uuid4()
        primary_begin_payload = {
            "claimed_by": "worker-a",
            "claim_token": first_claim["claim_token"],
            "lease_version": first_claim["lease_version"],
            "attempt_id": primary_attempt,
            "operation_fingerprint": primary["operation_fingerprint"],
        }
        begun = repository.begin_retry_operation_checkpoint(
            retry_task_code, primary["operation_key"], primary_begin_payload
        )
        duplicate_begin = repository.begin_retry_operation_checkpoint(
            retry_task_code, primary["operation_key"], primary_begin_payload
        )
        completion_id = uuid4()
        complete_payload = {
            **primary_begin_payload,
            "completion_id": completion_id,
            "evidence": {"verified": True, "material_id": 41043},
        }
        completed = repository.complete_retry_operation_checkpoint(
            retry_task_code, primary["operation_key"], complete_payload
        )
        duplicate_complete = repository.complete_retry_operation_checkpoint(
            retry_task_code, primary["operation_key"], complete_payload
        )
        assert begun is not None and begun["decision"] == "execute"
        assert duplicate_begin is not None and duplicate_begin["attempt_id"] == str(primary_attempt)
        assert completed is not None and completed["state"] == "completed"
        assert duplicate_complete is not None and duplicate_complete["decision"] == "skip"
        assert "claim_token" not in str(duplicate_complete)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE maitu_execution_retry_tasks
                SET claim_expires_at = now() - interval '1 second'
                WHERE retry_task_code = %s
                """,
                (retry_task_code,),
            )
        connection.commit()
        reclaimed = repository.reclaim_expired_retry_tasks()
        assert reclaimed["retry_task_codes"] == [retry_task_code]
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_key, state
                FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s
                ORDER BY operation_key
                """,
                (retry_task_code,),
            )
            assert cursor.fetchall() == [("primary", "completed")]

        second_claim = _claim(repository, "worker-b")
        primary_skip = repository.begin_retry_operation_checkpoint(
            retry_task_code,
            primary["operation_key"],
            {
                "claimed_by": "worker-b",
                "claim_token": second_claim["claim_token"],
                "lease_version": second_claim["lease_version"],
                "attempt_id": uuid4(),
                "operation_fingerprint": primary["operation_fingerprint"],
            },
        )

        assert primary_skip is not None and primary_skip["decision"] == "skip"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT completion_evidence::text FROM maitu_retry_operation_checkpoints WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            assert all("claim_token" not in row[0] for row in cursor.fetchall())


def test_postgres_explicit_release_marks_begun_checkpoint_reconcile_required() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code)
        claim = _claim(repository, "worker-a")
        plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert plan is not None
        operation = plan["operations"][0]
        repository.begin_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            {
                "claimed_by": "worker-a",
                "claim_token": claim["claim_token"],
                "lease_version": claim["lease_version"],
                "attempt_id": uuid4(),
                "operation_fingerprint": operation["operation_fingerprint"],
            },
        )

        repository.release_retry_task(
            retry_task_code,
            {
                "status": "pending",
                "claimed_by": "worker-a",
                "claim_token": claim["claim_token"],
                "lease_version": claim["lease_version"],
            },
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT state FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s AND operation_key = %s
                """,
                (retry_task_code, operation["operation_key"]),
            )
            assert cursor.fetchone() == ("reconcile_required",)
            cursor.execute(
                "DELETE FROM maitu_retry_operation_checkpoints WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
        connection.commit()


def test_postgres_primary_completion_reconciliation_is_idempotent_and_skips_replay() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    reconciliation_id = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code)
        first_claim = _claim(repository, "worker-a")
        plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert plan is not None
        operation = plan["operations"][0]
        begin_payload = {
            "claimed_by": "worker-a",
            "claim_token": first_claim["claim_token"],
            "lease_version": first_claim["lease_version"],
            "attempt_id": uuid4(),
            "operation_fingerprint": operation["operation_fingerprint"],
        }
        begun = repository.begin_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            begin_payload,
        )
        assert begun is not None and begun["decision"] == "execute"
        repository.release_retry_task(
            retry_task_code,
            {
                "status": "pending",
                "claimed_by": "worker-a",
                "claim_token": first_claim["claim_token"],
                "lease_version": first_claim["lease_version"],
            },
        )
        reconciliation_payload = {
            "reconciliation_id": reconciliation_id,
            "expected_attempt_id": begin_payload["attempt_id"],
            "operation_fingerprint": operation["operation_fingerprint"],
            "resolution": "confirmed_completed",
            "resolved_by": "operator-it",
            "resolution_summary": "authoritative readback confirmed mutation",
            "evidence": {"verified": True, "operation_applied": True, "readback": "saved"},
        }
        first = repository.reconcile_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            reconciliation_payload,
        )
        duplicate = repository.reconcile_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            reconciliation_payload,
        )
        assert first == duplicate

        second_claim = _claim(repository, "worker-b")
        skipped = repository.begin_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            {
                "claimed_by": "worker-b",
                "claim_token": second_claim["claim_token"],
                "lease_version": second_claim["lease_version"],
                "attempt_id": uuid4(),
                "operation_fingerprint": operation["operation_fingerprint"],
            },
        )
        assert skipped is not None and skipped["decision"] == "skip"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT state, completion_source, completion_reconciliation_id, completed_lease_version,
                       completion_evidence->>'operation_applied'
                FROM maitu_retry_operation_checkpoints
                WHERE retry_task_code = %s AND operation_key = %s
                """,
                (retry_task_code, operation["operation_key"]),
            )
            assert cursor.fetchone() == ("completed", "reconciliation", reconciliation_id, None, "true")
            cursor.execute(
                "SELECT count(*) FROM maitu_retry_operation_reconciliations WHERE reconciliation_id = %s",
                (reconciliation_id,),
            )
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "DELETE FROM maitu_retry_operation_reconciliations WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute(
                "DELETE FROM maitu_retry_execution_receipts WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute(
                "DELETE FROM maitu_retry_operation_checkpoints WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute("UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s", (retry_task_code,))
        connection.commit()


def test_postgres_slot_authoritative_intent_is_frozen_for_active_retry_lease() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    slot_code = f"MT-SLOT-IT-{uuid4().hex[:12]}"
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_material_slots (slot_code, slot_name, required_category, layer_name)
                VALUES (%s, 'integration slot', 'product_image', 'layer-before')
                """,
                (slot_code,),
            )
        connection.commit()
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code, slot_code=slot_code)
        _claim(repository, "worker-a")

        with pytest.raises(RetryLeaseConflictError, match="authoritative intent"):
            repository.update(slot_code, {"layer_name": "layer-after"})
        with pytest.raises(RetryLeaseConflictError, match="authoritative intent"):
            repository.soft_delete(slot_code)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT layer_name, deleted_at FROM maitu_material_slots WHERE slot_code = %s",
                (slot_code,),
            )
            assert cursor.fetchone() == ("layer-before", None)
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute("DELETE FROM maitu_material_slots WHERE slot_code = %s", (slot_code,))
        connection.commit()


def test_postgres_slot_mutation_and_claim_serialize_on_retry_task_row() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    slot_code = f"MT-SLOT-IT-{uuid4().hex[:12]}"
    failure_type = f"race_{uuid4().hex[:12]}"
    claim_started = threading.Event()
    claim_done = threading.Event()
    claim_result: dict[str, Any] = {}
    claim_errors: list[BaseException] = []

    with psycopg.connect(DATABASE_URL) as mutation_connection:
        with mutation_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_material_slots (slot_code, slot_name, required_category, layer_name)
                VALUES (%s, 'race slot', 'product_image', 'layer-before')
                """,
                (slot_code,),
            )
        mutation_connection.commit()
        _insert_retry_task(
            mutation_connection,
            retry_task_code,
            slot_code=slot_code,
            failure_type=failure_type,
        )
        mutation_repository = MaituMaterialSlotRepository(mutation_connection)

        with mutation_connection.cursor() as cursor:
            cursor.execute(
                "SELECT retry_task_code FROM maitu_execution_retry_tasks WHERE retry_task_code = %s FOR UPDATE",
                (retry_task_code,),
            )
            assert cursor.fetchone() == (retry_task_code,)

        def claim_while_mutation_holds_lock() -> None:
            try:
                with psycopg.connect(DATABASE_URL) as claim_connection:
                    claim_repository = MaituMaterialSlotRepository(claim_connection)
                    claim_started.set()
                    claimed = claim_repository.claim_next_retry_task(
                        {
                            "claimed_by": "worker-race",
                            "lock_ttl_seconds": 60,
                            "max_attempts": 3,
                            "failure_type": failure_type,
                        }
                    )
                    claim_result["task"] = claimed
            except BaseException as exc:  # pragma: no cover - assertion below reports worker failure
                claim_errors.append(exc)
            finally:
                claim_done.set()

        thread = threading.Thread(target=claim_while_mutation_holds_lock)
        thread.start()
        assert claim_started.wait(timeout=2)
        assert claim_done.wait(timeout=2)
        thread.join(timeout=2)
        assert claim_errors == []
        assert claim_result["task"] is None

        updated = mutation_repository.update(slot_code, {"layer_name": "layer-after"})
        assert updated is not None
        assert updated["layer_name"] == "layer-after"

        claimed_after_mutation = mutation_repository.claim_next_retry_task(
            {
                "claimed_by": "worker-race",
                "lock_ttl_seconds": 60,
                "max_attempts": 3,
                "failure_type": failure_type,
            }
        )
        assert claimed_after_mutation is not None
        assert claimed_after_mutation["retry_task_code"] == retry_task_code
        assert claimed_after_mutation["layer_name"] == "layer-after"

        operation_plan = mutation_repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert operation_plan is not None
        assert operation_plan["operations"][0]["layer_name"] == "layer-before"

        with mutation_connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM maitu_retry_operation_checkpoints WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute("DELETE FROM maitu_material_slots WHERE slot_code = %s", (slot_code,))
        mutation_connection.commit()


def test_postgres_asset_binding_receipt_nonce_is_one_shot() -> None:
    asset_code = f"AG-IMG-IT-{uuid4().hex[:12]}"
    nonce = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assets (asset_code, asset_type, original_filename, status)
                VALUES (%s, 'IMG', 'nonce.png', 'stored')
                """,
                (asset_code,),
            )
        connection.commit()
        repository = AssetRepository(connection)
        payload = {
            "maitu_material_id": 901,
            "source_material_type": "image",
            "source_material_url": "https://cdn.example/nonce.png",
            "maitu_binding_verification_source": "maitu_inventory_readback",
            "maitu_binding_verified_at": datetime.now(UTC),
            "maitu_binding_scope": "assetgraph_script_layout_material_binding_v1",
            "maitu_binding_inventory_fingerprint": "a" * 64,
            "maitu_binding_readback_nonce": nonce,
            "maitu_binding_attestation": "b" * 64,
        }
        assert repository.update_maitu_material_binding(asset_code, payload) is not None
        with pytest.raises(AssetBindingReceiptReplayError, match="already consumed"):
            repository.update_maitu_material_binding(asset_code, payload)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM assets WHERE asset_code = %s", (asset_code,))
        connection.commit()


def test_postgres_asset_binding_update_and_claim_serialize_on_retry_task_row() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    asset_code = f"AG-IMG-IT-{retry_task_code[-12:]}"
    with psycopg.connect(DATABASE_URL) as setup_connection:
        _insert_retry_task(setup_connection, retry_task_code)
        with setup_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assets (
                    asset_code, asset_type, original_filename, status, maitu_material_id,
                    source_material_type, maitu_binding_verification_source,
                    maitu_binding_verified_at, maitu_binding_scope
                )
                VALUES (%s, 'IMG', 'binding-race.png', 'stored', 202, 'image',
                        'maitu_readback', %s, 'live_room:38336')
                ON CONFLICT (asset_code) DO UPDATE SET
                    maitu_material_id = EXCLUDED.maitu_material_id,
                    source_material_type = EXCLUDED.source_material_type,
                    maitu_binding_verification_source = EXCLUDED.maitu_binding_verification_source,
                    maitu_binding_verified_at = EXCLUDED.maitu_binding_verified_at,
                    maitu_binding_scope = EXCLUDED.maitu_binding_scope
                """,
                (asset_code, datetime(2026, 7, 11, tzinfo=UTC)),
            )
        setup_connection.commit()

    binding_started = threading.Event()
    binding_done = threading.Event()
    binding_pid: dict[str, int] = {}
    binding_result: dict[str, Any] = {}
    binding_errors: list[BaseException] = []

    with psycopg.connect(DATABASE_URL) as asset_blocker:
        with asset_blocker.cursor() as cursor:
            cursor.execute("SELECT asset_code FROM assets WHERE asset_code = %s FOR UPDATE", (asset_code,))
            assert cursor.fetchone() == (asset_code,)

        def update_binding_while_asset_row_is_locked() -> None:
            try:
                with psycopg.connect(DATABASE_URL) as binding_connection:
                    binding_pid["value"] = binding_connection.info.backend_pid
                    binding_started.set()
                    binding_result["row"] = AssetRepository(binding_connection).update_maitu_material_binding(
                        asset_code,
                        {"maitu_material_id": 203, "source_material_type": "image"},
                    )
            except BaseException as exc:  # pragma: no cover - parent assertion reports it
                binding_errors.append(exc)
            finally:
                binding_done.set()

        binding_thread = threading.Thread(target=update_binding_while_asset_row_is_locked)
        binding_thread.start()
        assert binding_started.wait(timeout=2)

        blocked_on_asset = False
        with psycopg.connect(DATABASE_URL) as observer:
            for _ in range(100):
                with observer.cursor() as cursor:
                    cursor.execute(
                        "SELECT wait_event_type, query FROM pg_stat_activity WHERE pid = %s",
                        (binding_pid["value"],),
                    )
                    activity = cursor.fetchone()
                if activity and activity[0] == "Lock" and "assets" in activity[1]:
                    blocked_on_asset = True
                    break
                time.sleep(0.02)
        assert blocked_on_asset is True

        with psycopg.connect(DATABASE_URL) as claim_connection:
            claimed_during_binding = MaituMaterialSlotRepository(claim_connection).claim_next_retry_task(
                {
                    "claimed_by": "worker-binding-race",
                    "lock_ttl_seconds": 60,
                    "max_attempts": 3,
                    "failure_type": "missing_layer",
                }
            )
        assert claimed_during_binding is None

        asset_blocker.rollback()
        assert binding_done.wait(timeout=5)
        binding_thread.join(timeout=5)

    assert binding_errors == []
    assert binding_result["row"]["maitu_material_id"] == 203

    with psycopg.connect(DATABASE_URL) as verify_connection:
        repository = MaituMaterialSlotRepository(verify_connection)
        claimed_after_binding = _claim(repository, "worker-binding-race")
        assert claimed_after_binding["retry_task_code"] == retry_task_code
        operation_plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert operation_plan is not None
        assert operation_plan["operations"][0]["maitu_material_id"] == 202
        with verify_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE maitu_execution_retry_tasks SET status = 'succeeded' WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute("DELETE FROM assets WHERE asset_code = %s", (asset_code,))
        verify_connection.commit()


def test_postgres_concurrent_duplicate_release_writes_one_receipt_without_attempt_increment() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    retry_execution_id = str(uuid4())
    with psycopg.connect(DATABASE_URL) as setup_connection:
        _insert_retry_task(setup_connection, retry_task_code)
        claim = _claim(MaituMaterialSlotRepository(setup_connection), "worker-a")

    payload = {
        "retry_execution_id": retry_execution_id,
        "retry_execution_status": "released",
        "claimed_by": "worker-a",
        "claim_token": claim["claim_token"],
        "lease_version": claim["lease_version"],
        "result_summary": "done",
    }
    barrier = threading.Barrier(2)
    rows: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def write_result() -> None:
        try:
            with psycopg.connect(DATABASE_URL) as connection:
                barrier.wait(timeout=5)
                row = MaituMaterialSlotRepository(connection).create_retry_task_execution_result(
                    retry_task_code, payload
                )
                assert row is not None
                rows.append(row)
        except BaseException as exc:  # captured and asserted in the parent thread
            errors.append(exc)

    threads = [threading.Thread(target=write_result) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(rows) == 2
    with psycopg.connect(DATABASE_URL) as verify_connection:
        with verify_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT retry_attempt_count,
                       (SELECT count(*) FROM maitu_retry_execution_receipts WHERE retry_execution_id = %s)
                FROM maitu_execution_retry_tasks
                WHERE retry_task_code = %s
                """,
                (retry_execution_id, retry_task_code),
            )
            assert cursor.fetchone() == (0, 1)

        conflicting_payload = {**payload, "result_summary": "different"}
        with pytest.raises(RetryExecutionConflictError):
            MaituMaterialSlotRepository(verify_connection).create_retry_task_execution_result(
                retry_task_code, conflicting_payload
            )
