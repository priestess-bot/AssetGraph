#!/usr/bin/env python3
"""Build Agent/RAG retrieval documents for imported AssetGraph assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, Sequence


@dataclass(slots=True)
class BuildOptions:
    api_base_url: str = "http://127.0.0.1:8000"
    page_size: int = 100
    documents_output: Path = Path("docs/asset-numbering/asset_retrieval_documents.jsonl")
    summary_output: Path | None = None
    embeddings_output: Path | None = None
    embed: bool = False
    embedding_batch_size: int = 16
    embedding_dimensions: int | None = None


class AssetGraphClient(Protocol):
    def get_json(self, path: str) -> Any: ...

    def post_json(self, path: str, payload: dict[str, Any]) -> Any: ...


class HttpAssetGraphClient:
    def __init__(self, api_base_url: str, timeout_seconds: float = 120.0) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> Any:
        request = urllib.request.Request(f"{self.api_base_url}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            f"{self.api_base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def fetch_all_assets(client: AssetGraphClient, *, page_size: int) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"limit": page_size, "offset": offset})
        page = client.get_json(f"/api/assets?{query}")
        if not isinstance(page, list):
            raise RuntimeError("GET /api/assets did not return a list")
        assets.extend(row for row in page if isinstance(row, dict))
        if len(page) < page_size:
            break
        offset += page_size
    return assets


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_retrieval_content(asset: dict[str, Any]) -> str:
    display_code = clean(asset.get("display_code") or asset.get("local_file_code") or asset.get("asset_code"))
    lines = [
        f"素材编号：{display_code}",
        f"全局编号：{clean(asset.get('asset_code'))}",
        f"标题：{clean(asset.get('title'))}",
        f"文件类型：{clean(asset.get('asset_type'))}",
        f"麦兔分类：{clean(asset.get('maitu_category'))}",
        f"麦兔原生类型：{clean(asset.get('maitu_type'))}",
        f"用途：{clean(asset.get('usage'))}",
        f"主体：{clean(asset.get('subject'))}",
        f"文件角色：{clean(asset.get('file_role'))}",
        f"文件名：{clean(asset.get('original_filename'))}",
        f"相对路径：{clean(asset.get('local_relative_path'))}",
        f"Browser-use提示：{clean(asset.get('browser_use_hint'))}",
    ]
    description = clean(asset.get("description"))
    if description:
        lines.append(f"描述：{description}")
    duplicate_group = clean(asset.get("duplicate_group"))
    if duplicate_group:
        lines.append(
            "重复组："
            f"{duplicate_group}；组内序号：{clean(asset.get('duplicate_rank'))}；"
            f"组内数量：{clean(asset.get('duplicate_count'))}"
        )
    return "\n".join(lines)


def build_document(asset: dict[str, Any]) -> dict[str, Any]:
    asset_code = clean(asset.get("asset_code"))
    content = build_retrieval_content(asset)
    return {
        "document_id": f"asset:{asset_code}:retrieval",
        "document_type": "asset_retrieval_profile",
        "asset_code": asset_code,
        "display_code": clean(asset.get("display_code") or asset.get("local_file_code") or asset_code),
        "local_file_code": clean(asset.get("local_file_code")),
        "title": clean(asset.get("title")),
        "content": content,
        "content_hash": content_hash(content),
        "metadata": {
            "asset_type": clean(asset.get("asset_type")),
            "maitu_category": clean(asset.get("maitu_category")),
            "maitu_type": clean(asset.get("maitu_type")),
            "usage": clean(asset.get("usage")),
            "subject": clean(asset.get("subject")),
            "file_role": clean(asset.get("file_role")),
            "source_system": clean(asset.get("source_system")),
            "local_relative_path": clean(asset.get("local_relative_path")),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def embed_documents(
    client: AssetGraphClient,
    documents: list[dict[str, Any]],
    *,
    batch_size: int,
    dimensions: int | None,
) -> list[dict[str, Any]]:
    embeddings: list[dict[str, Any]] = []
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        payload: dict[str, Any] = {"texts": [doc["content"] for doc in batch], "is_query": False}
        if dimensions is not None:
            payload["dimensions"] = dimensions
        response = client.post_json("/api/rag/embeddings", payload)
        vectors = response.get("vectors") if isinstance(response, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise RuntimeError("/api/rag/embeddings returned unexpected vector count")
        model = str(response.get("model") or "")
        dimension = int(response.get("dimension") or (len(vectors[0]) if vectors else 0))
        for doc, vector in zip(batch, vectors, strict=True):
            embeddings.append(
                {
                    "document_id": doc["document_id"],
                    "asset_code": doc["asset_code"],
                    "content_hash": doc["content_hash"],
                    "model": model,
                    "dimension": dimension,
                    "vector": vector,
                }
            )
    return embeddings


def summarize(documents: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> dict[str, Any]:
    by_asset_type = Counter(doc["metadata"]["asset_type"] for doc in documents if doc["metadata"].get("asset_type"))
    by_maitu_category = Counter(doc["metadata"]["maitu_category"] for doc in documents if doc["metadata"].get("maitu_category"))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "document_count": len(documents),
        "embedding_count": len(embeddings),
        "by_asset_type": dict(by_asset_type),
        "by_maitu_category": dict(by_maitu_category),
    }


def render_summary(report: dict[str, Any]) -> str:
    def table(mapping: dict[str, int]) -> str:
        lines = ["| 项 | 数量 |", "| --- | ---: |"]
        for key, count in mapping.items():
            lines.append(f"| {key} | {count} |")
        return "\n".join(lines) if len(lines) > 2 else "无"

    return f"""# AssetGraph 素材检索文本生成报告

生成时间：{report['generated_at']}

- 文档数：{report['document_count']}
- embedding 数：{report['embedding_count']}

## 按文件类型分布

{table(report['by_asset_type'])}

## 按麦兔分类分布

{table(report['by_maitu_category'])}
"""


def run_build(options: BuildOptions, *, client: AssetGraphClient | None = None) -> dict[str, Any]:
    client = client or HttpAssetGraphClient(options.api_base_url)
    assets = fetch_all_assets(client, page_size=options.page_size)
    documents = [build_document(asset) for asset in assets]
    write_jsonl(options.documents_output, documents)

    embeddings: list[dict[str, Any]] = []
    if options.embed:
        if options.embeddings_output is None:
            raise ValueError("embeddings_output is required when embed=True")
        embeddings = embed_documents(
            client,
            documents,
            batch_size=options.embedding_batch_size,
            dimensions=options.embedding_dimensions,
        )
        write_jsonl(options.embeddings_output, embeddings)

    report = summarize(documents, embeddings)
    if options.summary_output:
        options.summary_output.parent.mkdir(parents=True, exist_ok=True)
        options.summary_output.write_text(render_summary(report), encoding="utf-8")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AssetGraph asset retrieval documents and optional Qwen3 embeddings.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--documents-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--embeddings-output", type=Path)
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    parser.add_argument("--embedding-dimensions", type=int)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_build(
        BuildOptions(
            api_base_url=args.api_base_url,
            page_size=args.page_size,
            documents_output=args.documents_output,
            summary_output=args.summary_output,
            embeddings_output=args.embeddings_output,
            embed=args.embed,
            embedding_batch_size=args.embedding_batch_size,
            embedding_dimensions=args.embedding_dimensions,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
