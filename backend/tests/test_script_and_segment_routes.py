from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import scripts, video_segments
from app.main import app


class FakeScriptRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = "AG-SCRIPT-20260707-000001"
        row = {
            "id": "10000000-0000-0000-0000-000000000001",
            "script_code": code,
            "title": payload["title"],
            "product_id": payload.get("product_id"),
            "script_type": payload.get("script_type", "livestream"),
            "version": payload.get("version"),
            "description": payload.get("description"),
            "blocks": [
                {
                    "id": "11000000-0000-0000-0000-000000000001",
                    "script_id": "10000000-0000-0000-0000-000000000001",
                    **block,
                }
                for block in payload.get("blocks", [])
            ],
        }
        self.rows[code] = row
        return row

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.rows.values())[offset : offset + limit]

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.rows.get(code)


class FakeVideoSegmentRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = "AG-SEG-20260707-000001"
        row = {
            "id": "20000000-0000-0000-0000-000000000001",
            "segment_code": code,
            **payload,
            "status": payload.get("status", "created"),
        }
        self.rows[code] = row
        return row

    def list(self, live_code: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = list(self.rows.values())
        if live_code is not None:
            rows = [row for row in rows if row["live_code"] == live_code]
        return rows[offset : offset + limit]

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.rows.get(code)


@pytest.fixture
def client() -> TestClient:
    script_repo = FakeScriptRepository()
    segment_repo = FakeVideoSegmentRepository()
    app.dependency_overrides[scripts.get_script_repository] = lambda: script_repo
    app.dependency_overrides[video_segments.get_video_segment_repository] = lambda: segment_repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_and_get_script_with_blocks(client: TestClient) -> None:
    response = client.post(
        "/api/scripts",
        json={
            "title": "胶原蛋白饮直播脚本",
            "script_type": "livestream",
            "version": "v1",
            "description": "数字人直播主脚本",
            "blocks": [
                {
                    "block_type": "opening",
                    "content": "欢迎来到今天的直播间。",
                    "sort_order": 1,
                    "estimated_duration_seconds": 12.5,
                },
                {
                    "block_type": "selling_point",
                    "content": "这款胶原蛋白饮低糖便携。",
                    "sort_order": 2,
                },
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["script_code"] == "AG-SCRIPT-20260707-000001"
    assert body["title"] == "胶原蛋白饮直播脚本"
    assert body["blocks"][0]["block_type"] == "opening"

    list_response = client.get("/api/scripts")
    assert list_response.status_code == 200
    assert list_response.json()[0]["script_code"] == body["script_code"]

    get_response = client.get(f"/api/scripts/{body['script_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["blocks"][1]["content"] == "这款胶原蛋白饮低糖便携。"


def test_create_list_and_get_video_segment(client: TestClient) -> None:
    response = client.post(
        "/api/video-segments",
        json={
            "live_id": "30000000-0000-0000-0000-000000000001",
            "asset_id": "40000000-0000-0000-0000-000000000001",
            "asset_code": "AG-VID-20260707-000001",
            "live_code": "AG-LIVE-20260707-000001",
            "title": "产品卖点讲解片段",
            "start_time_seconds": 15.0,
            "end_time_seconds": 45.5,
            "transcript": "这款产品适合熬夜人群。",
            "product_id": "50000000-0000-0000-0000-000000000001",
            "digital_human_id": "60000000-0000-0000-0000-000000000001",
            "voice_profile_id": "70000000-0000-0000-0000-000000000001",
            "script_block_id": "80000000-0000-0000-0000-000000000001",
            "quality_score": 0.91,
            "reuse_score": 0.87,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["segment_code"] == "AG-SEG-20260707-000001"
    assert body["live_code"] == "AG-LIVE-20260707-000001"
    assert body["transcript"] == "这款产品适合熬夜人群。"

    list_response = client.get("/api/video-segments", params={"live_code": "AG-LIVE-20260707-000001"})
    assert list_response.status_code == 200
    assert list_response.json()[0]["segment_code"] == body["segment_code"]

    get_response = client.get(f"/api/video-segments/{body['segment_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "产品卖点讲解片段"


def test_video_segment_rejects_invalid_time_range(client: TestClient) -> None:
    response = client.post(
        "/api/video-segments",
        json={
            "live_id": "30000000-0000-0000-0000-000000000001",
            "live_code": "AG-LIVE-20260707-000001",
            "start_time_seconds": 45.5,
            "end_time_seconds": 15.0,
        },
    )

    assert response.status_code == 422
