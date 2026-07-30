from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app


class FakeAssetRepository:
    def __init__(self) -> None:
        self.assets = {
            "AG-VID-20260709-000001": {
                "id": "asset-id",
                "asset_code": "AG-VID-20260709-000001",
                "asset_type": "VID",
                "original_filename": "demo.mp4",
                "status": "created",
            }
        }
        self.file_rows: list[dict[str, Any]] = []
        self.status_updates: list[tuple[str, str]] = []

    def get_by_code(self, asset_code: str) -> dict[str, Any] | None:
        return self.assets.get(asset_code)

    def create_file_record(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if asset_code not in self.assets:
            return None
        row = {
            "id": "file-id",
            "asset_id": "asset-id",
            "asset_code": asset_code,
            **payload,
        }
        self.file_rows.append(row)
        return row

    def list_file_records(self, asset_code: str) -> list[dict[str, Any]]:
        return [row for row in self.file_rows if row["asset_code"] == asset_code]

    def update_status(self, asset_code: str, status: str) -> dict[str, Any] | None:
        self.status_updates.append((asset_code, status))
        asset = self.assets.get(asset_code)
        if asset is None:
            return None
        asset["status"] = status
        return asset


class FakeObjectStorage:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, *, bucket_name: str, object_key: str, path: Path, content_type: str | None = None) -> None:
        self.objects[(bucket_name, object_key)] = path.read_bytes()
        self.uploads.append(
            {
                "bucket_name": bucket_name,
                "object_key": object_key,
                "content_type": content_type,
                "bytes": path.read_bytes(),
            }
        )

    def download_file(self, *, bucket_name: str, object_key: str, destination: Path) -> None:
        destination.write_bytes(self.objects[(bucket_name, object_key)])


@pytest.fixture
def client() -> tuple[TestClient, FakeAssetRepository, FakeObjectStorage]:
    repository = FakeAssetRepository()
    storage = FakeObjectStorage()
    app.dependency_overrides[assets.get_asset_repository] = lambda: repository
    app.dependency_overrides[assets.get_asset_preview_metadata] = lambda: (
        repository.get_by_code("AG-VID-20260709-000001"),
        repository.list_file_records("AG-VID-20260709-000001"),
    )
    app.dependency_overrides[assets.get_object_storage] = lambda: storage
    with TestClient(app) as test_client:
        yield test_client, repository, storage
    app.dependency_overrides.clear()


def test_upload_asset_file_stores_file_and_creates_file_record(client: tuple[TestClient, FakeAssetRepository, FakeObjectStorage]) -> None:
    test_client, repository, storage = client

    response = test_client.post(
        "/api/assets/AG-VID-20260709-000001/files",
        files={"file": ("demo.mp4", b"video bytes", "video/mp4")},
        data={
            "file_role": "original",
            "local_file_code": "MT-VID-0024",
            "source_relative_path": "视频/demo.mp4",
            "checksum_sha256": "96b050b919f3fca2fc8b6923537136a197ad13c583beb1438d1a12ccbc999c42",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_code"] == "AG-VID-20260709-000001"
    assert body["file_role"] == "original"
    assert body["bucket_name"] == "assetgraph"
    assert body["object_key"] == "assets/AG-VID-20260709-000001/original/demo.mp4"
    assert body["local_file_code"] == "MT-VID-0024"
    assert body["file_size"] == len(b"video bytes")
    assert storage.uploads[0]["bytes"] == b"video bytes"
    assert repository.status_updates == [("AG-VID-20260709-000001", "stored")]


def test_upload_asset_file_rejects_checksum_mismatch(client: tuple[TestClient, FakeAssetRepository, FakeObjectStorage]) -> None:
    test_client, _repository, storage = client

    response = test_client.post(
        "/api/assets/AG-VID-20260709-000001/files",
        files={"file": ("demo.mp4", b"video bytes", "video/mp4")},
        data={"checksum_sha256": "0" * 64},
    )

    assert response.status_code == 400
    assert storage.uploads == []


def test_list_asset_files_returns_file_records(client: tuple[TestClient, FakeAssetRepository, FakeObjectStorage]) -> None:
    test_client, repository, _storage = client
    repository.file_rows.append(
        {
            "id": "file-id",
            "asset_id": "asset-id",
            "asset_code": "AG-VID-20260709-000001",
            "file_role": "original",
            "bucket_name": "assetgraph",
            "object_key": "assets/AG-VID-20260709-000001/original/demo.mp4",
            "mime_type": "video/mp4",
            "file_size": 11,
            "checksum_sha256": "a" * 64,
            "source_relative_path": "视频/demo.mp4",
            "local_file_code": "MT-VID-0024",
            "storage_status": "stored",
        }
    )

    response = test_client.get("/api/assets/AG-VID-20260709-000001/files")

    assert response.status_code == 200
    assert response.json()[0]["object_key"] == "assets/AG-VID-20260709-000001/original/demo.mp4"


def test_uploaded_asset_file_is_available_through_the_customer_preview(
    client: tuple[TestClient, FakeAssetRepository, FakeObjectStorage],
) -> None:
    test_client, repository, storage = client
    repository.assets["AG-VID-20260709-000001"].update(
        {"media_kind": "video", "execution_capability": "local_only"}
    )
    object_key = "assets/AG-VID-20260709-000001/original/demo.mp4"
    repository.file_rows.append(
        {
            "id": "file-id",
            "asset_id": "asset-id",
            "asset_code": "AG-VID-20260709-000001",
            "file_role": "original",
            "bucket_name": "assetgraph",
            "object_key": object_key,
            "mime_type": "video/mp4",
            "file_size": 11,
            "checksum_sha256": "a" * 64,
            "source_relative_path": None,
            "local_file_code": None,
            "storage_status": "stored",
        }
    )
    storage.objects[("assetgraph", object_key)] = b"video bytes"

    response = test_client.get("/api/assets/AG-VID-20260709-000001/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"video bytes"
