from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from app.repositories.maitu import (
    MaituMaterialSlotRepository,
    RetryCheckpointConflictError,
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
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO maitu_execution_retry_tasks (
                retry_task_code, plan_code, execution_code, slot_code, failure_type,
                retryable, status, retry_attempt_count
            )
            VALUES (%s, %s, %s, %s, %s, true, 'pending', 0)
            """,
            (
                retry_task_code,
                f"PLAN-{retry_task_code}",
                f"EXEC-{retry_task_code}",
                slot_code,
                failure_type,
            ),
        )
    connection.commit()


def _claim(repository: MaituMaterialSlotRepository, worker_id: str) -> dict[str, Any]:
    claimed = repository.claim_next_retry_task(
        {"claimed_by": worker_id, "lock_ttl_seconds": 60, "max_attempts": 3}
    )
    assert claimed is not None
    return claimed


def _complete_all_checkpoints(
    repository: MaituMaterialSlotRepository,
    retry_task_code: str,
    claim: dict[str, Any],
    *,
    worker_id: str = "worker-a",
) -> list[dict[str, Any]]:
    plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
    assert plan is not None
    completed: list[dict[str, Any]] = []
    for operation in plan["operations"]:
        attempt_id = uuid4()
        begin_payload = {
            "claimed_by": worker_id,
            "claim_token": claim["claim_token"],
            "lease_version": claim["lease_version"],
            "attempt_id": attempt_id,
            "operation_fingerprint": operation["operation_fingerprint"],
        }
        begun = repository.begin_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            begin_payload,
        )
        assert begun is not None and begun["decision"] == "execute"
        completion = repository.complete_retry_operation_checkpoint(
            retry_task_code,
            operation["operation_key"],
            {
                **begin_payload,
                "completion_id": uuid4(),
                "evidence": {"verified": True, "operation_key": operation["operation_key"]},
            },
        )
        assert completion is not None and completion["state"] == "completed"
        completed.append(completion)
    return completed


def test_postgres_operation_checkpoint_migration_replays() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "017_maitu_retry_operation_checkpoints.sql"
    ).read_text(encoding="utf-8")
    reconciliation_migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "018_maitu_retry_operation_reconciliation.sql"
    ).read_text(encoding="utf-8")
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(reconciliation_migration)
            cursor.execute(migration)
            cursor.execute(reconciliation_migration)
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
                "DELETE FROM maitu_execution_retry_tasks WHERE retry_task_code = %s",
                (retry_task_code,),
            )
        connection.commit()


def test_postgres_checkpoint_complete_skips_and_old_begun_requires_reconciliation() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code)
        first_claim = _claim(repository, "worker-a")
        plan = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
        assert plan is not None
        primary, save = plan["operations"]

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
        save_attempt = uuid4()
        save_begin_payload = {
            "claimed_by": "worker-a",
            "claim_token": first_claim["claim_token"],
            "lease_version": first_claim["lease_version"],
            "attempt_id": save_attempt,
            "operation_fingerprint": save["operation_fingerprint"],
        }
        repository.begin_retry_operation_checkpoint(retry_task_code, save["operation_key"], save_begin_payload)

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
            assert cursor.fetchall() == [("primary", "completed"), ("save_project", "reconcile_required")]

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
        save_reconcile = repository.begin_retry_operation_checkpoint(
            retry_task_code,
            save["operation_key"],
            {
                "claimed_by": "worker-b",
                "claim_token": second_claim["claim_token"],
                "lease_version": second_claim["lease_version"],
                "attempt_id": uuid4(),
                "operation_fingerprint": save["operation_fingerprint"],
            },
        )

        assert primary_skip is not None and primary_skip["decision"] == "skip"
        assert save_reconcile is not None and save_reconcile["decision"] == "reconcile"
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
                "DELETE FROM maitu_execution_retry_tasks WHERE retry_task_code = %s",
                (retry_task_code,),
            )
        connection.commit()


def test_postgres_confirmed_completion_reconciliation_is_idempotent_and_skips_replay() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    reconciliation_id = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        repository = MaituMaterialSlotRepository(connection)
        _insert_retry_task(connection, retry_task_code, failure_type="save_failed")
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
            "resolution_summary": "authoritative readback confirmed save",
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
                UPDATE maitu_retry_operation_reconciliations
                SET resolved_by = 'operator-TAMPERED'
                WHERE reconciliation_id = %s
                """,
                (reconciliation_id,),
            )
        connection.commit()
        with pytest.raises(RetryCheckpointConflictError, match="does not prove"):
            repository.create_retry_task_execution_result(
                retry_task_code,
                {
                    "retry_execution_id": uuid4(),
                    "retry_execution_status": "succeeded",
                    "claimed_by": "worker-b",
                    "claim_token": second_claim["claim_token"],
                    "lease_version": second_claim["lease_version"],
                    "result_summary": "tampered reconciliation receipt must not be accepted",
                },
            )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE maitu_retry_operation_reconciliations
                SET resolved_by = 'operator-it'
                WHERE reconciliation_id = %s
                """,
                (reconciliation_id,),
            )
        connection.commit()

        succeeded = repository.create_retry_task_execution_result(
            retry_task_code,
            {
                "retry_execution_id": uuid4(),
                "retry_execution_status": "succeeded",
                "claimed_by": "worker-b",
                "claim_token": second_claim["claim_token"],
                "lease_version": second_claim["lease_version"],
                "result_summary": "reconciliation-backed completion accepted",
            },
        )
        assert succeeded is not None and succeeded["status"] == "succeeded"

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
            cursor.execute("DELETE FROM maitu_execution_retry_tasks WHERE retry_task_code = %s", (retry_task_code,))
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
                "DELETE FROM maitu_execution_retry_tasks WHERE retry_task_code = %s",
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
        assert operation_plan["operations"][0]["layer_name"] == "layer-after"

        with mutation_connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM maitu_retry_operation_checkpoints WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute(
                "DELETE FROM maitu_execution_retry_tasks WHERE retry_task_code = %s",
                (retry_task_code,),
            )
            cursor.execute("DELETE FROM maitu_material_slots WHERE slot_code = %s", (slot_code,))
        mutation_connection.commit()


def test_postgres_concurrent_duplicate_result_increments_attempt_once() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    retry_execution_id = str(uuid4())
    with psycopg.connect(DATABASE_URL) as setup_connection:
        _insert_retry_task(setup_connection, retry_task_code)
        claim = _claim(MaituMaterialSlotRepository(setup_connection), "worker-a")
        _complete_all_checkpoints(
            MaituMaterialSlotRepository(setup_connection),
            retry_task_code,
            claim,
        )

    payload = {
        "retry_execution_id": retry_execution_id,
        "retry_execution_status": "succeeded",
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
            assert cursor.fetchone() == (1, 1)

        conflicting_payload = {**payload, "result_summary": "different"}
        with pytest.raises(RetryExecutionConflictError):
            MaituMaterialSlotRepository(verify_connection).create_retry_task_execution_result(
                retry_task_code, conflicting_payload
            )
