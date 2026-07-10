from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

import pytest

from app.repositories.maitu import (
    MaituMaterialSlotRepository,
    RetryExecutionConflictError,
    RetryLeaseConflictError,
)


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, query: str, values: tuple[Any, ...] | None = None) -> None:
        self.connection.executed.append((query, values or ()))

    def fetchone(self) -> Any:
        return self.connection.fetchone_results.pop(0)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.connection.fetchall_results.pop(0)


class FakeConnection:
    def __init__(
        self,
        *,
        fetchone_results: list[Any] | None = None,
        fetchall_results: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.fetchone_results = fetchone_results or []
        self.fetchall_results = fetchall_results or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def lease_payload() -> dict[str, Any]:
    return {
        "claimed_by": "worker-1",
        "claim_token": UUID("c1a1d000-0000-4000-8000-000000000001"),
        "lease_version": 2,
    }


def task_row(*, status: str = "in_progress", lease_active: bool = True) -> dict[str, Any]:
    return {
        "id": UUID("85000000-0000-0000-0000-000000000001"),
        "retry_task_code": "MT-RETRY-20260710-000001",
        "status": status,
        "claimed_by": "worker-1" if status == "in_progress" else None,
        "claim_token": UUID("c1a1d000-0000-4000-8000-000000000001") if status == "in_progress" else None,
        "lease_version": 2,
        "claim_expires_at": "2026-07-10T12:00:00Z" if status == "in_progress" else None,
        "retry_attempt_count": 0 if status == "in_progress" else 1,
        "lease_active": lease_active,
    }


def result_payload() -> dict[str, Any]:
    return {
        **lease_payload(),
        "retry_execution_id": UUID("7be4e98f-dd31-4c50-97d6-604d46ec7869"),
        "retry_execution_status": "succeeded",
        "result_summary": "done",
    }


def payload_fingerprint(payload: dict[str, Any]) -> str:
    serializable = json.loads(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True))
    return hashlib.sha256(
        json.dumps(serializable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def test_claim_generates_new_token_and_increments_lease_version_atomically() -> None:
    claimed_row = {
        **task_row(),
        "claim_token": UUID("c1a1d000-0000-4000-8000-000000000002"),
        "maitu_project_code": None,
        "scene_name": None,
        "slot_name": None,
        "layer_name": None,
        "failure_type": "missing_layer",
    }
    claimed_row.pop("lease_active")
    connection = FakeConnection(fetchone_results=[claimed_row])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.claim_next_retry_task(
        {"claimed_by": "worker-1", "lock_ttl_seconds": 120, "max_attempts": 3}
    )

    assert result is not None
    assert result["claim_token"] == "c1a1d000-0000-4000-8000-000000000002"
    claim_sql = connection.executed[0][0]
    assert "claim_token = gen_random_uuid()" in claim_sql
    assert "lease_version = lease_version + 1" in claim_sql
    assert "FOR UPDATE OF rt SKIP LOCKED" in claim_sql
    assert "RETURNING rt.*" in claim_sql
    assert len(connection.executed) == 1
    assert connection.commit_count == 1


def test_heartbeat_is_conditioned_on_full_unexpired_lease_identity() -> None:
    renewed = task_row()
    renewed.pop("lease_active")
    connection = FakeConnection(fetchone_results=[renewed])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.heartbeat_retry_task(
        "MT-RETRY-20260710-000001",
        {**lease_payload(), "lock_ttl_seconds": 120},
    )

    assert result is not None
    heartbeat_sql, values = connection.executed[0]
    assert "status = 'in_progress'" in heartbeat_sql
    assert "claimed_by = %s" in heartbeat_sql
    assert "claim_token = %s" in heartbeat_sql
    assert "lease_version = %s" in heartbeat_sql
    assert "claim_expires_at >= now()" in heartbeat_sql
    assert values == (
        120,
        "MT-RETRY-20260710-000001",
        "worker-1",
        lease_payload()["claim_token"],
        2,
    )


def test_release_rejects_stale_lease_when_task_still_exists() -> None:
    existing = task_row()
    existing.pop("lease_active")
    connection = FakeConnection(fetchone_results=[None, existing])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryLeaseConflictError):
        repository.release_retry_task(
            "MT-RETRY-20260710-000001",
            {**lease_payload(), "status": "pending"},
        )

    release_sql = connection.executed[0][0]
    assert "claim_token = %s" in release_sql
    assert "lease_version = %s" in release_sql
    assert "claim_expires_at >= now()" in release_sql


def test_metadata_patch_rejects_in_progress_task() -> None:
    existing = task_row()
    existing.pop("lease_active")
    connection = FakeConnection(fetchone_results=[None, existing])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryLeaseConflictError):
        repository.update_retry_task(
            "MT-RETRY-20260710-000001",
            {"result_summary": "manual note"},
        )

    update_sql = connection.executed[0][0]
    assert "status <> 'in_progress'" in update_sql
    assert "retry_attempt_count" not in update_sql


def test_execution_result_updates_task_and_inserts_receipt_in_one_transaction() -> None:
    updated = {
        **task_row(status="succeeded"),
        "last_retry_execution_id": UUID("7be4e98f-dd31-4c50-97d6-604d46ec7869"),
    }
    updated.pop("lease_active")
    connection = FakeConnection(
        fetchone_results=[
            task_row(),
            None,
            updated,
            {"retry_execution_id": UUID("7be4e98f-dd31-4c50-97d6-604d46ec7869")},
        ]
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.create_retry_task_execution_result(
        "MT-RETRY-20260710-000001",
        result_payload(),
    )

    assert result is not None
    assert result["last_retry_execution_id"] == "7be4e98f-dd31-4c50-97d6-604d46ec7869"
    update_sql = connection.executed[2][0]
    assert "retry_attempt_count = retry_attempt_count + 1" in update_sql
    assert "claim_token = %s" in update_sql
    assert "claim_expires_at >= now()" in update_sql
    assert "INSERT INTO maitu_retry_execution_receipts" in connection.executed[3][0]
    receipt_values = connection.executed[3][1]
    assert "claim_token" not in receipt_values[-1].obj
    assert connection.commit_count == 1
    assert connection.rollback_count == 0


def test_released_execution_result_returns_task_to_pending_without_incrementing_attempt() -> None:
    updated = {
        **task_row(status="pending"),
        "retry_attempt_count": 0,
        "last_retry_execution_id": UUID("7be4e98f-dd31-4c50-97d6-604d46ec7869"),
    }
    updated.pop("lease_active")
    payload = {**result_payload(), "retry_execution_status": "released"}
    connection = FakeConnection(
        fetchone_results=[
            task_row(),
            None,
            updated,
            {"retry_execution_id": UUID("7be4e98f-dd31-4c50-97d6-604d46ec7869")},
        ]
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.create_retry_task_execution_result("MT-RETRY-20260710-000001", payload)

    assert result is not None
    assert result["status"] == "pending"
    assert result["retry_attempt_count"] == 0
    update_sql = connection.executed[2][0]
    assert "retry_attempt_count = retry_attempt_count + 1" not in update_sql
    assert "INSERT INTO maitu_retry_execution_receipts" in connection.executed[3][0]


def test_duplicate_execution_result_returns_without_second_task_update() -> None:
    payload = result_payload()
    terminal_task = task_row(status="succeeded")
    connection = FakeConnection(
        fetchone_results=[
            terminal_task,
            {
                "retry_task_code": "MT-RETRY-20260710-000001",
                "result_fingerprint": payload_fingerprint(payload),
            },
        ]
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.create_retry_task_execution_result("MT-RETRY-20260710-000001", payload)

    assert result is not None
    assert result["retry_attempt_count"] == 1
    assert len(connection.executed) == 2
    assert connection.commit_count == 1


def test_execution_id_reuse_with_different_fingerprint_rolls_back() -> None:
    connection = FakeConnection(
        fetchone_results=[
            task_row(status="succeeded"),
            {
                "retry_task_code": "MT-RETRY-20260710-000001",
                "result_fingerprint": "0" * 64,
            },
        ]
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryExecutionConflictError):
        repository.create_retry_task_execution_result("MT-RETRY-20260710-000001", result_payload())

    assert connection.rollback_count == 1
