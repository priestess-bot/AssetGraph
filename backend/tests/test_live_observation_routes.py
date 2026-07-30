from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.auth import require_maitu_script_layout_worker
from app.api.routes.live_observations import _add_session_media_urls, get_live_observation_service, router
from app.core.config import settings
from app.services.recording_upload import StoredRecording


NOW = datetime.now(UTC)


class FakeLiveObservationService:
    def __init__(self) -> None:
        self.claim_worker_id: str | None = None
        self.import_payload: dict[str, Any] | None = None
        self.operator_retry: tuple[str, str] | None = None
        self.archived_template: tuple[str, str] | None = None

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

    def import_recording(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.import_payload = payload
        return {
            "session_code": "LR-CAP-UPLOAD-1",
            "target_code": "LR-WATCH-UPLOAD-1",
            "created_at": NOW,
        }

    def retry_analysis_run_as_operator(self, run_code: str, reason: str) -> dict[str, Any]:
        self.operator_retry = (run_code, reason)
        return {
            "id": "00000000-0000-4000-8000-000000000010",
            "analysis_run_code": run_code,
            "session_code": "LR-CAP-UPLOAD-1",
            "chunk_code": "LR-CHUNK-UPLOAD-1",
            "analysis_type": "ocr",
            "status": "queued",
            "input_fingerprint": "a" * 64,
            "strategy_revision": "live.ocr.v2",
            "parameters": {},
            "output_payload": {},
            "attempt_count": 1,
            "max_attempts": 3,
            "next_attempt_at": NOW,
            "retry_history": [],
            "created_at": NOW,
            "updated_at": NOW,
        }

    def archive_room_template(self, template_code: str, payload: Any) -> dict[str, Any]:
        self.archived_template = (template_code, payload.reason)
        return {
            "id": "00000000-0000-4000-8000-000000000011",
            "template_code": template_code,
            "name": "已停用模板",
            "template_kind": "content_strategy",
            "status": "archived",
            "projection_ready": False,
            "manual_review_required": True,
            "archived_at": NOW,
            "archive_reason": payload.reason,
            "created_at": NOW,
            "updated_at": NOW,
            "revisions": [],
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


def test_operator_can_upload_a_recording_without_platform_capture(
    client: tuple[TestClient, FakeLiveObservationService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, service = client
    monkeypatch.setattr(
        "app.api.routes.live_observations.store_recording_upload",
        lambda *_args, **_kwargs: StoredRecording(
            original_name="room.mp4",
            relative_path="uploads/aa/checksum.mp4",
            file_size=12,
            checksum_sha256="a" * 64,
            content_type="video/mp4",
            container_format="mp4",
            duration_seconds=61.5,
            media_probe={"schema_version": "file-truth-v1", "video": {"width": 1080, "height": 1920}},
        ),
    )

    response = test_client.post(
        "/api/live-research/capture-sessions/uploads",
        data={"source_room_id": "893746120", "source_room_title": "品牌夏季专场"},
        files={"file": ("room.mp4", b"video-bytes", "video/mp4")},
    )

    assert response.status_code == 201
    assert response.json()["session_code"] == "LR-CAP-UPLOAD-1"
    assert response.json()["queued_analysis_types"] == [
        "frame_sampling",
        "asr",
        "ocr",
        "layout_inference",
    ]
    assert service.import_payload is not None
    assert service.import_payload["source_room_id"] == "893746120"
    assert service.import_payload["checksum_sha256"] == "a" * 64


def test_capture_session_response_hides_internal_child_foreign_keys() -> None:
    response = _add_session_media_urls(
        {
            "session_code": "LR-CAP-1",
            "channels": [{"session_id": "internal-session", "channel_code": "LR-CH-1", "media_kind": "video"}],
            "chunks": [{"session_id": "internal-session", "chunk_code": "LR-CHUNK-1", "status": "writing"}],
            "raw_event_batches": [{"session_id": "internal-session", "batch_code": "LR-BATCH-1"}],
            "timeline": [{"session_id": "internal-session", "chunk_id": "internal-chunk", "chunk_code": "LR-CHUNK-1"}],
        }
    )

    assert "session_id" not in response["channels"][0]
    assert "session_id" not in response["chunks"][0]
    assert "session_id" not in response["raw_event_batches"][0]
    assert "session_id" not in response["timeline"][0]
    assert "chunk_id" not in response["timeline"][0]


def test_recording_upload_rejects_an_invalid_source_room_id(
    client: tuple[TestClient, FakeLiveObservationService],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/live-research/capture-sessions/uploads",
        data={"source_room_id": "room/escape", "source_room_title": "invalid"},
        files={"file": ("room.mp4", b"video-bytes", "video/mp4")},
    )
    assert response.status_code == 422
    assert service.import_payload is None


def test_operator_can_retry_one_failed_analysis_step(
    client: tuple[TestClient, FakeLiveObservationService],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/live-research/analysis-runs/LR-ANL-FAILED-1/retry",
        json={"reason": "修复模型配置后重试"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert service.operator_retry == ("LR-ANL-FAILED-1", "修复模型配置后重试")


def test_operator_can_archive_a_template_without_deleting_history(
    client: tuple[TestClient, FakeLiveObservationService],
) -> None:
    test_client, service = client
    response = test_client.post(
        "/api/live-research/room-templates/LR-TPL-1/archive",
        json={"reason": "不再用于新项目"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "archived"
    assert response.json()["archive_reason"] == "不再用于新项目"
    assert service.archived_template == ("LR-TPL-1", "不再用于新项目")


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
