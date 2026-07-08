from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import lives
from app.main import app


class FakeLiveSessionRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.assets: dict[str, list[dict[str, Any]]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = "AG-LIVE-20260707-000001"
        row = {
            "id": "90000000-0000-0000-0000-000000000001",
            "live_code": code,
            "title": payload["title"],
            "platform": payload.get("platform"),
            "streamer_name": payload.get("streamer_name"),
            "status": payload.get("status", "planned"),
            "project_id": payload.get("project_id"),
            "digital_human_id": payload.get("digital_human_id"),
            "voice_profile_id": payload.get("voice_profile_id"),
            "script_id": payload.get("script_id"),
            "description": payload.get("description"),
        }
        self.rows[code] = row
        self.assets[code] = [
            {
                "asset_code": "AG-VID-20260707-000001",
                "relation_type": "recording",
                "sort_order": 0,
                "segment_label": "完整录屏",
            }
        ]
        return row

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.rows.values())[offset : offset + limit]

    def get_by_code(self, live_code: str) -> dict[str, Any] | None:
        return self.rows.get(live_code)

    def list_assets(self, live_code: str) -> list[dict[str, Any]]:
        return self.assets.get(live_code, [])


@pytest.fixture
def client() -> TestClient:
    repository = FakeLiveSessionRepository()
    app.dependency_overrides[lives.get_live_session_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_list_and_get_live_session(client: TestClient) -> None:
    response = client.post(
        "/api/lives",
        json={
            "title": "7月胶原蛋白数字人直播",
            "platform": "douyin",
            "streamer_name": "数字人小雅",
            "digital_human_id": "60000000-0000-0000-0000-000000000001",
            "voice_profile_id": "70000000-0000-0000-0000-000000000001",
            "script_id": "10000000-0000-0000-0000-000000000001",
            "description": "首场数字人直播测试",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["live_code"] == "AG-LIVE-20260707-000001"
    assert body["title"] == "7月胶原蛋白数字人直播"
    assert body["digital_human_id"] == "60000000-0000-0000-0000-000000000001"
    assert body["voice_profile_id"] == "70000000-0000-0000-0000-000000000001"
    assert body["script_id"] == "10000000-0000-0000-0000-000000000001"

    list_response = client.get("/api/lives")
    assert list_response.status_code == 200
    assert list_response.json()[0]["live_code"] == body["live_code"]

    get_response = client.get(f"/api/lives/{body['live_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["platform"] == "douyin"


def test_live_assets_endpoint_preserves_index_shape(client: TestClient) -> None:
    create_response = client.post("/api/lives", json={"title": "7月胶原蛋白数字人直播"})
    live_code = create_response.json()["live_code"]

    response = client.get(f"/api/lives/{live_code}/assets")

    assert response.status_code == 200
    body = response.json()
    assert body["live_code"] == live_code
    assert body["assets"][0]["asset_code"] == "AG-VID-20260707-000001"
    assert body["assets"][0]["relation_type"] == "recording"


def test_get_missing_live_session_returns_404(client: TestClient) -> None:
    response = client.get("/api/lives/AG-LIVE-20260707-999999")

    assert response.status_code == 404
