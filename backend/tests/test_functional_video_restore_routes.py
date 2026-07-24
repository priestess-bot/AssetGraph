from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import functional_videos
from app.domain.errors import DomainValidationError
from app.main import app


def plan(revision: int = 2) -> dict:
    return {
        "plan_code": "VIDPLAN-001",
        "project_code": "CONTENT-001",
        "variant_code": "VAR-001",
        "video_job_code": "VIDJOB-001",
        "title": "恢复时间轴",
        "production_timeline": {"global_end_ms": 60_000, "tracks": []},
        "timeline_revision": revision,
        "render_profile": {},
        "job_status": "queued",
        "current_stage": "asset_selection",
        "progress_percent": 37,
        "error_message": None,
        "final_asset_id": None,
        "quality_report": {},
        "workflow_stages": [],
        "artifacts": [],
        "created_at": "2026-07-25T00:00:00Z",
        "updated_at": "2026-07-25T00:00:00Z",
    }


class FakeFunctionalVideoService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, str]] = []
        self.branch_calls: list[tuple[str, dict, str]] = []
        self.release_calls: list[tuple[str, str]] = []

    def create_release_candidate(self, plan_code: str, *, actor_id: str) -> dict:
        self.release_calls.append((plan_code, actor_id))
        return {
            **plan(),
            "release_code": "RELEASE-001",
            "release_snapshot_artifact_code": "ART-001",
            "release_manifest_fingerprint": "a" * 64,
            "release": {
                "release_code": "RELEASE-001",
                "status": "candidate",
                "manifest_code": "RELEASE-001-M001",
                "manifest_fingerprint": "a" * 64,
                "snapshot_artifact_code": "ART-001",
            },
        }

    def branch_plan(self, plan_code: str, payload: dict, *, actor_id: str) -> dict | None:
        if plan_code == "VIDPLAN-MISSING":
            return None
        self.branch_calls.append((plan_code, payload, actor_id))
        return {**plan(1), "plan_code": "VIDPLAN-002", "title": payload.get("title") or "恢复时间轴 - 分支"}

    def restore_timeline_revision(
        self,
        plan_code: str,
        source_revision: int,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict | None:
        if plan_code == "VIDPLAN-MISSING":
            return None
        if expected_revision != 2:
            raise DomainValidationError("VIDEO_TIMELINE_REVISION_CONFLICT", "Timeline changed since it was loaded")
        self.calls.append((plan_code, source_revision, expected_revision, actor_id))
        return plan(3)


@pytest.fixture
def client() -> tuple[TestClient, FakeFunctionalVideoService]:
    service = FakeFunctionalVideoService()
    app.dependency_overrides[functional_videos.get_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service
    app.dependency_overrides.clear()


def test_restore_timeline_revision_creates_the_next_revision(client: tuple[TestClient, FakeFunctionalVideoService]) -> None:
    test_client, service = client

    response = test_client.post(
        "/api/functional-video-plans/VIDPLAN-001/timeline-revisions/1/restore",
        json={"expected_revision": 2},
    )

    assert response.status_code == 200
    assert response.json()["timeline_revision"] == 3
    assert service.calls == [("VIDPLAN-001", 1, 2, "functional-operator")]


def test_restore_timeline_revision_reports_stale_editor_as_conflict(client: tuple[TestClient, FakeFunctionalVideoService]) -> None:
    test_client, _ = client

    response = test_client.post(
        "/api/functional-video-plans/VIDPLAN-001/timeline-revisions/1/restore",
        json={"expected_revision": 1},
    )

    assert response.status_code == 409


def test_branch_video_plan_creates_a_new_queued_plan(client: tuple[TestClient, FakeFunctionalVideoService]) -> None:
    test_client, service = client

    response = test_client.post("/api/functional-video-plans/VIDPLAN-001/branch", json={"title": "剪辑调整"})

    assert response.status_code == 201
    assert response.json()["plan_code"] == "VIDPLAN-002"
    assert service.branch_calls == [("VIDPLAN-001", {"title": "剪辑调整"}, "functional-operator")]


def test_create_video_release_candidate(client: tuple[TestClient, FakeFunctionalVideoService]) -> None:
    test_client, service = client

    response = test_client.post("/api/functional-video-plans/VIDPLAN-001/release-candidate")

    assert response.status_code == 200
    assert response.json()["release"]["manifest_code"] == "RELEASE-001-M001"
    assert service.release_calls == [("VIDPLAN-001", "functional-operator")]
