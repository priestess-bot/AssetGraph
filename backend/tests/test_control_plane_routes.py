from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_control_plane_operator, require_control_plane_worker
from app.api.routes import control_plane
from app.main import app


NOW = datetime(2026, 7, 23, tzinfo=UTC)
CLAIM_TOKEN = "11111111-1111-4111-8111-111111111111"


def _step(*, status: str = "ready", claimed: bool = False) -> dict[str, Any]:
    return {
        "step_code": "STEP-20260723-000001",
        "step_type": "prepare_content",
        "sort_order": 0,
        "status": status,
        "priority": 100,
        "idempotency_key": "prepare-1",
        "side_effect_level": "pure_compute",
        "max_attempts": 3,
        "attempt": 1 if claimed else 0,
        "timeout_seconds": 60,
        "cancellable": True,
        "compensation_strategy": None,
        "reconcile_strategy": None,
        "input_fingerprint": "a" * 64,
        "output_fingerprint": None,
        "claimed_by": "worker-a" if claimed else None,
        "lease_version": 1 if claimed else 0,
        "lease_expires_at": NOW + timedelta(minutes=1) if claimed else None,
        "heartbeat_at": NOW if claimed else None,
        "error_code": None,
        "error_summary": None,
        "started_at": NOW if claimed else None,
        "completed_at": None,
        "depends_on": [],
    }


def _run(*, status: str = "queued") -> dict[str, Any]:
    return {
        "run_code": "RUN-20260723-000001",
        "workflow_type": "content_generation",
        "subject_type": "content_project",
        "subject_code": "CONTENT-1",
        "subject_revision": 1,
        "parent_run_code": None,
        "status": status,
        "priority": 100,
        "progress_completed": 0,
        "progress_total": 1,
        "queue_reason": "waiting_for_dependencies",
        "budget": {},
        "actual_cost": {},
        "trace_id": None,
        "root_span_id": None,
        "requested_by": "operator-a",
        "cancellation_requested_at": None,
        "waiting_reason": None,
        "error_code": None,
        "error_summary": None,
        "started_at": None,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "steps": [_step()],
        "human_tasks": [],
    }


def _task(*, status: str = "open", revision: int = 1) -> dict[str, Any]:
    return {
        "task_code": "TASK-20260723-000001",
        "run_code": "RUN-20260723-000001",
        "step_code": "STEP-20260723-000001",
        "task_type": "approve_content",
        "status": status,
        "revision": revision,
        "priority": 100,
        "owner_principal": "operator-a",
        "claimed_by": "operator-a" if status == "claimed" else None,
        "claimed_at": NOW if status == "claimed" else None,
        "due_at": None,
        "escalated_at": None,
        "subject": {"revision": 1},
        "decision": None,
        "structured_reason": None,
        "decided_by": None,
        "decided_at": None,
        "expires_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


class FakeControlPlaneRepository:
    def __init__(self) -> None:
        self.run = _run()
        self.last_create: dict[str, Any] | None = None
        self.last_cancel: dict[str, Any] | None = None

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.last_create = payload
        return self.run

    def get_workflow_run(self, run_code: str) -> dict[str, Any] | None:
        return self.run if run_code == self.run["run_code"] else None

    def cancel_workflow_run(self, run_code: str, *, requested_by: str, reason: str) -> dict[str, Any] | None:
        self.last_cancel = {"requested_by": requested_by, "reason": reason}
        if run_code != self.run["run_code"]:
            return None
        return {**self.run, "status": "cancelled", "completed_at": NOW}

    def claim_next_step(self, **kwargs: Any) -> dict[str, Any]:
        return {**_step(status="running", claimed=True), "run_code": self.run["run_code"], "claim_token": CLAIM_TOKEN}

    def heartbeat_step(self, step_code: str, **kwargs: Any) -> dict[str, Any] | None:
        return _step(status="running", claimed=True) if step_code == "STEP-20260723-000001" else None

    def complete_step(self, step_code: str, **kwargs: Any) -> dict[str, Any] | None:
        return {**_step(status="succeeded"), "output_fingerprint": "b" * 64, "completed_at": NOW}

    def fail_step(self, step_code: str, **kwargs: Any) -> dict[str, Any] | None:
        return {**_step(status="failed"), "error_code": kwargs["error_code"], "completed_at": NOW}

    def list_human_tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [_task()]

    def get_human_task(self, task_code: str) -> dict[str, Any] | None:
        return _task() if task_code == "TASK-20260723-000001" else None

    def claim_human_task(self, task_code: str, **kwargs: Any) -> dict[str, Any] | None:
        return _task(status="claimed", revision=2) if task_code == "TASK-20260723-000001" else None

    def decide_human_task(self, task_code: str, **kwargs: Any) -> dict[str, Any] | None:
        if task_code != "TASK-20260723-000001":
            return None
        return {
            **_task(status="decided", revision=3),
            "decision": kwargs["decision"],
            "structured_reason": kwargs["structured_reason"],
            "decided_by": kwargs["decided_by"],
            "decided_at": NOW,
        }


@pytest.fixture
def client() -> tuple[TestClient, FakeControlPlaneRepository]:
    repository = FakeControlPlaneRepository()
    app.dependency_overrides[control_plane.get_control_plane_repository] = lambda: repository
    app.dependency_overrides[require_control_plane_operator] = lambda: "operator-a"
    app.dependency_overrides[require_control_plane_worker] = lambda: "worker-a"
    with TestClient(app) as test_client:
        yield test_client, repository
    app.dependency_overrides.pop(control_plane.get_control_plane_repository, None)
    app.dependency_overrides.pop(require_control_plane_operator, None)
    app.dependency_overrides.pop(require_control_plane_worker, None)


def _create_payload() -> dict[str, Any]:
    return {
        "workflow_type": "content_generation",
        "subject_type": "content_project",
        "subject_code": "CONTENT-1",
        "subject_revision": 1,
        "idempotency_key": "run-1",
        "steps": [
            {
                "step_key": "prepare",
                "step_type": "prepare_content",
                "idempotency_key": "prepare-1",
                "timeout_seconds": 60,
                "input_fingerprint": "a" * 64,
            }
        ],
    }


def test_workflow_routes_derive_principal_and_expose_get_cancel(
    client: tuple[TestClient, FakeControlPlaneRepository],
) -> None:
    test_client, repository = client

    created = test_client.post("/api/workflow-runs", json=_create_payload())
    fetched = test_client.get("/api/workflow-runs/RUN-20260723-000001")
    cancelled = test_client.post(
        "/api/workflow-runs/RUN-20260723-000001/cancel",
        json={"reason": "operator requested"},
    )
    missing = test_client.get("/api/workflow-runs/RUN-MISSING")

    assert created.status_code == 201
    assert repository.last_create is not None
    assert repository.last_create["requested_by"] == "operator-a"
    assert fetched.status_code == 200
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert repository.last_cancel == {"requested_by": "operator-a", "reason": "operator requested"}
    assert missing.status_code == 404


def test_workflow_creation_inherits_server_trace_instead_of_client_payload_trace(
    client: tuple[TestClient, FakeControlPlaneRepository],
) -> None:
    test_client, repository = client
    inbound_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    inbound_parent_span = "00f067aa0ba902b7"
    payload = {
        **_create_payload(),
        "trace_id": "f" * 32,
        "root_span_id": "e" * 16,
    }

    response = test_client.post(
        "/api/workflow-runs",
        json=payload,
        headers={"traceparent": f"00-{inbound_trace_id}-{inbound_parent_span}-01"},
    )

    assert response.status_code == 201
    assert repository.last_create is not None
    assert repository.last_create["trace_id"] == inbound_trace_id
    assert len(repository.last_create["root_span_id"]) == 16
    assert repository.last_create["root_span_id"] != inbound_parent_span
    assert response.headers["traceparent"].split("-")[1] == inbound_trace_id


def test_worker_routes_require_header_identity_to_match_payload(
    client: tuple[TestClient, FakeControlPlaneRepository],
) -> None:
    test_client, _repository = client

    mismatch = test_client.post(
        "/api/workflow-steps/claim-next",
        json={"worker_id": "worker-b", "lease_seconds": 60},
    )
    claimed = test_client.post(
        "/api/workflow-steps/claim-next",
        json={"worker_id": "worker-a", "lease_seconds": 60},
    )
    heartbeat = test_client.post(
        "/api/workflow-steps/STEP-20260723-000001/heartbeat",
        json={
            "worker_id": "worker-a",
            "claim_token": CLAIM_TOKEN,
            "lease_version": 1,
            "lease_seconds": 60,
        },
    )

    assert mismatch.status_code == 403
    assert claimed.status_code == 200
    assert claimed.json()["claim_token"] == CLAIM_TOKEN
    assert heartbeat.status_code == 200


def test_human_task_routes_use_expected_revision_and_structured_reason(
    client: tuple[TestClient, FakeControlPlaneRepository],
) -> None:
    test_client, _repository = client

    listed = test_client.get("/api/human-tasks?status=open")
    claimed = test_client.post(
        "/api/human-tasks/TASK-20260723-000001/claim",
        json={"claimed_by": "operator-a", "expected_revision": 1},
    )
    decided = test_client.post(
        "/api/human-tasks/TASK-20260723-000001/decide",
        json={
            "decided_by": "operator-a",
            "expected_revision": 2,
            "decision": "approve",
            "structured_reason": {"reason_code": "CONTENT_VERIFIED"},
        },
    )

    assert listed.status_code == 200
    assert claimed.json()["revision"] == 2
    assert decided.status_code == 200
    assert decided.json()["structured_reason"] == {"reason_code": "CONTENT_VERIFIED"}
