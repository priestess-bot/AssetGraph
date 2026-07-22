from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.auth import require_maitu_script_layout_worker
from app.api.routes.live_observations import get_live_observation_service, router
from app.core.config import settings


NOW = datetime.now(UTC)


class FakeLiveObservationService:
    def __init__(self) -> None:
        self.claim_worker_id: str | None = None

    def overview(self) -> dict[str, int]:
        return {"watch_targets_total": 1, "watch_targets_enabled": 1}

    def claim_watch_target(self, payload: Any) -> dict[str, Any]:
        self.claim_worker_id = payload.worker_id
        return {
            "id": "00000000-0000-4000-8000-000000000001",
            "target_code": "LR-WATCH-20260720-000001",
            "platform": "douyin",
            "room_url": "https://live.douyin.com/123456",
            "canonical_room_id": "123456",
            "display_name": "research",
            "recorder_engine": "streamcap",
            "preferred_quality": "720p",
            "status": "enabled",
            "poll_interval_seconds": 180,
            "retention_days": 30,
            "next_check_at": NOW,
            "last_observed_at": NOW,
            "last_live_at": None,
            "last_capture_session_code": None,
            "consecutive_failures": 0,
            "last_error_code": None,
            "last_error_message": None,
            "metadata": {},
            "lease_active": True,
            "claim_token": "00000000-0000-4000-8000-000000000002",
            "lease_version": 1,
            "lease_expires_at": NOW + timedelta(seconds=120),
            "created_at": NOW,
            "updated_at": NOW,
        }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeLiveObservationService]:
    service = FakeLiveObservationService()
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_live_observation_service] = lambda: service
    monkeypatch.setattr(
        settings,
        "maitu_script_layout_worker_token",
        SecretStr("live-research-test-worker-secret"),
    )
    return TestClient(application), service


def test_public_overview_does_not_require_worker_auth(
    client: tuple[TestClient, FakeLiveObservationService],
) -> None:
    test_client, _service = client
    response = test_client.get("/api/live-research/overview")
    assert response.status_code == 200
    assert response.json()["watch_targets_total"] == 1


def test_worker_routes_require_bearer_and_matching_worker_identity(
    client: tuple[TestClient, FakeLiveObservationService],
) -> None:
    test_client, service = client
    path = "/api/live-research/worker/watch-target-claims"
    payload = {"worker_id": "worker-a", "lease_seconds": 120}

    assert test_client.post(path, json=payload).status_code == 401
    wrong_identity = test_client.post(
        path,
        json=payload,
        headers={
            "Authorization": "Bearer live-research-test-worker-secret",
            "X-AssetGraph-Worker-ID": "worker-b",
        },
    )
    assert wrong_identity.status_code == 403
    accepted = test_client.post(
        path,
        json=payload,
        headers={
            "Authorization": "Bearer live-research-test-worker-secret",
            "X-AssetGraph-Worker-ID": "worker-a",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["preferred_quality"] == "720p"
    assert service.claim_worker_id == "worker-a"


def test_every_worker_route_declares_the_shared_worker_auth_dependency() -> None:
    worker_routes = [
        route for route in router.routes if "/worker/" in getattr(route, "path", "")
    ]
    assert worker_routes
    for route in worker_routes:
        dependencies = [dependency.call for dependency in route.dependant.dependencies]
        assert require_maitu_script_layout_worker in dependencies, route.path


def test_no_raw_event_content_get_route_exists() -> None:
    exposed = [
        (route.path, set(route.methods or []))
        for route in router.routes
        if "raw-event" in getattr(route, "path", "")
    ]
    assert exposed
    assert all("GET" not in methods for _path, methods in exposed)


def test_analysis_retry_is_worker_bound(
    client: tuple[TestClient, FakeLiveObservationService],
) -> None:
    test_client, _service = client
    response = test_client.post(
        "/api/live-research/worker/analysis-runs/LR-ANL-1/retry",
        json={"worker_id": "worker-a", "reason": "credentials configured"},
        headers={
            "Authorization": "Bearer live-research-test-worker-secret",
            "X-AssetGraph-Worker-ID": "worker-b",
        },
    )
    assert response.status_code == 403
