from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app


class FakeMaterialLibraryRepository:
    def __init__(self) -> None:
        self.last_update: dict | None = None

    def update_asset_rights(
        self,
        asset_code: str,
        *,
        rights_status: str,
        rights_note: str,
        actor: str,
    ) -> dict | None:
        if asset_code != "AG-IMG-001":
            return None
        self.last_update = {
            "rights_status": rights_status,
            "rights_note": rights_note,
            "actor": actor,
        }
        return {
            "id": "asset-id",
            "asset_code": asset_code,
            "asset_type": "IMG",
            "title": "品牌主图",
            "original_filename": "brand.png",
            "status": "stored",
            "media_kind": "image",
            "material_roles": ["background"],
            "execution_capability": "local_only",
            "rights_status": rights_status,
            "rights_note": rights_note,
            "rights_updated_by": actor,
        }


def test_customer_can_record_a_minimal_asset_usage_basis() -> None:
    repository = FakeMaterialLibraryRepository()
    app.dependency_overrides[assets.get_material_library_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            response = client.patch(
                "/api/assets/AG-IMG-001/rights",
                json={"status": "approved", "note": "品牌自有素材，仅用于本项目"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["rights_status"] == "approved"
    assert repository.last_update == {
        "rights_status": "approved",
        "rights_note": "品牌自有素材，仅用于本项目",
        "actor": "functional-operator",
    }


def test_asset_rights_migration_defaults_unknown_materials_to_pending() -> None:
    sql = Path("migrations/099_asset_rights_status.sql").read_text(encoding="utf-8")

    assert "DEFAULT 'pending'" in sql
    assert "'approved', 'restricted', 'revoked'" in sql
