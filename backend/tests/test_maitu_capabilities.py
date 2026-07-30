from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.functional_live_rooms import router
from app.services.maitu_capabilities import maitu_capability_matrix


def test_maitu_capability_matrix_is_deterministic_and_conservative() -> None:
    first = maitu_capability_matrix()
    second = maitu_capability_matrix()

    assert first == second
    assert len(first["contract_fingerprint"]) == 64
    assert first["can_execute_draft"] is False
    assert first["manual_handoff_available"] is True

    capabilities = {item["key"]: item for item in first["capabilities"]}
    assert capabilities["read_room"]["status"] == "manual_only"
    assert capabilities["create_scene"]["status"] == "manual_only"
    assert capabilities["verify_reload_persistence"]["status"] == "manual_only"
    assert capabilities["create_live_room"]["status"] == "unsupported"
    assert capabilities["schedule"]["status"] == "unsupported"
    assert capabilities["go_live"]["status"] == "unsupported"
    assert "read_room" in first["unverified_required_capabilities"]
    assert "create_scene" in first["unverified_required_capabilities"]


def test_maitu_capability_route_is_not_captured_as_a_plan_code() -> None:
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/functional-live-room-plans/maitu-capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "maitu-capability-matrix.v1"
    assert body["can_execute_draft"] is False
    assert body["capabilities"][-1]["key"] == "go_live"
