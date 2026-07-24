from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.functional_operations import FunctionalOperationsService


def test_scene_allocation_distributes_each_session_metric_over_observed_durations() -> None:
    started = datetime(2026, 7, 25, 12, tzinfo=UTC)
    sessions = [
        {"session_code": "OPS-001", "metrics": {"watchers": 120}},
        {"session_code": "OPS-002", "metrics": {"watchers": 60}},
    ]
    exposures = {
        "OPS-001": [
            {
                "plan_code": "LIVEPLAN-001",
                "scene_code": "SCENE-01",
                "started_at": started,
                "ended_at": started + timedelta(seconds=10),
                "source_kind": "recording_match",
                "confidence": 0.9,
                "release_code": "RELEASE-001",
            },
            {
                "plan_code": "LIVEPLAN-001",
                "scene_code": "SCENE-02",
                "started_at": started + timedelta(seconds=10),
                "ended_at": started + timedelta(seconds=40),
                "source_kind": "recording_match",
                "confidence": 0.8,
                "release_code": "RELEASE-001",
            },
        ],
        "OPS-002": [
            {
                "plan_code": "LIVEPLAN-001",
                "scene_code": "SCENE-01",
                "started_at": started,
                "ended_at": started + timedelta(seconds=30),
                "source_kind": "manual_observation",
                "confidence": 0.7,
                "release_code": None,
            }
        ],
    }

    allocations = FunctionalOperationsService._scene_allocations(
        sessions,
        exposures,
        metric_key="watchers",
    )

    assert [(item["scene_code"], item["estimated_metric_value"]) for item in allocations] == [
        ("SCENE-01", 90.0),
        ("SCENE-02", 90.0),
    ]
    first = allocations[0]
    assert first["observed_duration_seconds"] == 40.0
    assert first["source_session_codes"] == ["OPS-001", "OPS-002"]
    assert first["source_kind_counts"] == {"recording_match": 1, "manual_observation": 1}
    assert first["average_confidence"] == 0.75
    assert first["allocation_basis"] == "active_observed_exposure_duration_within_each_session"


def test_scene_allocation_omits_sessions_without_active_observed_duration() -> None:
    started = datetime(2026, 7, 25, 12, tzinfo=UTC)

    allocations = FunctionalOperationsService._scene_allocations(
        [{"session_code": "OPS-001", "metrics": {"orders": 2}}],
        {
            "OPS-001": [
                {
                    "plan_code": "LIVEPLAN-001",
                    "scene_code": "SCENE-01",
                    "started_at": started,
                    "ended_at": started,
                    "source_kind": "manual_observation",
                    "confidence": 1,
                    "release_code": None,
                }
            ]
        },
        metric_key="orders",
    )

    assert allocations == []
