from __future__ import annotations

from typing import Any

from app.repositories.assets import AssetRepository


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, values: tuple[Any, ...] = ()) -> None:
        self.connection.executed.append((" ".join(query.split()), values))

    def fetchone(self) -> dict[str, Any]:
        return self.connection.fetchone_results.pop(0)

    def fetchall(self) -> list[dict[str, Any]]:
        return self.connection.fetchall_results.pop(0)


class FakeConnection:
    def __init__(self, *, fetchone_results: list[dict[str, Any]], fetchall_results: list[list[dict[str, Any]]]) -> None:
        self.fetchone_results = fetchone_results
        self.fetchall_results = fetchall_results
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return FakeCursor(self)


def test_stats_returns_agent_quality_summary_from_aggregate_queries() -> None:
    connection = FakeConnection(
        fetchone_results=[
            {
                "total_assets": 131,
                "asset_file_count": 3,
                "duplicate_group_count": 7,
                "duplicate_asset_count": 18,
                "local_file_code_duplicate_groups": 0,
                "tag_count": 123,
                "tagged_asset_count": 120,
                "asset_tag_relation_count": 806,
                "missing_local_file_code": 0,
                "missing_display_code": 0,
                "missing_title": 0,
                "missing_maitu_category": 0,
                "missing_maitu_type": 0,
                "missing_usage": 0,
                "missing_subject": 0,
                "missing_browser_use_hint": 0,
            }
        ],
        fetchall_results=[
            [{"key": "IMG", "count": 71}, {"key": "VID", "count": 56}, {"key": "AUD", "count": 4}],
            [{"key": "product_video", "count": 56}, {"key": "digital_human_video", "count": 29}],
            [{"key": "视频", "count": 56}, {"key": "数字分身", "count": 29}],
            [{"key": "视频素材", "count": 28}, {"key": "商品讲解视频", "count": 12}],
        ],
    )
    repository = AssetRepository(connection)  # type: ignore[arg-type]

    stats = repository.stats()

    assert stats["total_assets"] == 131
    assert stats["asset_file_count"] == 3
    assert stats["duplicate_group_count"] == 7
    assert stats["tag_count"] == 123
    assert stats["tagged_asset_count"] == 120
    assert stats["asset_tag_relation_count"] == 806
    assert stats["by_asset_type"] == {"IMG": 71, "VID": 56, "AUD": 4}
    assert stats["by_maitu_category"]["product_video"] == 56
    assert stats["missing_fields"] == {
        "local_file_code": 0,
        "display_code": 0,
        "title": 0,
        "maitu_category": 0,
        "maitu_type": 0,
        "usage": 0,
        "subject": 0,
        "browser_use_hint": 0,
    }
    assert any("COUNT(*) FILTER" in query for query, _values in connection.executed)
