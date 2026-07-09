from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_asset_retrieval_documents import BuildOptions, run_build  # noqa: E402


class FakeAssetGraphClient:
    def __init__(self) -> None:
        self.post_payloads: list[dict[str, Any]] = []

    def get_json(self, path: str) -> Any:
        if path == "/api/assets?limit=2&offset=0":
            return [
                {
                    "asset_code": "AG-IMG-20260709-000001",
                    "display_code": "MT-IMG-0001",
                    "local_file_code": "MT-IMG-0001",
                    "asset_type": "IMG",
                    "title": "品酒大师商品主图",
                    "original_filename": "MT-IMG-0001_图片_商品主图_品酒大师PRO.png",
                    "maitu_category": "product_image",
                    "maitu_type": "图片",
                    "usage": "商品主图",
                    "subject": "品酒大师PRO",
                    "file_role": "商品主图",
                    "browser_use_hint": "用于麦兔图片素材选择：品酒大师PRO",
                    "local_relative_path": "图片/MT-IMG-0001.png",
                    "description": "商品主图素材",
                },
                {
                    "asset_code": "AG-VID-20260709-000001",
                    "display_code": "MT-VID-0001",
                    "local_file_code": "MT-VID-0001",
                    "asset_type": "VID",
                    "title": "品酒大师商品讲解视频",
                    "original_filename": "MT-VID-0001_视频_商品讲解视频_品酒大师PRO.mp4",
                    "maitu_category": "product_video",
                    "maitu_type": "视频",
                    "usage": "商品讲解视频",
                    "subject": "品酒大师PRO",
                    "file_role": "商品讲解视频",
                    "browser_use_hint": "用于麦兔视频素材选择：品酒大师PRO",
                    "local_relative_path": "视频/MT-VID-0001.mp4",
                    "description": "商品讲解视频素材",
                },
            ]
        if path == "/api/assets?limit=2&offset=2":
            return []
        raise AssertionError(path)

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        assert path == "/api/rag/embeddings"
        self.post_payloads.append(payload)
        return {
            "model": "qwen3-embedding-4b-local",
            "dimension": 3,
            "vectors": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_run_build_writes_retrieval_documents_and_embeddings(tmp_path: Path) -> None:
    documents_output = tmp_path / "asset_retrieval_documents.jsonl"
    embeddings_output = tmp_path / "asset_retrieval_embeddings.jsonl"
    summary_output = tmp_path / "asset_retrieval_documents.md"
    client = FakeAssetGraphClient()

    report = run_build(
        BuildOptions(
            api_base_url="http://assetgraph.test",
            page_size=2,
            documents_output=documents_output,
            summary_output=summary_output,
            embeddings_output=embeddings_output,
            embed=True,
            embedding_batch_size=2,
            embedding_dimensions=1024,
        ),
        client=client,
    )

    docs = read_jsonl(documents_output)
    embeddings = read_jsonl(embeddings_output)
    assert report["document_count"] == 2
    assert docs[0]["document_id"] == "asset:AG-IMG-20260709-000001:retrieval"
    assert docs[0]["asset_code"] == "AG-IMG-20260709-000001"
    assert "素材编号：MT-IMG-0001" in docs[0]["content"]
    assert "主体：品酒大师PRO" in docs[0]["content"]
    assert docs[0]["content_hash"]
    assert embeddings[0]["document_id"] == docs[0]["document_id"]
    assert embeddings[0]["dimension"] == 3
    assert client.post_payloads[0]["is_query"] is False
    assert client.post_payloads[0]["dimensions"] == 1024
    markdown = summary_output.read_text(encoding="utf-8")
    assert "# AssetGraph 素材检索文本生成报告" in markdown
    assert "文档数：2" in markdown
    assert "IMG" in markdown and "VID" in markdown
