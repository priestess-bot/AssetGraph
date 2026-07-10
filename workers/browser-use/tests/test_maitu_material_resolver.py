from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from browser_use_worker.maitu_material_resolver import MaituMaterialResolver


class FakeAssetGraphClient:
    def __init__(self, assets: dict[str, dict[str, Any]]) -> None:
        self.assets = assets
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        asset = self.assets.get(asset_code)
        return dict(asset) if asset is not None else None

    def update_asset_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.updates.append((asset_code, dict(payload)))
        self.assets[asset_code] = {**self.assets[asset_code], **payload}
        return dict(self.assets[asset_code])


class FakeMaituMaterialSession:
    def __init__(self, materials: list[dict[str, Any]], uploaded: dict[str, dict[str, Any]] | None = None) -> None:
        self.materials = materials
        self.uploaded = uploaded or {}
        self.upload_calls: list[dict[str, Any]] = []
        self.list_calls = 0

    def list_maitu_materials(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [dict(item) for item in self.materials]

    def upload_maitu_material(self, *, asset: dict[str, Any], local_path: Path, layer_type: str | None) -> dict[str, Any]:
        self.upload_calls.append({"asset_code": asset["asset_code"], "local_path": local_path, "layer_type": layer_type})
        return dict(self.uploaded[asset["asset_code"]])


def plan_for(asset_code: str, *, layer_type: str = "product_image") -> dict[str, Any]:
    return {
        "build_plan_code": "MT-LAYOUT-BUILD-20260710-000001",
        "operations": [
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "scene-00-product_image",
                "layer_type": layer_type,
                "asset_code": asset_code,
            },
            {
                "operation_type": "position_asset_layer",
                "scene_index": 0,
                "layer_id": "scene-00-product_image",
                "layer_type": layer_type,
                "asset_code": asset_code,
            },
        ],
    }


def test_resolver_reuses_existing_assetgraph_binding_after_inventory_verification(tmp_path: Path) -> None:
    asset_code = "AG-IMG-20260709-000001"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "maitu_material_id": 41000,
                "source_material_type": "image",
                "source_material_url": "https://static.example/longyu.png",
                "source_cover_url": "https://static.example/longyu-cover.png",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 41000,
                "name": "龙谕",
                "type": "image",
                "url": "https://static.example/longyu.png",
                "cover_url": "https://static.example/longyu-cover.png",
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "resolved"
    assert result.reused_binding_count == 1
    assert result.remote_match_count == 0
    assert result.uploaded_count == 0
    assert result.manual_required_count == 0
    assert session.list_calls == 1
    assert session.upload_calls == []
    assert client.updates == []
    for operation in result.operation_plan["operations"]:
        assert operation["maitu_material_id"] == 41000
        assert operation["material_id"] == 41000
        assert operation["source_material_url"].endswith("longyu.png")


def test_resolver_rejects_type_incompatible_stored_binding_and_repairs_it_from_inventory(tmp_path: Path) -> None:
    asset_code = "AG-VID-20260709-000052"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "品酒大师PRO",
                "original_filename": "品酒大师PRO.mp4",
                "local_relative_path": "视频/品酒大师PRO.mp4",
                "maitu_material_id": 40999,
                "source_material_type": "image",
                "source_material_url": "https://static.example/product-pro.png",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 42601,
                "name": "品酒大师PRO.mp4",
                "type": "decorative_video",
                "url": "https://static.example/product-pro.mp4",
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="product_video")
    )

    assert result.status == "resolved"
    assert result.reused_binding_count == 0
    assert result.remote_match_count == 1
    assert client.updates[0][1] == {
        "maitu_material_id": 42601,
        "source_material_type": "decorative_video",
        "source_material_url": "https://static.example/product-pro.mp4",
    }
    assert result.operation_plan["operations"][0]["material_id"] == 42601


def test_resolver_refreshes_stale_stored_binding_from_authoritative_inventory(tmp_path: Path) -> None:
    asset_code = "AG-IMG-STALE"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "礼盒",
                "maitu_material_id": 77,
                "source_material_type": "image",
                "source_material_url": "https://static.example/stale.png",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [{"id": 77, "name": "礼盒", "type": "image", "url": "https://static.example/current.png"}]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "resolved"
    assert result.reused_binding_count == 0
    assert result.remote_match_count == 1
    assert client.updates[0][1]["source_material_url"] == "https://static.example/current.png"
    assert result.operation_plan["operations"][0]["source_material_url"].endswith("current.png")


def test_resolver_matches_existing_maitu_material_and_writes_binding_back(tmp_path: Path) -> None:
    asset_code = "AG-VID-20260709-000056"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "source_system": "maitu",
                "subject": "6月29日(2)-9051",
                "original_filename": "MT-VID-0028_视频_视频素材_6月29日(2)-9051.mp4",
                "local_relative_path": "视频/MT-VID-0028_视频_视频素材_6月29日(2)-9051.mp4",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 41043,
                "name": "6月29日 (2)-9051.mp4",
                "type": "decorative_video",
                "url": "https://static.example/uploads/6month29-9051.mp4",
                "cover_url": "https://static.example/covers/6month29-9051.png",
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="product_video")
    )

    assert result.status == "resolved"
    assert result.remote_match_count == 1
    assert result.uploaded_count == 0
    assert result.manual_required_count == 0
    assert client.updates == [
        (
            asset_code,
            {
                "maitu_material_id": 41043,
                "source_material_type": "decorative_video",
                "source_material_url": "https://static.example/uploads/6month29-9051.mp4",
                "source_cover_url": "https://static.example/covers/6month29-9051.png",
            },
        )
    ]
    assert result.operation_plan["operations"][0]["material_id"] == 41043


def test_resolver_uploads_missing_local_material_then_writes_binding(tmp_path: Path) -> None:
    asset_code = "AG-IMG-20260710-000099"
    local_relative_path = "商品图/新品主图.png"
    local_path = tmp_path / local_relative_path
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"real-image-bytes")
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "新品主图",
                "original_filename": "新品主图.png",
                "local_relative_path": local_relative_path,
            }
        }
    )
    session = FakeMaituMaterialSession(
        [],
        uploaded={
            asset_code: {
                "id": 50001,
                "name": "新品主图.png",
                "type": "image",
                "url": "https://static.example/images/new-product.png",
                "cover_url": None,
            }
        },
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "resolved"
    assert result.remote_match_count == 0
    assert result.uploaded_count == 1
    assert result.manual_required_count == 0
    assert session.upload_calls == [{"asset_code": asset_code, "local_path": local_path, "layer_type": "product_image"}]
    assert client.updates[0][1]["maitu_material_id"] == 50001
    assert result.operation_plan["operations"][1]["source_material_url"].endswith("new-product.png")


def test_resolver_fails_closed_when_asset_has_no_existing_material_or_local_file(tmp_path: Path) -> None:
    asset_code = "AG-IMG-20260710-000100"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "缺失商品图",
                "original_filename": "missing.png",
                "local_relative_path": "商品图/missing.png",
            }
        }
    )
    session = FakeMaituMaterialSession([])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.manual_required_count == 1
    assert result.issues[0].asset_code == asset_code
    assert result.issues[0].reason == "local_asset_file_not_found"
    assert session.upload_calls == []
    assert client.updates == []
    assert "material_id" not in result.operation_plan["operations"][0]
    assert result.operation_plan["operations"][0]["material_resolution_status"] == "manual_required"


def test_resolver_fails_closed_on_ambiguous_remote_name_match(tmp_path: Path) -> None:
    asset_code = "AG-IMG-20260710-000101"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "礼盒",
                "original_filename": "礼盒.png",
                "local_relative_path": "商品图/礼盒.png",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {"id": 41000, "name": "礼盒", "type": "image", "url": "https://static.example/a.png"},
            {"id": 42000, "name": "礼盒", "type": "image", "url": "https://static.example/b.png"},
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.manual_required_count == 1
    assert result.issues[0].reason == "ambiguous_maitu_material_match"
    assert result.issues[0].candidate_material_ids == [41000, 42000]
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_fails_closed_instead_of_uploading_digital_human_training_video(tmp_path: Path) -> None:
    asset_code = "AG-VID-20260710-000200"
    local_relative_path = "数字分身/未建模角色_训练素材.mp4"
    local_path = tmp_path / local_relative_path
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"training-video")
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "未建模角色",
                "maitu_category": "digital_human_video",
                "original_filename": "未建模角色_训练素材.mp4",
                "local_relative_path": local_relative_path,
            }
        }
    )
    session = FakeMaituMaterialSession([])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="digital_human")
    )

    assert result.status == "completed_with_manual_review"
    assert result.manual_required_count == 1
    assert result.uploaded_count == 0
    assert result.issues[0].reason == "digital_human_material_not_found"
    assert session.upload_calls == []
    assert client.updates == []


@pytest.mark.parametrize("layer_type", ["product_image", "product_video"])
def test_resolver_rejects_digital_human_training_asset_in_strict_regular_layer(tmp_path: Path, layer_type: str) -> None:
    asset_code = "AG-DH-WRONG-STRICT-LAYER"
    relative = "数字分身/训练素材.mp4"
    local_path = tmp_path / relative
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"training-video")
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "明月",
                "maitu_category": "digital_human_video",
                "local_relative_path": relative,
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 40222,
                "name": "明月",
                "type": "digital_human",
                "url": "https://static.example/dh.png",
                "speaker_id": 4224,
                "digital_human_image_id": 8856,
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type=layer_type)
    )

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "digital_human_asset_layer_mismatch"
    assert session.list_calls == 0
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_maps_digital_human_by_image_id_when_name_is_short(tmp_path: Path) -> None:
    asset_code = "AG-VID-20260709-000028"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "8856_明月_正坐A",
                "maitu_category": "digital_human_video",
                "original_filename": "DH-MDL-0002-F015_模特_8856_明月_正坐A_训练素材.mp4",
                "local_relative_path": "数字分身/明月正坐A.mp4",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 40222,
                "name": "明月",
                "type": "digital_human",
                "url": "https://static.example/digital-human/cover.png",
                "speaker_id": 4224,
                "digital_human_image_id": 8856,
                "digital_human_image": {"name": "明月", "id": 8856},
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="digital_human")
    )

    assert result.status == "resolved"
    assert result.remote_match_count == 1
    assert result.uploaded_count == 0
    assert session.upload_calls == []
    assert result.operation_plan["operations"][0]["maitu_material_id"] == 40222
    assert result.operation_plan["operations"][0]["digital_human_image_id"] == 8856


def test_resolver_maps_digital_human_material_ids_from_nested_image_name(tmp_path: Path) -> None:
    asset_code = "AG-VID-20260709-000019"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "7717_Y26定制_龙谕龙8",
                "entity_code": "DH-MDL-0001",
                "maitu_category": "digital_human_video",
                "original_filename": "DH-MDL-0001-F027_模特_7717_Y26定制_龙谕龙8_训练素材.mov",
                "local_relative_path": "数字分身/训练素材.mov",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 37200,
                "name": "张裕定制形象260519",
                "type": "digital_human",
                "url": "https://static.example/digital-human/7717.png",
                "speaker_id": 3760,
                "digital_human_image_id": 7717,
                "digital_human_image": {"name": "Y26定制", "id": 7717},
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="digital_human")
    )

    assert result.status == "resolved"
    assert result.remote_match_count == 1
    assert client.updates[0][1] == {
        "maitu_material_id": 37200,
        "source_material_type": "digital_human",
        "source_material_url": "https://static.example/digital-human/7717.png",
        "speaker_id": 3760,
        "digital_human_image_id": 7717,
    }
    assert result.operation_plan["operations"][0]["digital_human_image_id"] == 7717
    assert result.operation_plan["operations"][0]["speaker_id"] == 3760


def test_resolver_allows_video_for_polymorphic_supporting_visual(tmp_path: Path) -> None:
    asset_code = "AG-VID-SUPPORT"
    client = FakeAssetGraphClient(
        {asset_code: {"asset_code": asset_code, "subject": "工艺视频", "original_filename": "工艺视频.mp4"}}
    )
    session = FakeMaituMaterialSession(
        [{"id": 88, "name": "工艺视频.mp4", "type": "decorative_video", "url": "https://static.example/craft.mp4"}]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="supporting_visual")
    )

    assert result.status == "resolved"
    assert result.remote_match_count == 1
    assert result.operation_plan["operations"][0]["source_material_type"] == "decorative_video"


def test_resolver_matches_existing_maitu_material_with_three_digit_upload_suffix(tmp_path: Path) -> None:
    asset_code = "AG-VID-THREE-DIGIT"
    client = FakeAssetGraphClient(
        {asset_code: {"asset_code": asset_code, "subject": "品酒大师PRO", "original_filename": "品酒大师PRO.mp4"}}
    )
    session = FakeMaituMaterialSession(
        [
            {
                "id": 42601,
                "name": "品酒大师PRO-836.mp4",
                "type": "decorative_video",
                "url": "https://static.example/product-pro-836.mp4",
            }
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="product_video")
    )

    assert result.status == "resolved"
    assert result.remote_match_count == 1
    assert result.operation_plan["operations"][0]["maitu_material_id"] == 42601


def test_resolver_uses_strict_kind_when_visual_and_image_share_asset(tmp_path: Path) -> None:
    asset_code = "AG-SHARED-VISUAL"
    client = FakeAssetGraphClient({asset_code: {"asset_code": asset_code, "subject": "共享素材"}})
    session = FakeMaituMaterialSession(
        [
            {"id": 90, "name": "共享素材", "type": "decorative_video", "url": "https://static.example/shared.mp4"},
            {"id": 91, "name": "共享素材", "type": "image", "url": "https://static.example/shared.png"},
        ]
    )
    plan = {
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": asset_code, "layer_type": "supporting_visual"},
            {"operation_type": "insert_asset_layer", "asset_code": asset_code, "layer_type": "product_image"},
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "resolved"
    assert result.operation_plan["operations"][0]["source_material_type"] == "image"
    assert result.operation_plan["operations"][1]["source_material_type"] == "image"


def test_resolver_rejects_incomplete_digital_human_binding(tmp_path: Path) -> None:
    asset_code = "AG-DH-INCOMPLETE"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "subject": "未完整数字人",
                "maitu_category": "digital_human_video",
                "speaker_id": 123,
                "source_material_type": "digital_human",
            }
        }
    )
    session = FakeMaituMaterialSession([])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="digital_human")
    )

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "digital_human_material_not_found"
    assert client.updates == []


def test_resolver_rejects_malformed_insert_before_any_side_effect(tmp_path: Path) -> None:
    client = FakeAssetGraphClient({})
    session = FakeMaituMaterialSession([])
    plan = {"operations": [{"operation_type": "insert_asset_layer", "layer_type": "product_image", "asset_code": ""}]}

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_material_operation_plan"
    assert session.list_calls == 0
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_rejects_conflicting_layer_types_for_one_asset_before_side_effect(tmp_path: Path) -> None:
    asset_code = "AG-MIXED-1"
    client = FakeAssetGraphClient({asset_code: {"asset_code": asset_code}})
    session = FakeMaituMaterialSession([])
    plan = {
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": asset_code, "layer_type": "product_image"},
            {"operation_type": "insert_asset_layer", "asset_code": asset_code, "layer_type": "product_video"},
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "conflicting_asset_layer_types"
    assert session.list_calls == 0
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_fails_closed_on_multiple_matches_even_when_url_is_shared(tmp_path: Path) -> None:
    asset_code = "AG-IMG-SHARED"
    client = FakeAssetGraphClient({asset_code: {"asset_code": asset_code, "subject": "礼盒"}})
    session = FakeMaituMaterialSession(
        [
            {"id": 1, "name": "礼盒", "type": "image", "url": "https://static.example/shared.png"},
            {"id": 2, "name": "礼盒", "type": "image", "url": "https://static.example/shared.png"},
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "ambiguous_maitu_material_match"
    assert result.issues[0].candidate_material_ids == [1, 2]
    assert client.updates == []


def test_resolver_rejects_conflicting_duplicate_records_for_stored_material_id(tmp_path: Path) -> None:
    asset_code = "AG-IMG-DUPLICATE-ID"
    client = FakeAssetGraphClient(
        {
            asset_code: {
                "asset_code": asset_code,
                "maitu_material_id": 88,
                "source_material_type": "image",
                "source_material_url": "https://static.example/stored.png",
            }
        }
    )
    session = FakeMaituMaterialSession(
        [
            {"id": 88, "name": "礼盒", "type": "image", "url": "https://static.example/a.png"},
            {"id": 88, "name": "礼盒", "type": "image", "url": "https://static.example/b.png"},
        ]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "ambiguous_stored_maitu_material"
    assert result.issues[0].candidate_material_ids == [88]
    assert client.updates == []


def test_resolver_rejects_incompatible_upload_response(tmp_path: Path) -> None:
    asset_code = "AG-VID-WRONG-UPLOAD"
    relative = "视频/商品视频.mp4"
    local_path = tmp_path / relative
    local_path.parent.mkdir(parents=True)
    local_path.write_bytes(b"video")
    client = FakeAssetGraphClient({asset_code: {"asset_code": asset_code, "subject": "商品视频", "local_relative_path": relative}})
    session = FakeMaituMaterialSession(
        [],
        uploaded={asset_code: {"id": 8, "name": "商品视频.png", "type": "image", "url": "https://static.example/wrong.png"}},
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(
        plan_for(asset_code, layer_type="product_video")
    )

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_maitu_material_binding"
    assert client.updates == []


def test_resolver_preflight_issue_prevents_later_upload(tmp_path: Path) -> None:
    missing_code = "AG-IMG-MISSING"
    upload_code = "AG-IMG-UPLOAD"
    relative = "商品图/可上传.png"
    upload_path = tmp_path / relative
    upload_path.parent.mkdir(parents=True)
    upload_path.write_bytes(b"image")
    client = FakeAssetGraphClient(
        {
            missing_code: {"asset_code": missing_code, "subject": "缺失", "local_relative_path": "商品图/不存在.png"},
            upload_code: {"asset_code": upload_code, "subject": "可上传", "local_relative_path": relative},
        }
    )
    session = FakeMaituMaterialSession(
        [],
        uploaded={upload_code: {"id": 9, "name": "可上传.png", "type": "image", "url": "https://static.example/uploaded.png"}},
    )
    plan = {
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": missing_code, "layer_type": "product_image"},
            {"operation_type": "insert_asset_layer", "asset_code": upload_code, "layer_type": "product_image"},
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_rejects_binding_writeback_mismatch(tmp_path: Path) -> None:
    asset_code = "AG-IMG-MISMATCH"

    class MismatchClient(FakeAssetGraphClient):
        def update_asset_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.updates.append((asset_code, dict(payload)))
            return {"asset_code": asset_code, "maitu_material_id": 999, "source_material_type": "image"}

    client = MismatchClient({asset_code: {"asset_code": asset_code, "subject": "礼盒"}})
    session = FakeMaituMaterialSession([{"id": 10, "name": "礼盒", "type": "image", "url": "https://static.example/gift.png"}])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "binding_writeback_verification_failed"
    assert "material_id" not in result.operation_plan["operations"][0]


def test_resolver_rejects_binding_writeback_for_wrong_asset_code(tmp_path: Path) -> None:
    asset_code = "AG-IMG-WRONG-WRITEBACK"

    class WrongAssetClient(FakeAssetGraphClient):
        def update_asset_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.updates.append((asset_code, dict(payload)))
            return {"asset_code": "AG-IMG-OTHER", **payload}

    client = WrongAssetClient({asset_code: {"asset_code": asset_code, "subject": "礼盒"}})
    session = FakeMaituMaterialSession(
        [{"id": 13, "name": "礼盒", "type": "image", "url": "https://static.example/gift.png"}]
    )

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "binding_writeback_verification_failed"
    assert "material_id" not in result.operation_plan["operations"][0]


def test_resolver_rejects_non_object_plan_before_any_side_effect(tmp_path: Path) -> None:
    client = FakeAssetGraphClient({})
    session = FakeMaituMaterialSession([])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan([])  # type: ignore[arg-type]

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_material_operation_plan"
    assert session.list_calls == 0
    assert client.updates == []


def test_resolver_rejects_unknown_or_go_live_operation_before_any_side_effect(tmp_path: Path) -> None:
    asset_code = "AG-IMG-SAFE"
    client = FakeAssetGraphClient({asset_code: {"asset_code": asset_code, "subject": "礼盒"}})
    session = FakeMaituMaterialSession([{"id": 20, "name": "礼盒", "type": "image", "url": "https://static.example/gift.png"}])
    plan = {
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": asset_code, "layer_type": "product_image"},
            {"operation_type": "go_live"},
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_material_operation_plan"
    assert session.list_calls == 0
    assert client.updates == []


def test_resolver_rejects_blocking_placeholder_before_any_side_effect(tmp_path: Path) -> None:
    client = FakeAssetGraphClient({})
    session = FakeMaituMaterialSession([])
    plan = {"operations": [{"operation_type": "placeholder_required", "blocks_execution": True}]}

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "unresolved_material_placeholder"
    assert session.list_calls == 0
    assert client.updates == []


def test_resolver_rejects_non_string_asset_code_before_any_side_effect(tmp_path: Path) -> None:
    client = FakeAssetGraphClient({})
    session = FakeMaituMaterialSession([])
    plan = {"operations": [{"operation_type": "insert_asset_layer", "asset_code": 123, "layer_type": "product_image"}]}

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_material_operation_plan"
    assert session.list_calls == 0
    assert session.upload_calls == []


@pytest.mark.parametrize(
    ("operation_type", "asset_code", "layer_type"),
    [
        (" insert_asset_layer", "AG-IMG-CANONICAL", "product_image"),
        ("insert_asset_layer", " AG-IMG-CANONICAL", "product_image"),
        ("insert_asset_layer", "AG-IMG-CANONICAL", "product_image "),
    ],
)
def test_resolver_rejects_noncanonical_whitespace_before_any_side_effect(
    tmp_path: Path,
    operation_type: str,
    asset_code: str,
    layer_type: str,
) -> None:
    client = FakeAssetGraphClient({"AG-IMG-CANONICAL": {"asset_code": "AG-IMG-CANONICAL"}})
    session = FakeMaituMaterialSession([])
    plan = {
        "operations": [
            {"operation_type": operation_type, "asset_code": asset_code, "layer_type": layer_type}
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_material_operation_plan"
    assert session.list_calls == 0
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_rejects_mismatched_asset_response_before_inventory_lookup(tmp_path: Path) -> None:
    requested_code = "AG-IMG-REQUESTED"
    client = FakeAssetGraphClient({requested_code: {"asset_code": "AG-IMG-OTHER", "subject": "错误素材"}})
    session = FakeMaituMaterialSession([])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(requested_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_asset_response"
    assert session.list_calls == 0
    assert session.upload_calls == []


def test_resolver_rejects_malformed_inventory_schema(tmp_path: Path) -> None:
    asset_code = "AG-IMG-INVENTORY"
    client = FakeAssetGraphClient({asset_code: {"asset_code": asset_code, "subject": "礼盒"}})

    class MalformedInventorySession(FakeMaituMaterialSession):
        def list_maitu_materials(self) -> list[dict[str, Any]]:
            self.list_calls += 1
            return [{"id": "bad", "name": "礼盒", "type": "image"}]

    session = MalformedInventorySession([])
    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "maitu_inventory_lookup_failed"
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_preflights_all_local_file_types_before_first_upload(tmp_path: Path) -> None:
    image_code = "AG-IMG-UPLOAD-FIRST"
    video_code = "AG-VID-WRONG-SUFFIX"
    image_relative = "商品图/可上传.png"
    wrong_video_relative = "视频/错误.png"
    for relative in (image_relative, wrong_video_relative):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset")
    client = FakeAssetGraphClient(
        {
            image_code: {"asset_code": image_code, "subject": "可上传", "local_relative_path": image_relative},
            video_code: {"asset_code": video_code, "subject": "错误视频", "local_relative_path": wrong_video_relative},
        }
    )
    session = FakeMaituMaterialSession(
        [],
        uploaded={image_code: {"id": 11, "name": "可上传.png", "type": "image", "url": "https://static.example/ok.png"}},
    )
    plan = {
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": image_code, "layer_type": "product_image"},
            {"operation_type": "insert_asset_layer", "asset_code": video_code, "layer_type": "product_video"},
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "local_asset_type_mismatch"
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_preflights_all_filename_match_keys_before_first_upload(tmp_path: Path) -> None:
    first_code = "AG-IMG-UPLOAD-FIRST-NAME"
    bad_name_code = "AG-IMG-EMPTY-NAME"
    first_relative = "商品图/可上传.png"
    bad_relative = "商品图/---.png"
    for relative in (first_relative, bad_relative):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
    client = FakeAssetGraphClient(
        {
            first_code: {"asset_code": first_code, "subject": "可上传", "local_relative_path": first_relative},
            bad_name_code: {"asset_code": bad_name_code, "subject": "", "local_relative_path": bad_relative},
        }
    )
    session = FakeMaituMaterialSession(
        [],
        uploaded={first_code: {"id": 14, "name": "可上传.png", "type": "image", "url": "https://static.example/ok.png"}},
    )
    plan = {
        "operations": [
            {"operation_type": "insert_asset_layer", "asset_code": first_code, "layer_type": "product_image"},
            {"operation_type": "insert_asset_layer", "asset_code": bad_name_code, "layer_type": "product_image"},
        ]
    }

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan)

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "local_asset_filename_unmatchable"
    assert session.upload_calls == []
    assert client.updates == []


def test_resolver_rejects_regular_binding_without_authoritative_https_url(tmp_path: Path) -> None:
    asset_code = "AG-IMG-INCOMPLETE"
    client = FakeAssetGraphClient(
        {asset_code: {"asset_code": asset_code, "subject": "礼盒", "maitu_material_id": 12, "source_material_type": "image"}}
    )
    session = FakeMaituMaterialSession([{"id": 12, "name": "礼盒", "type": "image"}])

    result = MaituMaterialResolver(asset_client=client, session=session, assets_root=tmp_path).resolve_plan(plan_for(asset_code))

    assert result.status == "completed_with_manual_review"
    assert result.issues[0].reason == "invalid_maitu_material_binding"
    assert client.updates == []
