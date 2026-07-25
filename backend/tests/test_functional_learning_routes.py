from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import functional_learning


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _effect(**overrides: Any) -> dict[str, Any]:
    return {
        "effect_code": "EFFECT-001",
        "revision_number": 1,
        "attribution_report_code": "ATTR-001",
        "subject_type": "content_project",
        "subject_code": "CONTENT-001",
        "metric_key": "watchers",
        "evidence_level": "descriptive",
        "status": "revoked",
        "context": {},
        "effect_payload": {},
        "eligibility_snapshot": {"qualification": "descriptive_only"},
        "note": "The measurement input was corrected.",
        "approved_by": "operator-a",
        "approved_at": NOW,
        "revoked_by": "operator-b",
        "revoked_at": NOW,
        "revoked_reason": "The measurement input was corrected.",
        "fingerprint_sha256": "a" * 64,
        "created_at": NOW,
        **overrides,
    }


class FakeFunctionalLearningService:
    def __init__(self) -> None:
        self.revoke_calls: list[tuple[str, str, str]] = []

    def revoke_effect_estimate(
        self, effect_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        self.revoke_calls.append((effect_code, actor, reason))
        if effect_code == "EFFECT-MISSING":
            return None
        return _effect(effect_code=effect_code, revoked_by=actor, revoked_reason=reason)

    @staticmethod
    def assign_experiment_subject(code: str, subject_key: str) -> dict[str, Any] | None:
        if code == "EXP-MISSING":
            return None
        return {
            "assignment_code": "ASSIGN-001",
            "experiment_code": code,
            "subject_key": subject_key,
            "variant_key": "treatment",
            "assignment_strategy": "stable_hash_sha256_v1",
            "registration_fingerprint_sha256": "b" * 64,
            "assigned_at": NOW,
        }


@pytest.fixture
def client() -> tuple[TestClient, FakeFunctionalLearningService]:
    service = FakeFunctionalLearningService()
    app = FastAPI()
    app.include_router(functional_learning.router, prefix="/api")
    app.dependency_overrides[functional_learning.service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service


def test_revoke_effect_route_records_actor_and_reason(
    client: tuple[TestClient, FakeFunctionalLearningService],
) -> None:
    test_client, service = client

    response = test_client.post(
        "/api/functional-learning/effects/EFFECT-001/revoke",
        json={"actor": "operator-b", "reason": "The measurement input was corrected."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert response.json()["revoked_reason"] == "The measurement input was corrected."
    assert service.revoke_calls == [
        ("EFFECT-001", "operator-b", "The measurement input was corrected.")
    ]


def test_revoke_effect_route_rejects_empty_reason_and_handles_missing_effect(
    client: tuple[TestClient, FakeFunctionalLearningService],
) -> None:
    test_client, service = client

    invalid = test_client.post(
        "/api/functional-learning/effects/EFFECT-001/revoke",
        json={"reason": ""},
    )
    missing = test_client.post(
        "/api/functional-learning/effects/EFFECT-MISSING/revoke",
        json={"reason": "Evidence was withdrawn."},
    )

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert service.revoke_calls == [
        ("EFFECT-MISSING", "functional-operator", "Evidence was withdrawn.")
    ]


def test_experiment_assignment_route_returns_stable_assignment(
    client: tuple[TestClient, FakeFunctionalLearningService],
) -> None:
    test_client, _service = client

    assigned = test_client.post(
        "/api/functional-learning/experiments/EXP-001/assignments",
        json={"subject_key": "session-001"},
    )
    missing = test_client.post(
        "/api/functional-learning/experiments/EXP-MISSING/assignments",
        json={"subject_key": "session-001"},
    )

    assert assigned.status_code == 200
    assert assigned.json()["variant_key"] == "treatment"
    assert assigned.json()["assignment_strategy"] == "stable_hash_sha256_v1"
    assert missing.status_code == 404
