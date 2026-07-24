from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app
from app.repositories.material_library import MaterialLibraryValidationError


class FakeMaterialLibraryRepository:
    def __init__(self) -> None:
        self.pack = {
            "pack_code": "AG-PACK-001",
            "title": "背景素材包",
            "role": "background",
            "description": None,
            "revision_number": 1,
            "status": "published",
            "fingerprint_sha256": "a" * 64,
            "entries": [
                {
                    "selection_kind": "group",
                    "selection_code": "AG-GRP-001",
                    "mode": "required",
                    "min_occurrences": 1,
                    "max_occurrences": None,
                }
            ],
            "resolved_asset_codes": ["AG-IMG-001"],
            "created_at": "2026-07-25T00:00:00Z",
            "updated_at": "2026-07-25T00:00:00Z",
        }
        self.revisions = [
            {
                "revision_number": 1,
                "entries": deepcopy(self.pack["entries"]),
                "fingerprint_sha256": "a" * 64,
                "created_at": "2026-07-25T00:00:00Z",
            }
        ]

    def list_pack_revisions(self, pack_code: str) -> list[dict]:
        return deepcopy(self.revisions) if pack_code == self.pack["pack_code"] else []

    def create_pack_revision(self, pack_code: str, *, expected_revision: int, entries: list[dict]) -> dict | None:
        if pack_code != self.pack["pack_code"]:
            return None
        if expected_revision != self.pack["revision_number"]:
            raise MaterialLibraryValidationError("MATERIAL_PACK_REVISION_CONFLICT: current revision changed")
        self.pack = {
            **self.pack,
            "revision_number": expected_revision + 1,
            "status": "draft",
            "entries": deepcopy(entries),
            "fingerprint_sha256": "b" * 64,
        }
        self.revisions.insert(
            0,
            {
                "revision_number": self.pack["revision_number"],
                "entries": deepcopy(entries),
                "fingerprint_sha256": self.pack["fingerprint_sha256"],
                "created_at": "2026-07-25T01:00:00Z",
            },
        )
        return deepcopy(self.pack)


@pytest.fixture
def client() -> TestClient:
    repository = FakeMaterialLibraryRepository()
    app.dependency_overrides[assets.get_material_library_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_material_pack_revisions_are_listed_and_create_a_new_draft(client: TestClient) -> None:
    listed = client.get("/api/assets/material-packs/AG-PACK-001/revisions")

    assert listed.status_code == 200
    assert listed.json()[0]["revision_number"] == 1

    created = client.post(
        "/api/assets/material-packs/AG-PACK-001/revisions",
        json={
            "expected_revision": 1,
            "entries": [
                {
                    "selection_kind": "asset",
                    "selection_code": "AG-IMG-002",
                    "mode": "optional",
                    "min_occurrences": 0,
                }
            ],
        },
    )

    assert created.status_code == 201
    assert created.json()["revision_number"] == 2
    assert created.json()["status"] == "draft"

    conflict = client.post(
        "/api/assets/material-packs/AG-PACK-001/revisions",
        json={
            "expected_revision": 1,
            "entries": [
                {
                    "selection_kind": "asset",
                    "selection_code": "AG-IMG-003",
                    "mode": "optional",
                    "min_occurrences": 0,
                }
            ],
        },
    )

    assert conflict.status_code == 409
    assert "MATERIAL_PACK_REVISION_CONFLICT" in conflict.json()["detail"]


def test_material_pack_revision_history_returns_not_found_for_unknown_pack(client: TestClient) -> None:
    response = client.get("/api/assets/material-packs/AG-PACK-MISSING/revisions")

    assert response.status_code == 404
