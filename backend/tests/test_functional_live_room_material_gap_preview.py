from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import functional_live_rooms
from app.main import app
from app.services.functional_live_rooms import FunctionalLiveRoomService


class _FakeContent:
    def get_detail(self, project_code: str) -> dict:
        assert project_code == "CONTENT-001"
        return {
            "project_code": project_code,
            "revision_number": 4,
            "generated": True,
            "shot_list": {
                "revision_number": 7,
                "shots": [
                    {
                        "shot_code": "SHOT-001",
                        "scene_type": "opening",
                        "material_role_requirements": ["background"],
                    }
                ],
            },
        }


class _FakeMaterials:
    def preview_published_pack_resolution(self, pack_codes: list[str], *, role_modes: dict[str, str]) -> dict:
        assert pack_codes == []
        assert role_modes == {"background": "replace"}
        return {
            "resolved_asset_codes": [],
            "material_rules": [],
            "conflicts": [],
            "fingerprint_sha256": "f" * 64,
        }

    def preview_selection(self, *, role: str, carrier_kind: str) -> dict:
        assert (role, carrier_kind) == ("background", "live_room")
        return {"candidates": [{"asset_code": "AG-IMG-ALTERNATIVE"}]}


def _service() -> FunctionalLiveRoomService:
    service = object.__new__(FunctionalLiveRoomService)
    service.content = _FakeContent()
    service.materials = _FakeMaterials()
    service._selected_assets = lambda asset_codes, group_codes: [
        {
            "asset_code": "AG-IMG-SELECTED",
            "material_roles": ["background"],
            "execution_capability": "maitu_bound",
        }
    ]
    return service


def test_preview_material_gaps_uses_compiler_replacement_rules_and_freezes_provenance() -> None:
    result = _service().preview_material_gaps(
        {
            "project_code": "CONTENT-001",
            "asset_codes": ["AG-IMG-SELECTED"],
            "group_codes": [],
            "material_pack_codes": [],
            "material_role_modes": {"background": "replace"},
        }
    )

    assert result["checked_asset_codes"] == ["AG-IMG-SELECTED"]
    assert len(result["gaps"]) == 1
    gap = result["gaps"][0]
    assert gap["role"] == "background"
    assert gap["required_shot_codes"] == ["SHOT-001"]
    assert gap["alternative_asset_codes"] == ["AG-IMG-ALTERNATIVE"]
    assert gap["create_payload"]["gap_type"] == "role_coverage"
    assert gap["create_payload"]["source_context"] == {
        "schema_version": "functional-live-room-material-gap-preview.v1",
        "diagnostic_key": gap["diagnostic_key"],
        "project_code": "CONTENT-001",
        "project_revision_number": 4,
        "shot_list_revision_number": 7,
    }


def test_preview_material_gaps_route_validates_and_returns_diagnostics() -> None:
    class _RouteService:
        def preview_material_gaps(self, payload: dict) -> dict:
            assert payload["project_code"] == "CONTENT-001"
            return {
                "project_code": "CONTENT-001",
                "project_revision_number": 4,
                "shot_list_revision_number": 7,
                "checked_asset_codes": [],
                "gaps": [
                    {
                        "diagnostic_key": "a" * 64,
                        "role": "background",
                        "title": "缺少可执行 background 素材",
                        "severity": "high",
                        "gap_type": "role_coverage",
                        "required_shot_codes": ["SHOT-001"],
                        "missing_occurrences": 1,
                        "selection_mode": "append",
                        "alternative_asset_codes": ["AG-IMG-ALTERNATIVE"],
                        "create_payload": {
                            "title": "缺少可执行 background 素材",
                            "role": "background",
                            "severity": "high",
                            "gap_type": "role_coverage",
                            "specification": {},
                            "source_context": {},
                            "impact_summary": "test",
                            "alternative_asset_codes": ["AG-IMG-ALTERNATIVE"],
                        },
                    }
                ],
            }

    app.dependency_overrides[functional_live_rooms.get_service] = _RouteService
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/functional-live-room-plans/material-gap-preview",
                json={
                    "project_code": "CONTENT-001",
                    "asset_codes": [],
                    "group_codes": [],
                    "material_pack_codes": [],
                    "material_role_modes": {},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["gaps"][0]["diagnostic_key"] == "a" * 64
