from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_control_plane_operator
from app.api.routes import compatibility
from app.main import app


NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _run() -> dict:
    return {
        "projection_run_code": "LEGACY-VIDEO:VIDEO-001",
        "source_type": "video_production_job",
        "source_code": "VIDEO-001",
        "workflow_type": "legacy_rendered_video",
        "subject_type": "rendered_video_variant",
        "subject_code": "VIDEO-001",
        "subject_revision": None,
        "status": "queued",
        "priority": 100,
        "progress_completed": 0,
        "progress_total": 100,
        "waiting_reason": None,
        "error_code": None,
        "error_summary": None,
        "created_at": NOW,
        "updated_at": NOW,
        "started_at": None,
        "completed_at": None,
        "source_snapshot": {"legacy_status": "queued"},
        "mapping_quality": "legacy_import",
        "read_only": True,
        "steps": [
            {
                "projection_step_code": "LEGACY-VIDEO-STEP:VIDEO-001:rendering",
                "projection_run_code": "LEGACY-VIDEO:VIDEO-001",
                "source_type": "video_production_stage",
                "source_code": "VIDEO-001:rendering",
                "step_type": "rendering",
                "sort_order": 7,
                "status": "pending",
                "attempt": 1,
                "error_code": None,
                "error_summary": None,
                "started_at": None,
                "completed_at": None,
                "source_snapshot": {"legacy_status": "pending"},
                "read_only": True,
            }
        ],
    }


class FakeCompatibilityRepository:
    def list_runs(self, **_kwargs: object) -> list[dict]:
        return [{**_run(), "steps": []}]

    def get_run(self, projection_run_code: str) -> dict | None:
        return _run() if projection_run_code == "LEGACY-VIDEO:VIDEO-001" else None

    def list_asset_observations(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "projection_code": "IMG-001",
                "asset_code": "IMG-001",
                "asset_type": "IMG",
                "observed_geometry": {"left": 12, "top": 24},
                "duplicate_group": "DUP-001",
                "geometry_semantics": "observed_legacy_placement",
                "duplicate_group_semantics": "legacy_duplicate_candidate",
                "is_constraint": False,
                "is_user_group": False,
                "source_type": "assets",
                "source_code": "IMG-001",
                "mapping_quality": "legacy_import",
                "updated_at": NOW,
                "read_only": True,
            }
        ]

    def list_content_projects(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "projection_project_code": "LEGACY-CONTENT:VIDEO:VIDEO-001",
                "source_type": "video_production_job",
                "source_code": "VIDEO-001",
                "title": "Legacy video",
                "generation_goal": "Legacy video",
                "target_duration_seconds": 60,
                "source_snapshot": {"story_brief_present": False},
                "missing_provenance": ["confirmed_content_project_revision"],
                "mapping_quality": "legacy_import",
                "created_at": NOW,
                "updated_at": NOW,
                "read_only": True,
            }
        ]

    def list_live_room_variants(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "projection_variant_code": "LEGACY-LIVE-VARIANT:WB-001",
                "source_type": "maitu_workbench_run",
                "source_code": "WB-001",
                "carrier_kind": "live_room",
                "target_live_room_id": "38336",
                "expected_title": "Legacy room",
                "legacy_status": "completed",
                "mapping_quality": "legacy_import",
                "source_snapshot": {},
                "created_at": NOW,
                "updated_at": NOW,
                "read_only": True,
            }
        ]

    def list_layout_hypotheses(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "projection_code": "LEGACY-LAYOUT:TPL-001:1",
                "template_code": "TPL-001",
                "revision_number": 1,
                "status": "draft",
                "contract_version": "layout-hypothesis.v1",
                "canvas": {},
                "scenes": [],
                "components": [],
                "audio_policy": {},
                "provenance": {},
                "confidence": 0.4,
                "review_status": "pending",
                "reference_mode": "reference_only",
                "layout_fidelity": "approximate",
                "buildability": "reference_only",
                "conversion_allowed": False,
                "source_type": "live_room_template_revision",
                "source_code": "revision-001",
                "mapping_quality": "descriptive_only",
                "created_at": NOW,
                "updated_at": NOW,
                "read_only": True,
            }
        ]

    def list_delivery_unknown(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "projection_code": "LEGACY-DELIVERY-UNKNOWN:VIDEO:VIDEO-001",
                "source_type": "video_production_job",
                "source_code": "VIDEO-001",
                "possible_carrier_kind": "rendered_video",
                "release_code": None,
                "delivery_code": None,
                "external_identity": None,
                "readback_evidence": None,
                "delivery_semantics": "legacy_delivery_unknown",
                "is_actual_delivery": False,
                "is_exposure": False,
                "source_snapshot": {"legacy_status": "succeeded"},
                "observed_at": NOW,
                "read_only": True,
            }
        ]


@pytest.fixture
def client() -> TestClient:
    repository = FakeCompatibilityRepository()
    app.dependency_overrides[compatibility.get_workflow_compatibility_repository] = lambda: repository
    app.dependency_overrides[require_control_plane_operator] = lambda: "operator-a"
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(compatibility.get_workflow_compatibility_repository, None)
    app.dependency_overrides.pop(require_control_plane_operator, None)


def test_legacy_workflow_projection_routes_are_read_only_and_deep_linkable(client: TestClient) -> None:
    listed = client.get("/api/compatibility/workflow-runs", params={"source_type": "video_production_job"})
    assert listed.status_code == 200
    assert listed.json()[0]["read_only"] is True

    detail = client.get("/api/compatibility/workflow-runs/LEGACY-VIDEO:VIDEO-001")
    assert detail.status_code == 200
    assert detail.json()["steps"][0]["step_type"] == "rendering"

    missing = client.get("/api/compatibility/workflow-runs/LEGACY-VIDEO:missing")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "LEGACY_WORKFLOW_PROJECTION_NOT_FOUND"


def test_legacy_domain_projection_routes_preserve_uncertainty(client: TestClient) -> None:
    assets = client.get("/api/compatibility/assets")
    assert assets.status_code == 200
    assert assets.json()[0] | {
        "is_constraint": False,
        "is_user_group": False,
        "read_only": True,
    } == assets.json()[0]

    content_projects = client.get("/api/compatibility/content-projects")
    assert content_projects.status_code == 200
    assert "confirmed_content_project_revision" in content_projects.json()[0]["missing_provenance"]

    variants = client.get("/api/compatibility/live-room-variants")
    assert variants.status_code == 200
    assert variants.json()[0]["mapping_quality"] == "legacy_import"

    layouts = client.get("/api/compatibility/layout-hypotheses")
    assert layouts.status_code == 200
    assert layouts.json()[0]["contract_version"] == "layout-hypothesis.v1"
    assert layouts.json()[0]["conversion_allowed"] is False
    assert layouts.json()[0]["buildability"] == "reference_only"

    deliveries = client.get("/api/compatibility/delivery-unknown")
    assert deliveries.status_code == 200
    assert deliveries.json()[0]["release_code"] is None
    assert deliveries.json()[0]["delivery_code"] is None
    assert deliveries.json()[0]["is_actual_delivery"] is False
    assert deliveries.json()[0]["is_exposure"] is False
