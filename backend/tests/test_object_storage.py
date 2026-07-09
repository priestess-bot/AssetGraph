from __future__ import annotations

from pathlib import Path

from app.services.object_storage import build_asset_object_key, content_type_for_path


def test_build_asset_object_key_is_stable_and_namespaced() -> None:
    key = build_asset_object_key(
        asset_code="AG-VID-20260709-000001",
        filename="MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
    )

    assert key == "assets/AG-VID-20260709-000001/original/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4"


def test_build_asset_object_key_sanitizes_path_separators() -> None:
    key = build_asset_object_key(asset_code="AG-IMG-20260709-000001", filename="nested\\bad/name.png")

    assert key == "assets/AG-IMG-20260709-000001/original/nested_bad_name.png"


def test_content_type_for_path_uses_mimetype_guess() -> None:
    assert content_type_for_path(Path("demo.mp4")) == "video/mp4"
    assert content_type_for_path(Path("unknown.assetgraph")) == "application/octet-stream"
