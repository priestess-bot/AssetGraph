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
        self.create_calls: list[dict] = []

    def create_plan(self, payload: dict, *, actor_id: str) -> dict:
        self.create_calls.append({**payload, "actor_id": actor_id})
        return plan(1)

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


def test_create_video_plan_accepts_a_fixed_live_room_source(client: tuple[TestClient, FakeFunctionalVideoService]) -> None:
    test_client, service = client

    response = test_client.post(
        "/api/functional-video-plans",
        json={"live_room_plan_code": "LIVEPLAN-001", "target_duration_seconds": 55},
    )

    assert response.status_code == 201
    assert service.create_calls == [
        {
            "project_code": None,
            "live_room_plan_code": "LIVEPLAN-001",
            "title": None,
            "target_duration_seconds": 55,
            "visual_asset_codes": [],
            "visual_group_codes": [],
            "visual_material_pack_codes": [],
            "product_sticker_asset_code": None,
            "background_music_asset_code": None,
            "background_music_gain_db": -18.0,
            "actor_id": "functional-operator",
        }
    ]


def test_create_video_plan_accepts_up_to_six_explicit_visual_assets(
    client: tuple[TestClient, FakeFunctionalVideoService],
) -> None:
    test_client, service = client

    response = test_client.post(
        "/api/functional-video-plans",
        json={
            "project_code": "CONTENT-001",
            "target_duration_seconds": 55,
            "visual_asset_codes": ["AG-VID-000001", "AG-VID-000002"],
        },
    )

    assert response.status_code == 201
    assert service.create_calls == [
        {
            "project_code": "CONTENT-001",
            "live_room_plan_code": None,
            "title": None,
            "target_duration_seconds": 55,
            "visual_asset_codes": ["AG-VID-000001", "AG-VID-000002"],
            "visual_group_codes": [],
            "visual_material_pack_codes": [],
            "product_sticker_asset_code": None,
            "background_music_asset_code": None,
            "background_music_gain_db": -18.0,
            "actor_id": "functional-operator",
        }
    ]


def test_create_video_plan_accepts_group_and_published_pack_sources(
    client: tuple[TestClient, FakeFunctionalVideoService],
) -> None:
    test_client, service = client

    response = test_client.post(
        "/api/functional-video-plans",
        json={
            "project_code": "CONTENT-001",
            "target_duration_seconds": 55,
            "visual_group_codes": ["AG-GRP-001"],
            "visual_material_pack_codes": ["AG-PACK-001"],
        },
    )

    assert response.status_code == 201
    assert service.create_calls == [
        {
            "project_code": "CONTENT-001",
            "live_room_plan_code": None,
            "title": None,
            "target_duration_seconds": 55,
            "visual_asset_codes": [],
            "visual_group_codes": ["AG-GRP-001"],
            "visual_material_pack_codes": ["AG-PACK-001"],
            "product_sticker_asset_code": None,
            "background_music_asset_code": None,
            "background_music_gain_db": -18.0,
            "actor_id": "functional-operator",
        }
    ]


def test_create_video_plan_accepts_a_local_product_sticker(
    client: tuple[TestClient, FakeFunctionalVideoService],
) -> None:
    test_client, service = client

    response = test_client.post(
        "/api/functional-video-plans",
        json={
            "project_code": "CONTENT-001",
            "target_duration_seconds": 55,
            "product_sticker_asset_code": "AG-IMG-000001",
        },
    )

    assert response.status_code == 201
    assert service.create_calls == [
        {
            "project_code": "CONTENT-001",
            "live_room_plan_code": None,
            "title": None,
            "target_duration_seconds": 55,
            "visual_asset_codes": [],
            "visual_group_codes": [],
            "visual_material_pack_codes": [],
            "product_sticker_asset_code": "AG-IMG-000001",
            "background_music_asset_code": None,
            "background_music_gain_db": -18.0,
            "actor_id": "functional-operator",
        }
    ]
