from __future__ import annotations

import os
import threading
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from app.repositories.maitu import MaituMaterialSlotRepository, RetryExecutionConflictError, RetryLeaseConflictError


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _insert_retry_task(connection: psycopg.Connection[Any], retry_task_code: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO maitu_execution_retry_tasks (
                retry_task_code, plan_code, execution_code, failure_type,
                retryable, status, retry_attempt_count
            )
            VALUES (%s, %s, %s, 'missing_layer', true, 'pending', 0)
            """,
            (retry_task_code, f"PLAN-{retry_task_code}", f"EXEC-{retry_task_code}"),
        )
    connection.commit()


def _claim(repository: MaituMaterialSlotRepository, worker_id: str) -> dict[str, Any]:
    claimed = repository.claim_next_retry_task(
        {"claimed_by": worker_id, "lock_ttl_seconds": 60, "max_attempts": 3}
    )
    assert claimed is not None
    return claimed


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


def test_postgres_concurrent_duplicate_result_increments_attempt_once() -> None:
    retry_task_code = f"MT-RETRY-IT-{uuid4().hex[:12]}"
    retry_execution_id = str(uuid4())
    with psycopg.connect(DATABASE_URL) as setup_connection:
        _insert_retry_task(setup_connection, retry_task_code)
        claim = _claim(MaituMaterialSlotRepository(setup_connection), "worker-a")

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
