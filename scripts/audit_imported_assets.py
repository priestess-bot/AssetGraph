#!/usr/bin/env python3
"""Audit imported AssetGraph materials for Agent-facing retrieval quality."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, Sequence


@dataclass(slots=True)
class AuditOptions:
    api_base_url: str = "http://127.0.0.1:8000"
    page_size: int = 100
    json_output: Path | None = None
    markdown_output: Path | None = None


class AuditClient(Protocol):
    def get_json(self, path: str) -> Any: ...


class AssetGraphAuditClient:
    def __init__(self, api_base_url: str, timeout_seconds: float = 30.0) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> Any:
        request = urllib.request.Request(f"{self.api_base_url}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def fetch_all_assets(client: AuditClient, *, page_size: int) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"limit": page_size, "offset": offset})
        page = client.get_json(f"/api/assets?{query}")
        if not isinstance(page, list):
            raise RuntimeError("GET /api/assets did not return a list")
        assets.extend(item for item in page if isinstance(item, dict))
        if len(page) < page_size:
            break
        offset += page_size
    return assets


def duplicate_local_file_codes(assets: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(asset.get("local_file_code") or "") for asset in assets)
    return {code: count for code, count in counts.items() if code and count > 1}


def build_report(*, stats: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    missing_fields = dict(stats.get("missing_fields") or {})
    duplicate_codes = duplicate_local_file_codes(assets)
    total_assets = int(stats.get("total_assets") or 0)
    tagged_asset_count = int(stats.get("tagged_asset_count") or 0)
    required_fields_complete = all(int(value or 0) == 0 for value in missing_fields.values())
    local_duplicate_groups = int(stats.get("local_file_code_duplicate_groups") or 0)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total_assets": total_assets,
            "checked_assets": len(assets),
            "asset_file_count": int(stats.get("asset_file_count") or 0),
            "tag_count": int(stats.get("tag_count") or 0),
            "tagged_asset_count": tagged_asset_count,
            "asset_tag_relation_count": int(stats.get("asset_tag_relation_count") or 0),
            "tag_coverage_ratio": round(tagged_asset_count / total_assets, 4) if total_assets else 0.0,
            "duplicate_group_count": int(stats.get("duplicate_group_count") or 0),
            "duplicate_asset_count": int(stats.get("duplicate_asset_count") or 0),
            "local_file_code_duplicate_groups": local_duplicate_groups,
        },
        "distributions": {
            "by_asset_type": dict(stats.get("by_asset_type") or {}),
            "by_maitu_category": dict(stats.get("by_maitu_category") or {}),
            "by_maitu_type": dict(stats.get("by_maitu_type") or {}),
            "by_usage": dict(stats.get("by_usage") or {}),
        },
        "missing_fields": missing_fields,
        "duplicate_local_file_codes": duplicate_codes,
        "quality_gates": {
            "asset_count_matches_stats": len(assets) == total_assets,
            "required_fields_complete": required_fields_complete,
            "local_file_codes_unique": local_duplicate_groups == 0 and not duplicate_codes,
            "browser_use_hints_complete": int(missing_fields.get("browser_use_hint") or 0) == 0,
            "all_assets_tagged": tagged_asset_count == total_assets if total_assets else False,
        },
    }


def markdown_table(mapping: dict[str, Any], *, limit: int = 20) -> str:
    lines = ["| 项 | 数量 |", "| --- | ---: |"]
    for key, value in list(mapping.items())[:limit]:
        lines.append(f"| {key} | {value} |")
    if not mapping:
        lines.append("| 无 | 0 |")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    gates = report["quality_gates"]
    distributions = report["distributions"]
    missing_fields = report["missing_fields"]
    duplicate_codes = report["duplicate_local_file_codes"]
    gate_lines = "\n".join(f"- {'PASS' if passed else 'FAIL'} `{name}`" for name, passed in gates.items())

    return f"""# AssetGraph 素材入库质量报告

生成时间：{report['generated_at']}

## 总览

- 总素材数：{summary['total_assets']}
- 本次检查素材数：{summary['checked_assets']}
- 原始文件记录数：{summary['asset_file_count']}
- 标签数：{summary['tag_count']}
- 已打标签素材数：{summary['tagged_asset_count']}
- 标签关系数：{summary['asset_tag_relation_count']}
- 标签覆盖率：{summary['tag_coverage_ratio']:.2%}
- 重复组数：{summary['duplicate_group_count']}
- 重复组内素材数：{summary['duplicate_asset_count']}
- local_file_code 重复组数：{summary['local_file_code_duplicate_groups']}

## 质量门禁

{gate_lines}

## 缺失字段

{markdown_table(missing_fields)}

## 按文件类型分布

{markdown_table(distributions['by_asset_type'])}

## 按麦兔分类分布

{markdown_table(distributions['by_maitu_category'])}

## 按麦兔原生类型分布

{markdown_table(distributions['by_maitu_type'])}

## 按用途分布

{markdown_table(distributions['by_usage'])}

## local_file_code 重复详情

{markdown_table(duplicate_codes)}
"""


def run_audit(options: AuditOptions, *, client: AuditClient | None = None) -> dict[str, Any]:
    client = client or AssetGraphAuditClient(options.api_base_url)
    stats = client.get_json("/api/assets/stats")
    if not isinstance(stats, dict):
        raise RuntimeError("GET /api/assets/stats did not return an object")
    assets = fetch_all_assets(client, page_size=options.page_size)
    report = build_report(stats=stats, assets=assets)

    if options.json_output:
        options.json_output.parent.mkdir(parents=True, exist_ok=True)
        options.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if options.markdown_output:
        options.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        options.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit imported AssetGraph assets for Agent-facing quality.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_audit(
        AuditOptions(
            api_base_url=args.api_base_url,
            page_size=args.page_size,
            json_output=args.json_output,
            markdown_output=args.markdown_output,
        )
    )
    print(json.dumps({"summary": report["summary"], "quality_gates": report["quality_gates"]}, ensure_ascii=False, indent=2))
    return 0 if all(report["quality_gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
