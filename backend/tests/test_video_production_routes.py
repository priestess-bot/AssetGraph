from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import video_productions
from app.core.config import settings
from app.main import app
from app.repositories.video_productions import VideoProductionRetryConflictError
from app.schemas.video_productions import VIDEO_PRODUCTION_STAGES


NOW = datetime(2026, 7, 17, tzinfo=UTC)


class FakeVideoProductionRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.artifact_rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.last_list: dict[str, Any] | None = None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = "AG-VJOB-20260717-000001"
        row = _job(code=code, topic=payload["topic"])
        row["preset_code"] = payload["preset_code"]
        row["target_duration_seconds"] = payload["target_duration_seconds"]
        self.rows[code] = row
        return row

    def list(self, *, status: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
        self.last_list = {"status": status, "limit": limit, "offset": offset}
        rows = list(self.rows.values())
        if status:
            rows = [row for row in rows if row["status"] == status]
        return rows[offset : offset + limit]

    def get_by_code(self, job_code: str) -> dict[str, Any] | None:
        return self.rows.get(job_code)

    def retry(self, job_code: str) -> dict[str, Any] | None:
        row = self.rows.get(job_code)
        if row is None:
            return None
        if row["status"] != "failed":
            raise VideoProductionRetryConflictError("Only failed video production jobs can be retried")
        row["status"] = "queued"
        row["attempt"] += 1
        row["error_code"] = None
        row["error_message"] = None
        return row

    def get_artifact(self, job_code: str, artifact_key: str) -> dict[str, Any] | None:
        return self.artifact_rows.get((job_code, artifact_key))


def _job(*, code: str, topic: str, status: str = "queued") -> dict[str, Any]:
    stages = [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "stage_name": stage_name,
            "stage_order": index,
            "status": "pending",
            "attempt": 1,
            "input_payload": {},
            "output_payload": {},
            "error_code": None,
            "error_message": None,
            "started_at": None,
            "completed_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        for index, stage_name in enumerate(VIDEO_PRODUCTION_STAGES, start=1)
    ]
    return {
        "id": "10000000-0000-0000-0000-000000000001",
        "job_code": code,
        "topic": topic,
        "preset_code": "zhangyu_wine_demo_v1",
        "target_duration_seconds": 70,
        "status": status,
        "current_stage": "brief_generation",
        "progress_percent": 0,
        "attempt": 1,
        "story_brief": {},
        "script": {},
        "shot_list": {},
        "asset_plan": {},
        "quality_report": {},
        "final_asset_id": None,
        "error_code": "render_failed" if status == "failed" else None,
        "error_message": "render failed" if status == "failed" else None,
        "started_at": None,
        "completed_at": NOW if status == "failed" else None,
        "created_at": NOW,
        "updated_at": NOW,
        "stages": stages,
        "artifacts": [],
    }


@pytest.fixture
def client(tmp_path: Path) -> tuple[TestClient, FakeVideoProductionRepository, Path]:
    repository = FakeVideoProductionRepository()
    previous_root = settings.video_production_root
    settings.video_production_root = tmp_path
    app.dependency_overrides[video_productions.get_video_production_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client, repository, tmp_path
    app.dependency_overrides.pop(video_productions.get_video_production_repository, None)
    settings.video_production_root = previous_root


def test_create_video_production_returns_accepted_job_with_eight_stages(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, _repository, _root = client

    response = test_client.post("/api/video-productions", json={"topic": " 夏日聚餐选酒 "})

    assert response.status_code == 202
    body = response.json()
    assert body["job_code"] == "AG-VJOB-20260717-000001"
    assert body["topic"] == "夏日聚餐选酒"
    assert body["target_duration_seconds"] == 55
    assert [stage["stage_name"] for stage in body["stages"]] == list(VIDEO_PRODUCTION_STAGES)


def test_create_video_production_rejects_unknown_fields_and_invalid_duration(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, _repository, _root = client

    response = test_client.post(
        "/api/video-productions",
        json={"topic": "demo", "target_duration_seconds": 5, "unsafe": "ignored?"},
    )

    assert response.status_code == 422

    unknown_preset = test_client.post(
        "/api/video-productions",
        json={"topic": "demo", "preset_code": "unregistered-preset"},
    )
    assert unknown_preset.status_code == 422


def test_list_and_get_video_productions(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, repository, _root = client
    repository.rows["AG-VJOB-20260717-000001"] = _job(
        code="AG-VJOB-20260717-000001", topic="demo"
    )

    list_response = test_client.get("/api/video-productions?status=queued&limit=10&offset=0")
    detail_response = test_client.get("/api/video-productions/AG-VJOB-20260717-000001")
    missing_response = test_client.get("/api/video-productions/AG-VJOB-20260717-999999")

    assert list_response.status_code == 200
    assert repository.last_list == {"status": "queued", "limit": 10, "offset": 0}
    assert detail_response.status_code == 200
    assert detail_response.json()["story_brief"] == {}
    assert missing_response.status_code == 404


def test_retry_only_accepts_failed_jobs(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, repository, _root = client
    repository.rows["AG-VJOB-20260717-000001"] = _job(
        code="AG-VJOB-20260717-000001", topic="demo"
    )
    repository.rows["AG-VJOB-20260717-000002"] = _job(
        code="AG-VJOB-20260717-000002", topic="failed demo", status="failed"
    )

    conflict = test_client.post("/api/video-productions/AG-VJOB-20260717-000001/retry")
    accepted = test_client.post("/api/video-productions/AG-VJOB-20260717-000002/retry")

    assert conflict.status_code == 409
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    assert accepted.json()["attempt"] == 2


def test_artifact_download_supports_full_standard_and_suffix_ranges(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, repository, root = client
    content = b"0123456789"
    artifact_path = root / "AG-VJOB-20260717-000001" / "attempt-1" / "final.mp4"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(content)
    repository.artifact_rows[("AG-VJOB-20260717-000001", "video")] = {
        "artifact_key": "video",
        "relative_path": "AG-VJOB-20260717-000001/attempt-1/final.mp4",
        "mime_type": "video/mp4",
        "file_size": len(content),
        "checksum_sha256": hashlib.sha256(content).hexdigest(),
    }

    full = test_client.get("/api/video-productions/AG-VJOB-20260717-000001/artifacts/video")
    partial = test_client.get(
        "/api/video-productions/AG-VJOB-20260717-000001/artifacts/video",
        headers={"Range": "bytes=2-5"},
    )
    suffix = test_client.get(
        "/api/video-productions/AG-VJOB-20260717-000001/artifacts/video",
        headers={"Range": "bytes=-3"},
    )

    assert full.status_code == 200
    assert full.content == content
    assert full.headers["accept-ranges"] == "bytes"
    assert partial.status_code == 206
    assert partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/10"
    assert suffix.status_code == 206
    assert suffix.content == b"789"


def test_artifact_download_rejects_invalid_range_and_escaped_path(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, repository, root = client
    video_path = root / "AG-VJOB-20260717-000001" / "attempt-1" / "final.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    repository.artifact_rows[("AG-VJOB-20260717-000001", "video")] = {
        "artifact_key": "video",
        "relative_path": "AG-VJOB-20260717-000001/attempt-1/final.mp4",
        "mime_type": "video/mp4",
        "file_size": 5,
        "checksum_sha256": hashlib.sha256(b"video").hexdigest(),
    }
    outside = root.parent / "secret.json"
    outside.write_text("secret", encoding="utf-8")
    repository.artifact_rows[("AG-VJOB-20260717-000001", "script")] = {
        "artifact_key": "script",
        "relative_path": "../secret.json",
        "mime_type": "application/json",
        "file_size": 6,
    }

    invalid_range = test_client.get(
        "/api/video-productions/AG-VJOB-20260717-000001/artifacts/video",
        headers={"Range": "bytes=99-100"},
    )
    escaped = test_client.get(
        "/api/video-productions/AG-VJOB-20260717-000001/artifacts/script"
    )
    unknown_key = test_client.get(
        "/api/video-productions/AG-VJOB-20260717-000001/artifacts/not-allowed"
    )

    assert invalid_range.status_code == 416
    assert invalid_range.headers["content-range"] == "bytes */5"
    assert escaped.status_code == 404
    assert unknown_key.status_code == 404


def test_artifact_download_rejects_cross_job_path_and_same_size_digest_change(
    client: tuple[TestClient, FakeVideoProductionRepository, Path],
) -> None:
    test_client, repository, root = client
    job_code = "AG-VJOB-20260717-000001"
    other_job_code = "AG-VJOB-20260717-000002"
    original = b"original-video"
    video_path = root / job_code / "attempt-1" / "final.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(original)
    repository.artifact_rows[(job_code, "video")] = {
        "artifact_key": "video",
        "relative_path": f"{job_code}/attempt-1/final.mp4",
        "mime_type": "video/mp4",
        "file_size": len(original),
        "checksum_sha256": hashlib.sha256(original).hexdigest(),
    }

    other_path = root / other_job_code / "attempt-1" / "script.json"
    other_path.parent.mkdir(parents=True)
    other_path.write_text("{}", encoding="utf-8")
    repository.artifact_rows[(job_code, "script")] = {
        "artifact_key": "script",
        "relative_path": f"{other_job_code}/attempt-1/script.json",
        "mime_type": "application/json",
        "file_size": other_path.stat().st_size,
        "checksum_sha256": hashlib.sha256(other_path.read_bytes()).hexdigest(),
    }

    cross_job = test_client.get(f"/api/video-productions/{job_code}/artifacts/script")
    video_path.write_bytes(b"changed!-video")
    changed_digest = test_client.get(f"/api/video-productions/{job_code}/artifacts/video")

    assert cross_job.status_code == 404
    assert changed_digest.status_code == 409
