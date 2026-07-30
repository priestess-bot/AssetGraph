from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets
from app.core.config import settings
from app.main import app


class FakeAssetRepository:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows = rows

    def get_by_code(self, asset_code: str) -> dict[str, Any] | None:
        return self.rows.get(asset_code)

    def list_file_records(self, asset_code: str) -> list[dict[str, Any]]:
        return []


def _asset(*, relative_path: str, checksum: str, capability: str = "local_only") -> dict[str, Any]:
    return {
        "asset_code": "AG-IMG-20260725-000001",
        "media_kind": "image",
        "execution_capability": capability,
        "local_relative_path": relative_path,
        "checksum_sha256": checksum,
        "mime_type": "image/png",
    }


@pytest.fixture
def preview_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeAssetRepository, Path]:
    repository = FakeAssetRepository({})
    previous_root = settings.asset_materials_root
    settings.asset_materials_root = tmp_path
    app.dependency_overrides[assets.get_asset_preview_metadata] = lambda: (
        repository.get_by_code("AG-IMG-20260725-000001"),
        repository.list_file_records("AG-IMG-20260725-000001"),
    )
    with TestClient(app) as test_client:
        yield test_client, repository, tmp_path
    app.dependency_overrides.pop(assets.get_asset_preview_metadata, None)
    settings.asset_materials_root = previous_root


def test_local_only_asset_preview_streams_the_verified_file(
    preview_client: tuple[TestClient, FakeAssetRepository, Path],
) -> None:
    client, repository, root = preview_client
    content = b"local image bytes"
    candidate = root / "images" / "brand.png"
    candidate.parent.mkdir()
    candidate.write_bytes(content)
    repository.rows["AG-IMG-20260725-000001"] = _asset(
        relative_path="images/brand.png",
        checksum=hashlib.sha256(content).hexdigest(),
    )

    response = client.get("/api/assets/AG-IMG-20260725-000001/preview")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "private, no-store"


def test_asset_preview_rejects_non_local_paths_and_changed_files(
    preview_client: tuple[TestClient, FakeAssetRepository, Path],
) -> None:
    client, repository, root = preview_client
    candidate = root / "images" / "brand.png"
    candidate.parent.mkdir()
    candidate.write_bytes(b"changed")
    repository.rows["AG-IMG-20260725-000001"] = _asset(
        relative_path="../outside.png",
        checksum=hashlib.sha256(b"changed").hexdigest(),
    )
    assert client.get("/api/assets/AG-IMG-20260725-000001/preview").status_code == 404

    repository.rows["AG-IMG-20260725-000001"] = _asset(
        relative_path="images/brand.png",
        checksum="0" * 64,
    )
    assert client.get("/api/assets/AG-IMG-20260725-000001/preview").status_code == 409

    repository.rows["AG-IMG-20260725-000001"] = _asset(
        relative_path="images/brand.png",
        checksum=hashlib.sha256(b"changed").hexdigest(),
        capability="reference_only",
    )
    assert client.get("/api/assets/AG-IMG-20260725-000001/preview").status_code == 404


def test_local_video_preview_variant_uses_a_small_cached_rendition(
    preview_client: tuple[TestClient, FakeAssetRepository, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, repository, root = preview_client
    content = b"local video bytes"
    candidate = root / "videos" / "demo.mp4"
    candidate.parent.mkdir()
    candidate.write_bytes(content)
    repository.rows["AG-IMG-20260725-000001"] = {
        **_asset(
            relative_path="videos/demo.mp4",
            checksum=hashlib.sha256(content).hexdigest(),
        ),
        "media_kind": "video",
    }
    generated = root / ".asset-preview-cache" / "poster.jpg"
    generated.parent.mkdir()
    generated.write_bytes(b"poster bytes")
    monkeypatch.setattr(
        assets,
        "ensure_video_preview",
        lambda source, cache_root, **kwargs: generated,
    )

    response = client.get("/api/assets/AG-IMG-20260725-000001/preview?variant=poster")

    assert response.status_code == 200
    assert response.content == b"poster bytes"
    assert response.headers["content-type"].startswith("image/jpeg")


def test_local_image_thumbnail_uses_a_compact_cached_rendition(
    preview_client: tuple[TestClient, FakeAssetRepository, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, repository, root = preview_client
    content = b"large image bytes"
    candidate = root / "images" / "brand.png"
    candidate.parent.mkdir()
    candidate.write_bytes(content)
    repository.rows["AG-IMG-20260725-000001"] = _asset(
        relative_path="images/brand.png",
        checksum=hashlib.sha256(content).hexdigest(),
    )
    generated = root / ".asset-preview-cache" / "thumbnail.webp"
    generated.parent.mkdir()
    generated.write_bytes(b"thumbnail bytes")
    monkeypatch.setattr(
        assets,
        "ensure_image_thumbnail",
        lambda source, cache_root, **kwargs: generated,
    )

    response = client.get("/api/assets/AG-IMG-20260725-000001/preview?variant=thumbnail")

    assert response.status_code == 200
    assert response.content == b"thumbnail bytes"
    assert response.headers["content-type"].startswith("image/webp")
    assert response.headers["cache-control"] == "private, max-age=86400"
