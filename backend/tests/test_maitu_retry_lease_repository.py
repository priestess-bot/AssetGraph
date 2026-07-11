from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.repositories.maitu import (
    MaituMaterialSlotRepository,
    RetryCheckpointConflictError,
    RetryExecutionConflictError,
    RetryLeaseConflictError,
)
from app.schemas.maitu import (
    MaituRetryOperationCheckpointBeginCreate,
    MaituRetryOperationCheckpointCompleteCreate,
    MaituRetryTaskExecutionResultCreate,
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
        "plan_code": "MT-PLAN-20260710-000001",
        "execution_code": "MT-EXEC-20260710-000001",
        "slot_code": "MT-SLOT-20260710-000001",
        "asset_code": "AG-IMG-20260710-000001",
        "failure_type": "missing_layer",
        "retryable": True,
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


def checkpoint_payload() -> dict[str, Any]:
    return {
        **lease_payload(),
        "attempt_id": "5a1b01df-90fd-4f9e-90c7-5694650f0022",
        "completion_id": "acb52bd1-f87d-438c-95b2-00f7f20c03a5",
        "operation_fingerprint": "a" * 64,
        "result_summary": "verified completion",
        "evidence": {"verified": True},
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
    operation_fingerprints = {
        operation["operation_key"]: operation["operation_fingerprint"]
        for operation in MaituMaterialSlotRepository._build_retry_operations(task_row(), {}, {}, {})
    }
    connection = FakeConnection(
        fetchone_results=[
            task_row(),
            None,
            {},
            {},
            updated,
            {"retry_execution_id": UUID("7be4e98f-dd31-4c50-97d6-604d46ec7869")},
        ],
        fetchall_results=[
            [
                {
                    "operation_key": "primary",
                    "operation_fingerprint": operation_fingerprints["primary"],
                    "state": "completed",
                    "completion_evidence": {"verified": True, "operation_key": "primary"},
                },
                {
                    "operation_key": "save_project",
                    "operation_fingerprint": operation_fingerprints["save_project"],
                    "state": "completed",
                    "completion_evidence": {"verified": True, "operation_key": "save_project"},
                },
            ]
        ],
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.create_retry_task_execution_result(
        "MT-RETRY-20260710-000001",
        result_payload(),
    )

    assert result is not None
    assert result["last_retry_execution_id"] == "7be4e98f-dd31-4c50-97d6-604d46ec7869"
    update_sql = connection.executed[5][0]
    assert "retry_attempt_count = retry_attempt_count + 1" in update_sql
    assert "claim_token = %s" in update_sql
    assert "claim_expires_at >= now()" in update_sql
    assert "INSERT INTO maitu_retry_execution_receipts" in connection.executed[6][0]
    receipt_values = connection.executed[6][1]
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
    reconcile_sql = connection.executed[2][0]
    assert "state = 'reconcile_required'" in reconcile_sql
    update_sql = connection.executed[3][0]
    assert "retry_attempt_count = retry_attempt_count + 1" not in update_sql
    assert "INSERT INTO maitu_retry_execution_receipts" in connection.executed[4][0]


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


def test_succeeded_execution_result_requires_all_operation_checkpoints_completed() -> None:
    connection = FakeConnection(
        fetchone_results=[task_row(), None],
        fetchall_results=[[]],
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="checkpoints"):
        repository.create_retry_task_execution_result(
            "MT-RETRY-20260710-000001",
            result_payload(),
        )

    assert connection.rollback_count == 1
    assert all("UPDATE maitu_execution_retry_tasks" not in query for query, _values in connection.executed)


def test_succeeded_execution_result_rejects_completed_checkpoint_fingerprint_drift() -> None:
    operation_fingerprints = {
        operation["operation_key"]: operation["operation_fingerprint"]
        for operation in MaituMaterialSlotRepository._build_retry_operations(task_row(), {}, {}, {})
    }
    connection = FakeConnection(
        fetchone_results=[task_row(), None, {}, {}],
        fetchall_results=[
            [
                {
                    "operation_key": "primary",
                    "operation_fingerprint": "f" * 64,
                    "state": "completed",
                    "completion_evidence": {"verified": True, "operation_key": "primary"},
                },
                {
                    "operation_key": "save_project",
                    "operation_fingerprint": operation_fingerprints["save_project"],
                    "state": "completed",
                    "completion_evidence": {"verified": True, "operation_key": "save_project"},
                },
            ]
        ],
    )
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="fingerprint drifted"):
        repository.create_retry_task_execution_result(
            "MT-RETRY-20260710-000001",
            result_payload(),
        )

    assert connection.rollback_count == 1


def test_retry_operation_plan_has_stable_primary_and_save_checkpoint_identities() -> None:
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]
    task = {
        "retry_task_code": "MT-RETRY-20260710-000001",
        "plan_code": "MT-PLAN-20260710-000001",
        "execution_code": "MT-EXEC-20260710-000001",
        "slot_code": "MT-SLOT-20260710-000001",
        "asset_code": "AG-IMG-20260710-000001",
        "executor": "browser_use",
        "failure_type": "missing_layer",
        "retryable": True,
        "status": "pending",
        "retry_instruction": "transient instruction",
        "claim_token": "secret-token",
        "lease_version": 1,
    }
    plan = {
        "maitu_project_code": "MT-PROJ-1",
        "scene_name": "scene-a",
        "items": [
            {
                "slot_code": task["slot_code"],
                "slot_name": "hero",
                "selected_asset_title": "hero.png",
                "replacement_policy": "keep_layout",
            }
        ],
    }
    slot = {"scene_name": "scene-a", "layer_name": "layer-8", "slot_name": "hero"}
    repository.get_retry_task_by_code = lambda _code: dict(task)  # type: ignore[method-assign]
    repository.get_replacement_plan_by_code = lambda _code: dict(plan)  # type: ignore[method-assign]
    repository.get_by_code = lambda _code: dict(slot)  # type: ignore[method-assign]

    first = repository.get_retry_task_browser_use_operation_plan(task["retry_task_code"])
    task.update(status="in_progress", retry_instruction="changed", claim_token="other", lease_version=2)
    second = repository.get_retry_task_browser_use_operation_plan(task["retry_task_code"])

    assert first is not None and second is not None
    assert [operation["operation_key"] for operation in first["operations"]] == ["primary", "save_project"]
    assert [operation["operation_fingerprint"] for operation in first["operations"]] == [
        operation["operation_fingerprint"] for operation in second["operations"]
    ]
    assert all(len(operation["operation_fingerprint"]) == 64 for operation in first["operations"])

    task["asset_code"] = "AG-IMG-20260710-000002"
    changed = repository.get_retry_task_browser_use_operation_plan(task["retry_task_code"])
    assert changed is not None
    assert [operation["operation_fingerprint"] for operation in changed["operations"]] != [
        operation["operation_fingerprint"] for operation in first["operations"]
    ]


def test_save_failure_operation_plan_contains_exactly_one_save() -> None:
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]
    task = {
        "retry_task_code": "MT-RETRY-20260710-000001",
        "plan_code": "MT-PLAN-20260710-000001",
        "execution_code": "MT-EXEC-20260710-000001",
        "failure_type": "save_failed",
        "retryable": True,
        "status": "pending",
    }
    repository.get_retry_task_by_code = lambda _code: task  # type: ignore[method-assign]
    repository.get_replacement_plan_by_code = lambda _code: {"maitu_project_code": "MT-PROJ-1", "items": []}  # type: ignore[method-assign]

    result = repository.get_retry_task_browser_use_operation_plan(task["retry_task_code"])

    assert result is not None
    assert [(operation["operation_key"], operation["operation_type"]) for operation in result["operations"]] == [
        ("save_project", "retry_save_project")
    ]


def test_begin_checkpoint_rejects_request_fingerprint_drift() -> None:
    task = task_row()
    task["plan_code"] = "MT-PLAN-20260710-000001"
    task["execution_code"] = "MT-EXEC-20260710-000001"
    task["failure_type"] = "save_failed"
    connection = FakeConnection(fetchone_results=[task, {"maitu_project_code": "MT-PROJ-1"}])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="fingerprint"):
        repository.begin_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "save_project",
            {
                **lease_payload(),
                "attempt_id": UUID("aaaaaaaa-0000-4000-8000-000000000001"),
                "operation_fingerprint": "0" * 64,
            },
        )

    assert connection.rollback_count == 1


def test_reclaim_marks_only_begun_checkpoints_reconcile_required_in_same_statement() -> None:
    connection = FakeConnection(fetchall_results=[[{"retry_task_code": "MT-RETRY-20260710-000001"}]])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.reclaim_expired_retry_tasks()

    assert result["reclaimed_count"] == 1
    reclaim_sql = connection.executed[0][0]
    assert "maitu_retry_operation_checkpoints" in reclaim_sql
    assert "state = 'reconcile_required'" in reclaim_sql
    assert "checkpoint.state = 'begun'" in reclaim_sql
    assert connection.commit_count == 1


@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"verified": False},
        {"verified": True, "Authorization": "Bearer secret"},
        {"verified": True, "readback": {"api-token": "secret"}},
        {"verified": True, "context": {"value": "c1a1d000-0000-4000-8000-000000000001"}},
    ],
)
def test_checkpoint_complete_schema_rejects_unverified_or_secret_evidence(evidence: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MaituRetryOperationCheckpointCompleteCreate(
            **lease_payload(),
            attempt_id=UUID("aaaaaaaa-0000-4000-8000-000000000001"),
            operation_fingerprint="a" * 64,
            completion_id=UUID("bbbbbbbb-0000-4000-8000-000000000001"),
            evidence=evidence,
        )


@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"verified": False},
        {"verified": True, "authorization": "Bearer secret"},
        {"verified": True, "context": {"value": "prefix-c1a1d000-0000-4000-8000-000000000001-suffix"}},
    ],
)
def test_repository_rejects_unverified_or_secret_checkpoint_evidence(evidence: dict[str, Any]) -> None:
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="evidence"):
        repository.complete_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "primary",
            {
                **lease_payload(),
                "attempt_id": UUID("aaaaaaaa-0000-4000-8000-000000000001"),
                "operation_fingerprint": "a" * 64,
                "completion_id": UUID("bbbbbbbb-0000-4000-8000-000000000001"),
                "evidence": evidence,
            },
        )


def test_release_marks_current_lease_begun_checkpoints_reconcile_before_commit() -> None:
    released = task_row(status="pending")
    connection = FakeConnection(fetchone_results=[released])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    result = repository.release_retry_task(
        "MT-RETRY-20260710-000001",
        {**lease_payload(), "status": "pending"},
    )

    assert result is not None
    sql = "\n".join(query for query, _values in connection.executed)
    assert "maitu_retry_operation_checkpoints" in sql
    assert "state = 'reconcile_required'" in sql
    assert "begun_by = %s" in sql
    assert "begun_lease_version = %s" in sql
    assert connection.commit_count == 1


def test_slot_update_rejects_active_retry_lease_after_locking_related_tasks() -> None:
    connection = FakeConnection(fetchall_results=[[{"status": "in_progress"}]])
    repository = MaituMaterialSlotRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(RetryLeaseConflictError, match="authoritative intent"):
        repository.update("MT-SLOT-20260710-000001", {"layer_name": "changed-layer"})

    assert "FOR UPDATE" in connection.executed[0][0]
    assert connection.rollback_count == 1


@pytest.mark.parametrize("field_name", ["result_summary", "error_message", "retry_instruction"])
def test_execution_result_schema_rejects_claim_token_in_text_fields(field_name: str) -> None:
    payload = {
        **result_payload(),
        field_name: f"unsafe {lease_payload()['claim_token']} value",
    }
    with pytest.raises(ValidationError, match="claim token"):
        MaituRetryTaskExecutionResultCreate(**payload)


@pytest.mark.parametrize("field_name", ["result_summary", "error_message", "retry_instruction"])
def test_repository_rejects_claim_token_hidden_in_execution_result_text(field_name: str) -> None:
    payload = {
        **result_payload(),
        field_name: f"unsafe {lease_payload()['claim_token']} value",
    }
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryExecutionConflictError, match="claim token"):
        repository.create_retry_task_execution_result("MT-RETRY-20260710-000001", payload)


def test_checkpoint_complete_schema_rejects_claim_token_as_evidence_key() -> None:
    token = str(lease_payload()["claim_token"])
    payload = checkpoint_payload()
    payload["evidence"] = {"verified": True, token: "readback"}

    with pytest.raises(ValidationError, match="claim token"):
        MaituRetryOperationCheckpointCompleteCreate(**payload)


def test_repository_rejects_claim_token_as_evidence_key() -> None:
    token = str(lease_payload()["claim_token"])
    payload = checkpoint_payload()
    payload["evidence"] = {"verified": True, token: "readback"}
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="claim token"):
        repository.complete_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "primary",
            payload,
        )


def test_checkpoint_begin_schema_rejects_attempt_id_equal_to_claim_token() -> None:
    token = lease_payload()["claim_token"]
    with pytest.raises(ValidationError, match="attempt_id"):
        MaituRetryOperationCheckpointBeginCreate(
            **lease_payload(),
            attempt_id=token,
            operation_fingerprint="a" * 64,
        )


def test_repository_rejects_attempt_id_equal_to_claim_token() -> None:
    token = lease_payload()["claim_token"]
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="attempt_id"):
        repository.begin_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "primary",
            {
                **lease_payload(),
                "attempt_id": token,
                "operation_fingerprint": "a" * 64,
            },
        )


@pytest.mark.parametrize("equivalent_token", ["upper", "compact"])
def test_repository_rejects_semantically_equal_attempt_id(equivalent_token: str) -> None:
    token = lease_payload()["claim_token"]
    rendered = str(token).upper() if equivalent_token == "upper" else str(token).replace("-", "")
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="attempt_id"):
        repository.begin_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "primary",
            {
                **lease_payload(),
                "attempt_id": rendered,
                "operation_fingerprint": "a" * 64,
            },
        )


def test_checkpoint_complete_schema_rejects_completion_id_equal_to_claim_token() -> None:
    token = lease_payload()["claim_token"]
    payload = checkpoint_payload()
    payload["completion_id"] = token

    with pytest.raises(ValidationError, match="completion_id"):
        MaituRetryOperationCheckpointCompleteCreate(**payload)


def test_repository_rejects_completion_id_equal_to_claim_token() -> None:
    token = lease_payload()["claim_token"]
    payload = checkpoint_payload()
    payload["completion_id"] = token
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="completion_id"):
        repository.complete_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "primary",
            payload,
        )


@pytest.mark.parametrize("equivalent_token", ["upper", "compact"])
def test_repository_rejects_semantically_equal_completion_id(equivalent_token: str) -> None:
    token = lease_payload()["claim_token"]
    rendered = str(token).upper() if equivalent_token == "upper" else str(token).replace("-", "")
    payload = checkpoint_payload()
    payload["completion_id"] = rendered
    repository = MaituMaterialSlotRepository(FakeConnection())  # type: ignore[arg-type]

    with pytest.raises(RetryCheckpointConflictError, match="completion_id"):
        repository.complete_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            "primary",
            payload,
        )
