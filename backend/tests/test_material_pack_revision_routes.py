from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app
from app.repositories.material_library import MaterialLibraryValidationError


class FakeMaterialLibraryRepository:
    def __init__(self) -> None:
        self.batch_updates: list[dict] = []
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
        self.constraint_revisions = [
            {
                "profile_code": "AG-CP-001",
                "asset_code": "AG-IMG-001",
                "revision_number": 2,
                "constraints": [{"kind": "table_surface", "hard": True, "parameters": {"name": "table_surface"}}],
                "fingerprint_sha256": "c" * 64,
                "created_at": "2026-07-25T00:00:00Z",
            },
            {
                "profile_code": "AG-CP-001",
                "asset_code": "AG-IMG-001",
                "revision_number": 1,
                "constraints": [],
                "fingerprint_sha256": "a" * 64,
                "created_at": "2026-07-24T00:00:00Z",
            },
        ]
        self.room_override_promotion: dict | None = None

    def update_asset_classifications(
        self,
        asset_codes: list[str],
        *,
        media_kind: str | None,
        material_roles: list[str],
        execution_capability: str,
    ) -> list[dict]:
        self.batch_updates.append(
            {
                "asset_codes": asset_codes,
                "media_kind": media_kind,
                "material_roles": material_roles,
                "execution_capability": execution_capability,
            }
        )
        return [
            {
                "id": f"id-{asset_code}",
                "asset_code": asset_code,
                "asset_type": "IMG",
                "title": asset_code,
                "original_filename": f"{asset_code}.png",
                "media_kind": media_kind,
                "material_roles": material_roles,
                "execution_capability": execution_capability,
            }
            for asset_code in asset_codes
        ]

    def list_pack_revisions(self, pack_code: str) -> list[dict]:
        return deepcopy(self.revisions) if pack_code == self.pack["pack_code"] else []

    def preview_published_pack_resolution(
        self, pack_codes: list[str], *, role_modes: dict[str, str] | None = None
    ) -> dict:
        return {
            "schema_version": "material-pack-resolution.v1",
            "pack_refs": [{"pack_code": code, "pack_kind": "total", "revision_number": 1, "fingerprint_sha256": "a" * 64} for code in pack_codes],
            "resolved_asset_codes": ["AG-IMG-001"],
            "entry_requirements": [],
            "material_rules": [],
            "conflicts": [],
            "fingerprint_sha256": "b" * 64,
            "role_modes": role_modes or {},
        }

    def list_constraint_profile_revisions(self, asset_code: str) -> list[dict]:
        return deepcopy(self.constraint_revisions) if asset_code == "AG-IMG-001" else []

    def promote_room_constraint_override(
        self,
        asset_code: str,
        *,
        plan_code: str,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> dict | None:
        if asset_code == "AG-IMG-MISSING":
            return None
        self.room_override_promotion = {
            "asset_code": asset_code,
            "plan_code": plan_code,
            "expected_revision": expected_revision,
            "actor": actor,
            "reason": reason,
        }
        return {
            "profile_code": "AG-CP-001",
            "asset_code": asset_code,
            "revision_number": expected_revision + 1,
            "constraints": [{"kind": "allowed_region", "hard": True, "parameters": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.4}}],
            "fingerprint_sha256": "d" * 64,
            "created_by": actor,
            "change_reason": reason,
            "source_plan_code": plan_code,
            "source_profile_revision": expected_revision,
            "source_room_override": {"geometry": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.4}},
            "created_at": "2026-07-25T02:00:00Z",
        }

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


def test_batch_classification_deduplicates_targets_and_rejects_an_empty_set(client: TestClient) -> None:
    updated = client.patch(
        "/api/assets/batch-classification",
        json={
            "asset_codes": ["AG-IMG-001", "AG-IMG-001", "AG-IMG-002"],
            "media_kind": "image",
            "material_roles": ["background", "product_display"],
            "execution_capability": "local_only",
        },
    )
    empty = client.patch(
        "/api/assets/batch-classification",
        json={
            "asset_codes": ["  "],
            "media_kind": "image",
            "material_roles": [],
            "execution_capability": "local_only",
        },
    )

    assert updated.status_code == 200
    assert [row["asset_code"] for row in updated.json()] == ["AG-IMG-001", "AG-IMG-002"]
    assert updated.json()[0]["material_roles"] == ["background", "product_display"]
    assert empty.status_code == 422


def test_material_pack_revision_history_returns_not_found_for_unknown_pack(client: TestClient) -> None:
    response = client.get("/api/assets/material-packs/AG-PACK-MISSING/revisions")

    assert response.status_code == 404


def test_material_pack_resolve_accepts_explicit_role_composition_modes(client: TestClient) -> None:
    response = client.post(
        "/api/assets/material-packs/resolve",
        json={"pack_codes": ["AG-PACK-001"], "role_modes": {"background": "replace"}},
    )

    assert response.status_code == 200
    assert response.json()["pack_refs"][0]["pack_kind"] == "total"
    assert response.json()["role_modes"] == {"background": "replace"}

    invalid = client.post(
        "/api/assets/material-packs/resolve",
        json={"pack_codes": ["AG-PACK-001"], "role_modes": {"background": "ignore"}},
    )
    assert invalid.status_code == 422


def test_constraint_profile_revisions_are_immutable_and_listed_newest_first(client: TestClient) -> None:
    listed = client.get("/api/assets/AG-IMG-001/constraint-profile/revisions")
    missing = client.get("/api/assets/AG-IMG-MISSING/constraint-profile/revisions")

    assert listed.status_code == 200
    assert [row["revision_number"] for row in listed.json()] == [2, 1]
    assert listed.json()[0]["constraints"][0]["kind"] == "table_surface"
    assert missing.status_code == 404


def test_room_override_promotion_requires_a_frozen_plan_and_revision(client: TestClient) -> None:
    promoted = client.post(
        "/api/assets/AG-IMG-001/constraint-profile/promote-room-override",
        json={
            "plan_code": "LIVE-PLAN-001",
            "expected_revision": 2,
            "actor": "operator-1",
            "reason": "The product placement is reusable across rooms.",
        },
    )
    blank_reason = client.post(
        "/api/assets/AG-IMG-001/constraint-profile/promote-room-override",
        json={"plan_code": "LIVE-PLAN-001", "expected_revision": 2, "actor": "operator-1", "reason": "  "},
    )

    assert promoted.status_code == 200
    assert promoted.json()["source_plan_code"] == "LIVE-PLAN-001"
    assert promoted.json()["source_profile_revision"] == 2
    assert blank_reason.status_code == 422
