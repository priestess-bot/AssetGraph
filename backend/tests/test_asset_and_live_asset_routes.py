from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets, lives
from app.main import app
from app.repositories.assets import AssetBindingLeaseConflictError
from app.services.maitu_authority import MaituAuthorityError


READBACK_NONCE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def material_binding(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        field: binding.get(field)
        for field in (
            "maitu_material_id",
            "source_material_type",
            "source_material_url",
            "source_cover_url",
            "speaker_id",
            "digital_human_image_id",
        )
    }


class FakeMaituAuthorityVerifier:
    def attest_binding(self, asset_code: str, binding: dict[str, Any]) -> dict[str, Any]:
        del asset_code
        if binding.get("source_material_url") == "https://cdn.example/tampered.png":
            raise MaituAuthorityError("material binding URL differs from backend Maitu inventory readback")
        return {
            **binding,
            "inventory_snapshot_sha256": "a" * 64,
            "readback_nonce": READBACK_NONCE,
            "readback_attestation": "b" * 64,
        }


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
            "display_code": payload.get("display_code"),
            "local_file_code": payload.get("local_file_code"),
            "entity_code": payload.get("entity_code"),
            "source_system": payload.get("source_system"),
            "source_type": payload.get("source_type"),
            "maitu_category": payload.get("maitu_category"),
            "maitu_type": payload.get("maitu_type"),
            "maitu_subtype": payload.get("maitu_subtype"),
            "usage": payload.get("usage"),
            "subject": payload.get("subject"),
            "file_role": payload.get("file_role"),
            "browser_use_hint": payload.get("browser_use_hint"),
            "local_relative_path": payload.get("local_relative_path"),
            "duplicate_group": payload.get("duplicate_group"),
            "duplicate_rank": payload.get("duplicate_rank"),
            "duplicate_count": payload.get("duplicate_count"),
            "duplicate_primary_local_file_code": payload.get("duplicate_primary_local_file_code"),
            "duplicate_primary_asset_code": payload.get("duplicate_primary_asset_code"),
            "maitu_project_code": payload.get("maitu_project_code"),
            "maitu_material_id": payload.get("maitu_material_id"),
            "source_material_type": payload.get("source_material_type"),
            "source_material_url": payload.get("source_material_url"),
            "source_cover_url": payload.get("source_cover_url"),
            "speaker_id": payload.get("speaker_id"),
            "digital_human_image_id": payload.get("digital_human_image_id"),
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

    def update_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.rows.get(asset_code)
        if row is None:
            return None
        row.update(payload)
        return row

    def list(
        self,
        *,
        asset_type: str | None = None,
        maitu_category: str | None = None,
        local_file_code: str | None = None,
        entity_code: str | None = None,
        maitu_type: str | None = None,
        usage: str | None = None,
        subject: str | None = None,
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
        if local_file_code is not None:
            rows = [row for row in rows if row.get("local_file_code") == local_file_code]
        if entity_code is not None:
            rows = [row for row in rows if row.get("entity_code") == entity_code]
        if maitu_type is not None:
            rows = [row for row in rows if row.get("maitu_type") == maitu_type]
        if usage is not None:
            rows = [row for row in rows if row.get("usage") == usage]
        if subject is not None:
            rows = [row for row in rows if subject in (row.get("subject") or "")]
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
                or q in (row.get("display_code") or "")
                or q in (row.get("local_file_code") or "")
                or q in (row.get("entity_code") or "")
                or q in (row.get("title") or "")
                or q in row["original_filename"]
                or q in (row.get("description") or "")
                or q in (row.get("usage") or "")
                or q in (row.get("subject") or "")
                or q in (row.get("file_role") or "")
                or q in (row.get("browser_use_hint") or "")
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
    app.dependency_overrides[assets.require_maitu_script_layout_worker] = lambda: "asset-binding-test-worker"
    app.dependency_overrides[assets.get_maitu_authority_verifier] = FakeMaituAuthorityVerifier
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


def test_create_asset_preserves_local_material_code_mapping(client: TestClient) -> None:
    response = client.post(
        "/api/assets",
        json={
            "asset_type": "VID",
            "title": "品酒大师 PRO 商品讲解视频",
            "original_filename": "MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
            "file_ext": ".mp4",
            "mime_type": "video/mp4",
            "checksum_sha256": "b" * 64,
            "display_code": "MT-VID-0024",
            "local_file_code": "MT-VID-0024",
            "entity_code": None,
            "source_system": "maitu",
            "source_type": "maitu_local_material",
            "maitu_category": "product_video",
            "maitu_type": "视频",
            "usage": "商品讲解视频",
            "subject": "品酒大师PRO",
            "file_role": "商品讲解视频",
            "browser_use_hint": "用于麦兔视频素材选择：品酒大师PRO，用途：商品讲解视频",
            "local_relative_path": "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
            "duplicate_group": "DUP-008",
            "duplicate_rank": 1,
            "duplicate_count": 2,
            "duplicate_primary_local_file_code": "MT-VID-0024",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_code"] == "AG-VID-20260707-000001"
    assert body["display_code"] == "MT-VID-0024"
    assert body["local_file_code"] == "MT-VID-0024"
    assert body["source_system"] == "maitu"
    assert body["maitu_type"] == "视频"
    assert body["usage"] == "商品讲解视频"
    assert body["subject"] == "品酒大师PRO"
    assert body["duplicate_group"] == "DUP-008"

    by_local_code = client.get("/api/assets", params={"local_file_code": "MT-VID-0024"})
    assert by_local_code.status_code == 200
    assert by_local_code.json()[0]["asset_code"] == body["asset_code"]

    by_subject = client.get("/api/assets", params={"maitu_type": "视频", "subject": "品酒大师"})
    assert by_subject.status_code == 200
    assert by_subject.json()[0]["local_file_code"] == "MT-VID-0024"

    by_q = client.get("/api/assets", params={"q": "MT-VID-0024"})
    assert by_q.status_code == 200
    assert by_q.json()[0]["subject"] == "品酒大师PRO"


def test_create_digital_human_file_preserves_entity_code_mapping(client: TestClient) -> None:
    response = client.post(
        "/api/assets",
        json={
            "asset_type": "VID",
            "title": "模特 7717 品酒大师 PRO 训练素材",
            "original_filename": "DH-MDL-0001-F022_模特_7717_Y26定制_品酒大师PRO_训练素材.mov",
            "local_file_code": "DH-MDL-0001-F022",
            "entity_code": "DH-MDL-0001",
            "source_system": "maitu",
            "source_type": "maitu_local_material",
            "maitu_category": "digital_human_video",
            "maitu_type": "数字分身",
            "maitu_subtype": "模特",
            "usage": "视频",
            "subject": "7717_Y26定制_品酒大师PRO",
            "file_role": "训练素材",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_code"] == "AG-VID-20260707-000001"
    assert body["local_file_code"] == "DH-MDL-0001-F022"
    assert body["entity_code"] == "DH-MDL-0001"
    assert body["maitu_subtype"] == "模特"

    by_entity = client.get("/api/assets", params={"entity_code": "DH-MDL-0001"})
    assert by_entity.status_code == 200
    assert by_entity.json()[0]["file_role"] == "训练素材"


def test_patch_asset_maitu_material_binding_for_real_insert(client: TestClient) -> None:
    create_response = client.post(
        "/api/assets",
        json={
            "asset_type": "IMG",
            "title": "龙谕龙8商品主图",
            "original_filename": "longyu-long8.png",
            "maitu_category": "product_image",
            "local_relative_path": "图片/longyu-long8.png",
        },
    )
    asset_code = create_response.json()["asset_code"]

    response = client.patch(
        f"/api/assets/{asset_code}/maitu-material-binding",
        json=material_binding(
            {
                "maitu_material_id": 881001,
                "source_material_type": "image",
                "source_material_url": "https://static.maituai.example/materials/longyu-long8.png",
                "source_cover_url": "https://static.maituai.example/materials/longyu-long8-cover.png",
                "speaker_id": None,
                "digital_human_image_id": None,
            },
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["maitu_material_id"] == 881001
    assert body["source_material_type"] == "image"
    assert body["source_material_url"].endswith("longyu-long8.png")
    assert body["source_cover_url"].endswith("longyu-long8-cover.png")
    assert body["maitu_binding_verification_source"] == "backend_maitu_inventory_readback"
    assert body["maitu_binding_verified_at"] is not None
    assert body["maitu_binding_scope"] == "assetgraph_script_layout_material_binding_v2"
    assert "maitu_binding_readback_nonce" not in body
    assert "maitu_binding_attestation" not in body
    assert "maitu_binding_inventory_fingerprint" not in body
    get_response = client.get(f"/api/assets/{asset_code}")
    assert get_response.status_code == 200
    assert get_response.json()["maitu_material_id"] == 881001


def test_patch_asset_binding_rejects_empty_partial_or_authority_mismatched_replacement(client: TestClient) -> None:
    asset_code = client.post(
        "/api/assets",
        json={"asset_type": "IMG", "original_filename": "receipt.png"},
    ).json()["asset_code"]
    endpoint = f"/api/assets/{asset_code}/maitu-material-binding"
    assert client.patch(endpoint, json={}).status_code == 422
    assert client.patch(endpoint, json={"maitu_material_id": 901}).status_code == 422
    payload = material_binding(
        {
            "maitu_material_id": 901,
            "source_material_type": "image",
            "source_material_url": "https://cdn.example/receipt.png",
            "source_cover_url": None,
            "speaker_id": None,
            "digital_human_image_id": None,
        },
    )
    payload["source_material_url"] = "https://cdn.example/tampered.png"
    response = client.patch(endpoint, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "Backend Maitu inventory verification failed"


def test_patch_asset_material_binding_returns_409_during_active_retry_lease(
) -> None:
    class ConflictAssetRepository(FakeAssetRepository):
        def update_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
            raise AssetBindingLeaseConflictError(
                "asset Maitu material binding cannot change during an active retry worker lease"
            )

    repository = ConflictAssetRepository()
    asset = repository.create({"asset_type": "IMG", "original_filename": "product.png"})
    app.dependency_overrides[assets.get_asset_repository] = lambda: repository
    app.dependency_overrides[assets.require_maitu_script_layout_worker] = lambda: "asset-binding-test-worker"
    app.dependency_overrides[assets.get_maitu_authority_verifier] = FakeMaituAuthorityVerifier
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.patch(
                f"/api/assets/{asset['asset_code']}/maitu-material-binding",
                json=material_binding(
                    {
                        "maitu_material_id": 901,
                        "source_material_type": "image",
                        "source_material_url": "https://cdn.example/bg.png",
                        "source_cover_url": None,
                        "speaker_id": None,
                        "digital_human_image_id": None,
                    },
                ),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Asset Maitu material binding cannot change during an active retry worker lease"
    }


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
