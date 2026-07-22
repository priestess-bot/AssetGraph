from __future__ import annotations

import io
import json
import stat
from pathlib import Path

from browser_use_worker.maitu_inventory_sync import MaituInventoryCollector


class Session:
    def list_maitu_materials(self):
        row = {
            "id": 101,
            "name": "product.mov",
            "type": "decorative_video",
            "url": "https://cdn.example/product.mov?signature=temporary#download",
            "cover_url": "https://cdn.example/product.jpg?access_token=temporary",
        }
        return [row, dict(row)]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_collector_deduplicates_downloads_and_adds_reference_template(tmp_path: Path) -> None:
    opened_urls: list[str] = []

    def open_material(request, **_kwargs):
        opened_urls.append(request.full_url)
        return Response(b"video-bytes")

    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "file_code": "MT-TPL-0001",
                        "maitu_type": "模版",
                        "title": "演示模版",
                        "relative_path": "模版/preview.png",
                        "sha256": "a" * 64,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    collector = MaituInventoryCollector(
        session=Session(),
        mirror_root=tmp_path / "mirror",
        local_catalog_path=catalog,
        opener=open_material,
        legacy_mapping_path=tmp_path / "missing-mapping.json",
    )

    result = collector.collect(download_missing=True)

    assert result.summary["remote_row_count"] == 2
    assert result.summary["duplicate_row_count"] == 1
    assert result.summary["item_count"] == 2
    assert result.summary["reference_template_count"] == 1
    assert result.summary["downloaded_count"] == 1
    material = next(item for item in result.items if item["material_type"] == "decorative_video")
    assert opened_urls == ["https://cdn.example/product.mov?signature=temporary#download"]
    assert material["source_material_url"] == "https://cdn.example/product.mov"
    assert material["source_cover_url"] == "https://cdn.example/product.jpg"
    template = next(item for item in result.items if item["material_type"] == "template")
    assert template["metadata"]["reference_only"] is True
    assert template["metadata"]["reconstruction_fidelity"] == "approximate"
    observation = Path(result.observation_path)
    assert observation.is_file()
    assert stat.S_IMODE(observation.stat().st_mode) == 0o600


def test_existing_catalog_material_is_reused_without_download(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "file_code": "MT-VID-0001",
                        "filename": "product.mov",
                        "relative_path": "视频/product.mov",
                        "sha256": "b" * 64,
                        "maitu_type": "视频",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    catalog.with_name("current_asset_import.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "local_file_code": "MT-VID-0001",
                        "asset_code": "AG-VID-20260720-000001",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    collector = MaituInventoryCollector(
        session=Session(),
        mirror_root=tmp_path / "mirror",
        local_catalog_path=catalog,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not download")),
        legacy_mapping_path=tmp_path / "missing-mapping.json",
    )

    result = collector.collect(download_missing=True)

    item = result.items[0]
    assert item["checksum_sha256"] == "b" * 64
    assert item["metadata"]["local_relative_path"] == "视频/product.mov"
    assert item["asset_code"] == "AG-VID-20260720-000001"
    assert result.summary["downloaded_count"] == 0

    observation = Path(result.observation_path)
    original_bytes = observation.read_bytes()
    original_mtime = observation.stat().st_mtime_ns
    repeated = collector.collect(download_missing=True)
    assert repeated.source_revision == result.source_revision
    assert Path(repeated.observation_path).read_bytes() == original_bytes
    assert observation.stat().st_mtime_ns == original_mtime


def test_legacy_material_id_mapping_survives_remote_filename_changes(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "file_code": "MT-VID-0007",
                        "filename": "renamed-local.mov",
                        "relative_path": "视频/renamed-local.mov",
                        "sha256": "c" * 64,
                        "maitu_type": "视频",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    catalog.with_name("current_asset_import.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "local_file_code": "MT-VID-0007",
                        "asset_code": "AG-VID-20260720-000007",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    mapping = tmp_path / "legacy-mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "file_code": "MT-VID-0007",
                        "maitu_material_id_guess": "101",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    collector = MaituInventoryCollector(
        session=Session(),
        mirror_root=tmp_path / "mirror",
        local_catalog_path=catalog,
        legacy_mapping_path=mapping,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not download")),
    )

    result = collector.collect(download_missing=True)

    item = result.items[0]
    assert item["asset_code"] == "AG-VID-20260720-000007"
    assert item["checksum_sha256"] == "c" * 64
    assert item["metadata"]["local_relative_path"] == "视频/renamed-local.mov"
