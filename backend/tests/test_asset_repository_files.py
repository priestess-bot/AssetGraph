from __future__ import annotations

from typing import Any

import pytest

from app.repositories.assets import AssetBindingLeaseConflictError, AssetRepository


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, values: tuple[Any, ...] = ()) -> None:
        self.connection.executed.append((" ".join(query.split()), values))

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None:
        return self.connection.fetchone_results.pop(0)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.connection.fetchall_results.pop(0)


class FakeConnection:
    def __init__(self, *, fetchone_results: list[Any] | None = None, fetchall_results: list[list[dict[str, Any]]] | None = None) -> None:
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


def test_get_by_local_file_code_returns_matching_asset() -> None:
    connection = FakeConnection(fetchone_results=[{"id": "asset-id", "asset_code": "AG-VID-20260709-000001"}])
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    row = repository.get_by_local_file_code("maitu", "MT-VID-0024")

    assert row == {"id": "asset-id", "asset_code": "AG-VID-20260709-000001"}
    assert connection.executed[0][1] == ("maitu", "MT-VID-0024")


def test_create_file_record_inserts_for_existing_asset_and_commits() -> None:
    connection = FakeConnection(
        fetchone_results=[
            {"id": "asset-id"},
            {
                "id": "file-id",
                "asset_id": "asset-id",
                "asset_code": "AG-VID-20260709-000001",
                "file_role": "original",
                "bucket_name": "assetgraph",
                "object_key": "assets/AG-VID-20260709-000001/original/demo.mp4",
                "local_file_code": "MT-VID-0024",
            },
        ]
    )
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    row = repository.create_file_record(
        "AG-VID-20260709-000001",
        {
            "file_role": "original",
            "bucket_name": "assetgraph",
            "object_key": "assets/AG-VID-20260709-000001/original/demo.mp4",
            "mime_type": "video/mp4",
            "file_size": 123,
            "checksum_sha256": "a" * 64,
            "source_relative_path": "视频/demo.mp4",
            "local_file_code": "MT-VID-0024",
            "storage_status": "stored",
        },
    )

    assert row is not None
    assert row["object_key"] == "assets/AG-VID-20260709-000001/original/demo.mp4"
    assert connection.commit_count == 1
    assert "INSERT INTO asset_files" in connection.executed[1][0]


def test_create_file_record_returns_none_when_asset_missing() -> None:
    connection = FakeConnection(fetchone_results=[None])
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    assert repository.create_file_record("AG-MISSING", {"file_role": "original"}) is None
    assert connection.commit_count == 0


def test_list_file_records_returns_asset_files() -> None:
    connection = FakeConnection(fetchall_results=[[{"asset_code": "AG-IMG-1", "file_role": "original"}]])
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    assert repository.list_file_records("AG-IMG-1") == [{"asset_code": "AG-IMG-1", "file_role": "original"}]


def test_update_status_returns_updated_asset_and_commits() -> None:
    connection = FakeConnection(fetchone_results=[{"asset_code": "AG-IMG-1", "status": "stored"}])
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    row = repository.update_status("AG-IMG-1", "stored")

    assert row == {"asset_code": "AG-IMG-1", "status": "stored"}
    assert connection.commit_count == 1


def test_material_binding_update_is_blocked_during_active_retry_lease() -> None:
    connection = FakeConnection(
        fetchall_results=[[{"retry_task_code": "MT-RETRY-1", "status": "in_progress", "lease_active": True}]]
    )
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(AssetBindingLeaseConflictError, match="active retry worker lease"):
        repository.update_maitu_material_binding(
            "AG-IMG-1",
            {
                "maitu_material_id": 202,
                "source_material_type": "image",
                "source_material_url": "https://example.invalid/material/202.png",
            },
        )

    assert connection.rollback_count == 1
    assert len(connection.executed) == 1
    assert "maitu_execution_retry_tasks" in connection.executed[0][0]
    assert "FOR UPDATE" in connection.executed[0][0]


def test_material_binding_update_locks_pending_retry_tasks_before_asset_mutation() -> None:
    updated = {
        "asset_code": "AG-IMG-1",
        "maitu_material_id": 203,
        "source_material_type": "image",
    }
    connection = FakeConnection(
        fetchone_results=[{"maitu_binding_readback_nonce": None}, updated],
        fetchall_results=[[{"retry_task_code": "MT-RETRY-1", "status": "pending", "lease_active": False}]],
    )

    row = AssetRepository(connection).update_maitu_material_binding(
        "AG-IMG-1",
        {"maitu_material_id": 203, "source_material_type": "image"},
    )

    assert row == updated
    lock_sql = connection.executed[0][0]
    lock_where = lock_sql.split("WHERE", 1)[1]
    assert "status = 'in_progress'" not in lock_where
    assert "claim_expires_at >= now()" not in lock_where
    assert "ORDER BY retry_task_code" in lock_sql
    assert "FOR UPDATE" in lock_sql


def test_material_binding_update_clears_previous_verification_metadata() -> None:
    updated = {
        "asset_code": "AG-IMG-1",
        "maitu_material_id": 202,
        "source_material_type": "image",
        "maitu_binding_verification_source": None,
        "maitu_binding_verified_at": None,
        "maitu_binding_scope": None,
    }
    connection = FakeConnection(
        fetchone_results=[{"maitu_binding_readback_nonce": None}, updated], fetchall_results=[[]]
    )
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    row = repository.update_maitu_material_binding(
        "AG-IMG-1",
        {
            "maitu_material_id": 202,
            "source_material_type": "image",
        },
    )

    assert row == updated
    assert connection.commit_count == 1
    update_sql, values = connection.executed[2]
    assert "maitu_binding_verification_source = %s" in update_sql
    assert "maitu_binding_verified_at = %s" in update_sql
    assert "maitu_binding_scope = %s" in update_sql
    assert "maitu_binding_inventory_fingerprint = %s" in update_sql
    assert "maitu_binding_readback_nonce = %s" in update_sql
    assert "maitu_binding_attestation = %s" in update_sql
    assert values[-7:-1] == (None, None, None, None, None, None)
