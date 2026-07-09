from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_imported_assets import AuditOptions, run_audit  # noqa: E402


class FakeAuditClient:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def get_json(self, path: str) -> Any:
        self.requests.append(path)
        if path == "/api/assets/stats":
            return {
                "total_assets": 2,
                "asset_file_count": 1,
                "duplicate_group_count": 1,
                "duplicate_asset_count": 2,
                "local_file_code_duplicate_groups": 0,
                "tag_count": 3,
                "tagged_asset_count": 2,
                "asset_tag_relation_count": 4,
                "by_asset_type": {"IMG": 1, "VID": 1},
                "by_maitu_category": {"product_image": 1, "product_video": 1},
                "by_maitu_type": {"图片": 1, "视频": 1},
                "by_usage": {"商品主图": 1, "商品讲解视频": 1},
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
        if path == "/api/assets?limit=2&offset=0":
            return [
                {
                    "asset_code": "AG-IMG-20260709-000001",
                    "display_code": "MT-IMG-0001",
                    "local_file_code": "MT-IMG-0001",
                    "asset_type": "IMG",
                    "title": "商品主图",
                    "maitu_category": "product_image",
                    "maitu_type": "图片",
                    "usage": "商品主图",
                    "subject": "品酒大师PRO",
                    "browser_use_hint": "用于麦兔图片素材选择",
                },
                {
                    "asset_code": "AG-VID-20260709-000001",
                    "display_code": "MT-VID-0001",
                    "local_file_code": "MT-VID-0001",
                    "asset_type": "VID",
                    "title": "商品讲解视频",
                    "maitu_category": "product_video",
                    "maitu_type": "视频",
                    "usage": "商品讲解视频",
                    "subject": "品酒大师PRO",
                    "browser_use_hint": "用于麦兔视频素材选择",
                },
            ]
        if path == "/api/assets?limit=2&offset=2":
            return []
        raise AssertionError(path)


def test_run_audit_fetches_assets_stats_and_writes_reports(tmp_path: Path) -> None:
    json_output = tmp_path / "quality.json"
    markdown_output = tmp_path / "quality.md"

    report = run_audit(
        AuditOptions(
            api_base_url="http://assetgraph.test",
            page_size=2,
            json_output=json_output,
            markdown_output=markdown_output,
        ),
        client=FakeAuditClient(),
    )

    assert report["summary"]["total_assets"] == 2
    assert report["summary"]["checked_assets"] == 2
    assert report["quality_gates"]["required_fields_complete"] is True
    assert report["quality_gates"]["local_file_codes_unique"] is True
    assert report["quality_gates"]["asset_count_matches_stats"] is True
    assert json.loads(json_output.read_text(encoding="utf-8"))["summary"]["tagged_asset_count"] == 2
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "# AssetGraph 素材入库质量报告" in markdown
    assert "总素材数：2" in markdown
    assert "IMG" in markdown and "VID" in markdown
