from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_assets import ImportOptions, run_import  # noqa: E402


class FakeImportClient:
    def __init__(self, existing: dict[str, dict[str, Any]] | None = None) -> None:
        self.existing = existing or {}
        self.created_payloads: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []

    def get_asset_by_local_file_code(self, source_system: str, local_file_code: str) -> dict[str, Any] | None:
        return self.existing.get(local_file_code)

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        asset_code = f"AG-{payload['asset_type']}-20260709-{len(self.created_payloads) + 1:06d}"
        row = {"asset_code": asset_code, **payload}
        self.created_payloads.append(payload)
        self.existing[payload["local_file_code"]] = row
        return row

    def upload_asset_file(
        self,
        *,
        asset_code: str,
        path: Path,
        file_role: str,
        local_file_code: str,
        source_relative_path: str,
        checksum_sha256: str,
    ) -> dict[str, Any]:
        self.uploads.append(
            {
                "asset_code": asset_code,
                "path": path,
                "file_role": file_role,
                "local_file_code": local_file_code,
                "source_relative_path": source_relative_path,
                "checksum_sha256": checksum_sha256,
            }
        )
        return {"asset_code": asset_code, "file_role": file_role, "local_file_code": local_file_code}


def write_inventory(tmp_path: Path, items: list[dict[str, Any]]) -> Path:
    path = tmp_path / "asset_inventory.json"
    path.write_text(json.dumps({"asset_count": len(items), "assets": items}, ensure_ascii=False), encoding="utf-8")
    return path


def make_item(assets_root: Path, *, code: str = "MT-VID-0001", content: bytes = b"video") -> dict[str, Any]:
    import hashlib

    relative_path = f"视频/{code}_视频_商品讲解视频_品酒大师PRO.mp4"
    media_path = assets_root / relative_path
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    return {
        "file_code": code,
        "relative_path": relative_path,
        "file_size": len(content),
        "sha256": checksum,
        "tags": ["品酒大师", "PRO"],
        "asset_create_payload": {
            "asset_type": "VID",
            "title": "视频 - 商品讲解视频 - 品酒大师PRO",
            "original_filename": media_path.name,
            "file_ext": ".mp4",
            "mime_type": "video/mp4",
            "file_size": len(content),
            "checksum_sha256": checksum,
            "status": "stored",
            "display_code": code,
            "local_file_code": code,
            "source_system": "maitu",
            "source_type": "maitu_local_material",
            "maitu_category": "product_video",
            "maitu_type": "视频",
            "usage": "商品讲解视频",
            "subject": "品酒大师PRO",
            "local_relative_path": relative_path,
        },
    }


def test_dry_run_validates_inventory_without_api_calls(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    inventory_path = write_inventory(tmp_path, [make_item(assets_root)])
    client = FakeImportClient()

    report = run_import(
        ImportOptions(inventory=inventory_path, assets_root=assets_root, dry_run=True, expected_count=1),
        client=client,
    )

    assert report["mode"] == "dry_run"
    assert report["planned_count"] == 1
    assert report["invalid_count"] == 0
    assert client.created_payloads == []


def test_dry_run_reports_checksum_mismatch(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    item = make_item(assets_root)
    item["sha256"] = "0" * 64
    item["asset_create_payload"]["checksum_sha256"] = "0" * 64
    inventory_path = write_inventory(tmp_path, [item])

    report = run_import(ImportOptions(inventory=inventory_path, assets_root=assets_root, dry_run=True), client=FakeImportClient())

    assert report["invalid_count"] == 1
    assert "checksum" in report["items"][0]["reason"]


def test_limit_restricts_planned_items(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    inventory_path = write_inventory(tmp_path, [make_item(assets_root, code="MT-VID-0001"), make_item(assets_root, code="MT-VID-0002")])

    report = run_import(ImportOptions(inventory=inventory_path, assets_root=assets_root, dry_run=True, limit=1), client=FakeImportClient())

    assert report["planned_count"] == 1
    assert report["items"][0]["local_file_code"] == "MT-VID-0001"


def test_import_creates_asset_and_uploads_file(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    inventory_path = write_inventory(tmp_path, [make_item(assets_root)])
    client = FakeImportClient()

    report = run_import(
        ImportOptions(inventory=inventory_path, assets_root=assets_root, dry_run=False, upload_files=True, write_tags=True),
        client=client,
    )

    assert report["create_count"] == 1
    assert report["file_upload_count"] == 1
    assert client.created_payloads[0]["tags"] == ["品酒大师", "PRO"]
    assert client.uploads[0]["local_file_code"] == "MT-VID-0001"


def test_import_skips_existing_local_file_code(tmp_path: Path) -> None:
    assets_root = tmp_path / "素材"
    inventory_path = write_inventory(tmp_path, [make_item(assets_root)])
    client = FakeImportClient(existing={"MT-VID-0001": {"asset_code": "AG-VID-EXISTING", "local_file_code": "MT-VID-0001"}})

    report = run_import(ImportOptions(inventory=inventory_path, assets_root=assets_root, dry_run=False, skip_existing=True), client=client)

    assert report["skip_count"] == 1
    assert report["create_count"] == 0
    assert report["items"][0]["asset_code"] == "AG-VID-EXISTING"
