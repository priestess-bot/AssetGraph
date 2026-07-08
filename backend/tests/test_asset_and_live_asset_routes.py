from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets, lives
from app.main import app


class FakeAssetRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = f"AG-{payload['asset_type']}-20260707-{len(self.rows) + 1:06d}"
        row = {
            "id": "40000000-0000-0000-0000-000000000001",
            "asset_code": code,
            "asset_type": payload["asset_type"],
            "title": payload.get("title"),
            "original_filename": payload["original_filename"],
            "file_ext": payload.get("file_ext"),
            "mime_type": payload.get("mime_type"),
            "file_size": payload.get("file_size"),
            "checksum_sha256": payload.get("checksum_sha256"),
            "status": payload.get("status", "created"),
            "project_id": payload.get("project_id"),
            "description": payload.get("description"),
            "source_type": payload.get("source_type"),
            "maitu_category": payload.get("maitu_category"),
            "maitu_project_code": payload.get("maitu_project_code"),
            "maitu_scene_name": payload.get("maitu_scene_name"),
            "maitu_scene_index": payload.get("maitu_scene_index"),
            "maitu_layer_name": payload.get("maitu_layer_name"),
            "maitu_layer_index": payload.get("maitu_layer_index"),
            "maitu_slot_name": payload.get("maitu_slot_name"),
            "maitu_slot_code": payload.get("maitu_slot_code"),
            "layer_left": payload.get("layer_left"),
            "layer_top": payload.get("layer_top"),
            "layer_width": payload.get("layer_width"),
            "layer_height": payload.get("layer_height"),
            "layer_z_index": payload.get("layer_z_index"),
            "replacement_policy": payload.get("replacement_policy", "keep_layout"),
        }
        self.rows[code] = row
        return row

    def get_by_code(self, asset_code: str) -> dict[str, Any] | None:
        return self.rows.get(asset_code)

    def list(
        self,
        *,
        asset_type: str | None = None,
        maitu_category: str | None = None,
        maitu_project_code: str | None = None,
        maitu_scene_name: str | None = None,
        maitu_slot_name: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.rows.values())
        if asset_type is not None:
            rows = [row for row in rows if row["asset_type"] == asset_type]
        if maitu_category is not None:
            rows = [row for row in rows if row.get("maitu_category") == maitu_category]
        if maitu_project_code is not None:
            rows = [row for row in rows if row.get("maitu_project_code") == maitu_project_code]
        if maitu_scene_name is not None:
            rows = [row for row in rows if row.get("maitu_scene_name") == maitu_scene_name]
        if maitu_slot_name is not None:
            rows = [row for row in rows if row.get("maitu_slot_name") == maitu_slot_name]
        if q:
            rows = [
                row
                for row in rows
                if q in row["asset_code"]
                or q in (row.get("title") or "")
                or q in row["original_filename"]
                or q in (row.get("description") or "")
            ]
        return rows[offset : offset + limit]


class FakeLiveSessionRepository:
    def __init__(self) -> None:
        self.live = {
            "id": "90000000-0000-0000-0000-000000000001",
            "live_code": "AG-LIVE-20260707-000001",
            "title": "7月胶原蛋白数字人直播",
            "platform": "douyin",
            "streamer_name": "数字人小雅",
            "status": "planned",
            "project_id": None,
            "digital_human_id": None,
            "voice_profile_id": None,
            "script_id": None,
            "description": None,
        }
        self.links: dict[str, list[dict[str, Any]]] = {self.live["live_code"]: []}

    def get_by_code(self, live_code: str) -> dict[str, Any] | None:
        if live_code == self.live["live_code"]:
            return self.live
        return None

    def link_asset(self, live_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if live_code != self.live["live_code"]:
            return None
        row = {
            "asset_code": payload["asset_code"],
            "relation_type": payload["relation_type"],
            "sort_order": payload.get("sort_order", 0),
            "segment_label": payload.get("segment_label"),
            "start_time_seconds": payload.get("start_time_seconds"),
            "end_time_seconds": payload.get("end_time_seconds"),
            "maitu_scene_name": payload.get("maitu_scene_name"),
            "maitu_layer_name": payload.get("maitu_layer_name"),
            "maitu_slot_name": payload.get("maitu_slot_name"),
            "replacement_policy": payload.get("replacement_policy"),
        }
        self.links[live_code].append(row)
        return row

    def list_assets(self, live_code: str) -> list[dict[str, Any]]:
        return self.links.get(live_code, [])


@pytest.fixture
def client() -> TestClient:
    asset_repo = FakeAssetRepository()
    live_repo = FakeLiveSessionRepository()
    app.dependency_overrides[assets.get_asset_repository] = lambda: asset_repo
    app.dependency_overrides[lives.get_live_session_repository] = lambda: live_repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_and_get_asset(client: TestClient) -> None:
    response = client.post(
        "/api/assets",
        json={
            "asset_type": "VID",
            "title": "完整直播录屏",
            "original_filename": "live-full.mp4",
            "file_ext": ".mp4",
            "mime_type": "video/mp4",
            "file_size": 123456789,
            "checksum_sha256": "a" * 64,
            "description": "数字人直播完整录屏",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_code"] == "AG-VID-20260707-000001"
    assert body["asset_type"] == "VID"
    assert body["status"] == "created"

    get_response = client.get(f"/api/assets/{body['asset_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["original_filename"] == "live-full.mp4"


def test_create_maitu_asset_metadata_and_filter_for_agent_lookup(client: TestClient) -> None:
    response = client.post(
        "/api/assets",
        json={
            "asset_type": "IMG",
            "title": "胶原蛋白商品主图-白底款",
            "original_filename": "collagen-main.png",
            "file_ext": ".png",
            "mime_type": "image/png",
            "source_type": "maitu_material",
            "maitu_category": "product_image",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "maitu_scene_name": "京东空白直播间",
            "maitu_scene_index": 0,
            "maitu_layer_name": "layer_8",
            "maitu_layer_index": 8,
            "maitu_slot_name": "商品主图",
            "maitu_slot_code": "MT-SLOT-20260707-000001",
            "layer_left": 840,
            "layer_top": 180,
            "layer_width": 460,
            "layer_height": 460,
            "layer_z_index": 8,
            "replacement_policy": "keep_layout",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_code"] == "AG-IMG-20260707-000001"
    assert body["maitu_category"] == "product_image"
    assert body["maitu_slot_name"] == "商品主图"
    assert body["replacement_policy"] == "keep_layout"

    list_response = client.get(
        "/api/assets",
        params={
            "asset_type": "IMG",
            "maitu_category": "product_image",
            "maitu_scene_name": "京东空白直播间",
            "maitu_slot_name": "商品主图",
            "q": "胶原蛋白",
        },
    )

    assert list_response.status_code == 200
    results = list_response.json()
    assert results[0]["asset_code"] == body["asset_code"]
    assert results[0]["layer_width"] == 460


def test_link_asset_to_live_and_list_assets(client: TestClient) -> None:
    asset_response = client.post(
        "/api/assets",
        json={"asset_type": "VID", "original_filename": "live-full.mp4"},
    )
    asset_code = asset_response.json()["asset_code"]

    link_response = client.post(
        "/api/lives/AG-LIVE-20260707-000001/assets",
        json={
            "asset_code": asset_code,
            "relation_type": "recording",
            "sort_order": 0,
            "segment_label": "完整录屏",
            "start_time_seconds": 0,
            "end_time_seconds": 3600,
        },
    )

    assert link_response.status_code == 201
    link_body = link_response.json()
    assert link_body["asset_code"] == asset_code
    assert link_body["relation_type"] == "recording"

    list_response = client.get("/api/lives/AG-LIVE-20260707-000001/assets")
    assert list_response.status_code == 200
    assert list_response.json()["assets"][0]["asset_code"] == asset_code


def test_link_maitu_asset_to_live_preserves_replacement_context(client: TestClient) -> None:
    asset_response = client.post(
        "/api/assets",
        json={
            "asset_type": "IMG",
            "original_filename": "collagen-main.png",
            "maitu_category": "product_image",
            "maitu_scene_name": "京东空白直播间",
            "maitu_layer_name": "layer_8",
            "maitu_slot_name": "商品主图",
        },
    )
    asset_code = asset_response.json()["asset_code"]

    link_response = client.post(
        "/api/lives/AG-LIVE-20260707-000001/assets",
        json={
            "asset_code": asset_code,
            "relation_type": "product_image",
            "segment_label": "商品主图",
            "maitu_scene_name": "京东空白直播间",
            "maitu_layer_name": "layer_8",
            "maitu_slot_name": "商品主图",
            "replacement_policy": "keep_layout",
        },
    )

    assert link_response.status_code == 201
    assert link_response.json()["maitu_layer_name"] == "layer_8"
    assert link_response.json()["replacement_policy"] == "keep_layout"

    list_response = client.get("/api/lives/AG-LIVE-20260707-000001/assets")
    assert list_response.status_code == 200
    live_asset = list_response.json()["assets"][0]
    assert live_asset["maitu_scene_name"] == "京东空白直播间"
    assert live_asset["maitu_slot_name"] == "商品主图"


def test_link_asset_to_missing_live_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/lives/AG-LIVE-20260707-999999/assets",
        json={"asset_code": "AG-VID-20260707-000001", "relation_type": "recording"},
    )

    assert response.status_code == 404
