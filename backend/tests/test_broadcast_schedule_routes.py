from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import broadcast_schedules


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _schedule(**overrides: Any) -> dict[str, Any]:
    return {
        "schedule_code": "SCHEDULE-001",
        "revision_number": 1,
        "title": "Evening product session",
        "release_code": "RELEASE-001",
        "release_fingerprint_sha256": "a" * 64,
        "target_account_id": "account-1",
        "target_room_id": "room-1",
        "platform": "douyin",
        "timezone": "Asia/Shanghai",
        "starts_at": datetime(2026, 7, 26, 10, tzinfo=UTC),
        "ends_at": datetime(2026, 7, 26, 11, tzinfo=UTC),
        "owner": "operator-a",
        "promotion_dependencies": ["campaign-1"],
        "inventory_dependencies": ["inventory-1"],
        "conflict_strategy": "manual_reschedule",
        "stop_conditions": ["inventory unavailable"],
        "status": "validated",
        "validation_result": {"state": "passed", "go_live_capability": "disabled"},
        "fingerprint_sha256": "b" * 64,
        "created_at": NOW,
        **overrides,
    }


class FakeBroadcastScheduleService:
    def __init__(self) -> None:
        self.create_payload: dict[str, Any] | None = None
        self.validated: list[str] = []

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.create_payload = payload
        return _schedule(**payload, status="draft", release_fingerprint_sha256=None)

    @staticmethod
    def list() -> list[dict[str, Any]]:
        return [_schedule()]

    @staticmethod
    def get(code: str) -> dict[str, Any] | None:
        return _schedule(schedule_code=code) if code != "SCHEDULE-MISSING" else None

    def validate(self, code: str) -> dict[str, Any] | None:
        self.validated.append(code)
        return _schedule(schedule_code=code, revision_number=2) if code != "SCHEDULE-MISSING" else None


@pytest.fixture
def client() -> tuple[TestClient, FakeBroadcastScheduleService]:
    service = FakeBroadcastScheduleService()
    app = FastAPI()
    app.include_router(broadcast_schedules.router, prefix="/api")
    app.dependency_overrides[broadcast_schedules.service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service


def _payload() -> dict[str, Any]:
    return {
        "title": "Evening product session",
        "release_code": "RELEASE-001",
        "target_account_id": "account-1",
        "target_room_id": "room-1",
        "platform": "douyin",
        "timezone": "Asia/Shanghai",
        "starts_at": "2026-07-26T10:00:00+00:00",
        "ends_at": "2026-07-26T11:00:00+00:00",
        "owner": "operator-a",
        "promotion_dependencies": ["campaign-1"],
        "inventory_dependencies": ["inventory-1"],
        "conflict_strategy": "manual_reschedule",
        "stop_conditions": ["inventory unavailable"],
    }


def test_schedule_routes_create_and_validate_local_plan(
    client: tuple[TestClient, FakeBroadcastScheduleService],
) -> None:
    test_client, service = client

    created = test_client.post("/api/broadcast-schedules", json=_payload())
    validated = test_client.post("/api/broadcast-schedules/SCHEDULE-001/validate")

    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert service.create_payload is not None
    assert service.create_payload["target_room_id"] == "room-1"
    assert validated.status_code == 200
    assert validated.json()["revision_number"] == 2
    assert service.validated == ["SCHEDULE-001"]


def test_schedule_route_rejects_invalid_window_and_missing_schedule(
    client: tuple[TestClient, FakeBroadcastScheduleService],
) -> None:
    test_client, _service = client
    invalid_payload = {**_payload(), "ends_at": "2026-07-26T09:00:00+00:00"}

    invalid = test_client.post("/api/broadcast-schedules", json=invalid_payload)
    missing = test_client.post("/api/broadcast-schedules/SCHEDULE-MISSING/validate")

    assert invalid.status_code == 422
    assert missing.status_code == 404
