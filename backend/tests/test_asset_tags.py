from __future__ import annotations

from typing import Any

from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetCreate


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, values: tuple[Any, ...] = ()) -> None:
        self.connection.executed.append((" ".join(query.split()), values))

    def fetchone(self) -> Any:
        return self.connection.fetchone_results.pop(0)


class FakeConnection:
    def __init__(self, fetchone_results: list[Any]) -> None:
        self.fetchone_results = fetchone_results
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.commit_count = 0

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1


def test_asset_create_schema_accepts_imported_tags() -> None:
    payload = AssetCreate(
        asset_type="VID",
        original_filename="demo.mp4",
        tags=["品酒大师", "PRO"],
    )

    assert payload.tags == ["品酒大师", "PRO"]


def test_repository_create_writes_imported_tags_in_same_transaction() -> None:
    connection = FakeConnection(
        fetchone_results=[
            (1,),
            {
                "id": "asset-id",
                "asset_code": "AG-VID-20260709-000001",
                "asset_type": "VID",
                "original_filename": "demo.mp4",
                "status": "stored",
            },
        ]
    )
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    row = repository.create(
        {
            "asset_type": "VID",
            "original_filename": "demo.mp4",
            "status": "stored",
            "tags": ["品酒大师", "PRO", "品酒大师"],
        }
    )

    assert row["tags"] == ["品酒大师", "PRO"]
    assert connection.commit_count == 1
    executed_sql = "\n".join(query for query, _values in connection.executed)
    assert "INSERT INTO tags" in executed_sql
    assert "INSERT INTO asset_tags" in executed_sql
