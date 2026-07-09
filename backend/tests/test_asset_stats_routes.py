from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app


class FakeStatsRepository:
    def stats(self) -> dict[str, Any]:
        return {
            "total_assets": 131,
            "asset_file_count": 3,
            "duplicate_group_count": 7,
            "duplicate_asset_count": 18,
            "local_file_code_duplicate_groups": 0,
            "tag_count": 123,
            "tagged_asset_count": 120,
            "asset_tag_relation_count": 806,
            "by_asset_type": {"IMG": 71, "VID": 56, "AUD": 4},
            "by_maitu_category": {"product_video": 56, "digital_human_video": 29},
            "by_maitu_type": {"视频": 56, "数字分身": 29},
            "by_usage": {"视频素材": 28, "商品讲解视频": 12},
            "missing_fields": {
                "local_file_code": 0,
                "display_code": 0,
                "title": 0,
                "maitu_category": 0,
                "maitu_type": 0,
                "usage": 0,
                "subject": 0,
                "browser_use_hint": 0,
            },
        }


def test_asset_stats_route_returns_agent_quality_summary() -> None:
    app.dependency_overrides[assets.get_asset_repository] = lambda: FakeStatsRepository()
    try:
        with TestClient(app) as client:
            response = client.get("/api/assets/stats")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total_assets"] == 131
    assert body["asset_file_count"] == 3
    assert body["by_asset_type"] == {"IMG": 71, "VID": 56, "AUD": 4}
    assert body["missing_fields"]["local_file_code"] == 0
    assert body["local_file_code_duplicate_groups"] == 0
    assert body["tag_count"] == 123
    assert body["tagged_asset_count"] == 120
