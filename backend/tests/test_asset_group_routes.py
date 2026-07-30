from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import assets
from app.main import app


class FakeMaterialLibraryRepository:
    def __init__(self) -> None:
        self.group = {
            "group_code": "AG-GRP-001",
            "title": "原分组",
            "description": None,
            "asset_codes": ["AG-IMG-001"],
            "asset_count": 1,
            "created_at": "2026-07-26T00:00:00Z",
            "updated_at": "2026-07-26T00:00:00Z",
        }
        self.archived = False

    def update_group(self, group_code: str, *, title: str, description: str | None) -> dict | None:
        if group_code != self.group["group_code"] or self.archived:
            return None
        self.group.update({"title": title, "description": description})
        return deepcopy(self.group)

    def archive_group(self, group_code: str) -> bool:
        if group_code != self.group["group_code"] or self.archived:
            return False
        self.archived = True
        return True


def test_customer_can_rename_and_archive_an_asset_group() -> None:
    repository = FakeMaterialLibraryRepository()
    app.dependency_overrides[assets.get_material_library_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            updated = client.patch(
                "/api/assets/groups/AG-GRP-001",
                json={"title": "夏季主素材", "description": "直播间常用素材"},
            )
            archived = client.delete("/api/assets/groups/AG-GRP-001")
            missing = client.delete("/api/assets/groups/AG-GRP-001")
    finally:
        app.dependency_overrides.clear()

    assert updated.status_code == 200
    assert updated.json()["title"] == "夏季主素材"
    assert updated.json()["description"] == "直播间常用素材"
    assert archived.status_code == 204
    assert missing.status_code == 404


def test_asset_group_archive_migration_preserves_history() -> None:
    sql = Path("migrations/098_asset_group_archival.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS archived_at" in sql
    assert "WHERE archived_at IS NULL" in sql
    assert "DROP TABLE" not in sql
