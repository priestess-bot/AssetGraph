from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scan_assets import build_inventory_document, scan_assets  # noqa: E402


def test_scan_assets_parses_maitu_and_digital_human_files(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    video = assets_root / "视频" / "MT-VID-0001_视频_商品讲解视频_品酒大师PRO.mp4"
    audio = assets_root / "数字分身" / "音色" / "3760_Y26音色" / "DH-VOI-0001-F002_音色_3760_Y26音色_试听音频.mp3"
    duplicate = assets_root / "装饰" / "MT-DEC-0001_装饰_品牌Logo_logo.png"
    ignored = assets_root / "_非素材文件归档" / "MT-VID-9999_视频_归档_不应扫描.mp4"

    video.parent.mkdir(parents=True)
    video.write_bytes(b"same-media-content")
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"voice-content")
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"same-media-content")
    ignored.parent.mkdir(parents=True)
    ignored.write_bytes(b"ignored")

    items = scan_assets(assets_root)

    assert len(items) == 3
    by_code = {item.file_code: item for item in items}

    maitu_video = by_code["MT-VID-0001"]
    assert maitu_video.asset_type == "VID"
    assert maitu_video.media_kind == "video"
    assert maitu_video.maitu_type == "视频"
    assert maitu_video.maitu_category == "product_video"
    assert maitu_video.usage == "商品讲解视频"
    assert maitu_video.subject == "品酒大师PRO"
    assert "品酒大师" in maitu_video.tags
    assert "PRO" in maitu_video.tags
    payload = maitu_video.to_asset_create_payload()
    assert payload["status"] == "stored"
    assert payload["display_code"] == "MT-VID-0001"
    assert payload["local_file_code"] == "MT-VID-0001"
    assert payload["source_system"] == "maitu"
    assert payload["maitu_type"] == "视频"
    assert payload["usage"] == "商品讲解视频"
    assert payload["subject"] == "品酒大师PRO"
    assert payload["local_relative_path"] == "视频/MT-VID-0001_视频_商品讲解视频_品酒大师PRO.mp4"

    voice = by_code["DH-VOI-0001-F002"]
    assert voice.entity_code == "DH-VOI-0001"
    assert voice.asset_type == "AUD"
    assert voice.maitu_type == "数字分身"
    assert voice.maitu_subtype == "音色"
    assert voice.maitu_category == "voice_audio"
    assert voice.file_role == "试听音频"
    voice_payload = voice.to_asset_create_payload()
    assert voice_payload["local_file_code"] == "DH-VOI-0001-F002"
    assert voice_payload["entity_code"] == "DH-VOI-0001"
    assert voice_payload["maitu_subtype"] == "音色"

    duplicate_item = by_code["MT-DEC-0001"]
    assert maitu_video.duplicate_group == duplicate_item.duplicate_group
    assert maitu_video.duplicate_count == 2
    assert duplicate_item.duplicate_count == 2


def test_build_inventory_document_summarizes_counts(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    (assets_root / "背景").mkdir(parents=True)
    (assets_root / "背景" / "MT-BG-0001_背景_直播背景_背景-3.png").write_bytes(b"image")
    (assets_root / "视频").mkdir(parents=True)
    (assets_root / "视频" / "MT-VID-0001_视频_商品讲解视频_品酒大师PRO.mp4").write_bytes(b"video")

    items = scan_assets(assets_root)
    inventory = build_inventory_document(items, assets_root)

    assert inventory["schema_version"] == "asset_inventory.v1"
    assert inventory["asset_count"] == 2
    assert inventory["asset_type_counts"] == {"IMG": 1, "VID": 1}
    assert inventory["parse_status_counts"] == {"parsed": 2}
    assert inventory["duplicate_group_count"] == 0
    assert len(inventory["assets"]) == 2
