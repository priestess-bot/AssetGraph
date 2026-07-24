from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.problems import ProblemState, classify_problem, problem_payload
from app.main import app


def test_problem_classifier_keeps_nonterminal_operational_states_distinct() -> None:
    assert classify_problem(409, "Expected revision is stale").state == ProblemState.STALE
    assert classify_problem(422, "insufficient_data").state == ProblemState.INSUFFICIENT_DATA
    assert classify_problem(504, "External outcome is unknown").state == ProblemState.RECONCILE_REQUIRED
    assert classify_problem(503, "Dependency unavailable").state == ProblemState.WARNING
    assert classify_problem(500, "Unexpected failure").state == ProblemState.ERROR


def test_explicit_domain_code_is_preserved_with_safe_evidence() -> None:
    payload = problem_payload(
        status_code=404,
        detail={"code": "LEGACY_WORKFLOW_PROJECTION_NOT_FOUND", "message": "Not found"},
        request_path="/api/compatibility/workflow-runs/missing",
        trace_id="a" * 32,
    )

    assert payload["code"] == "LEGACY_WORKFLOW_PROJECTION_NOT_FOUND"
    assert payload["state"] == "error"
    assert payload["evidence"] == [
        {"kind": "request", "ref": "/api/compatibility/workflow-runs/missing"},
        {"kind": "trace", "ref": "a" * 32},
    ]
    assert payload["next_step"]


def test_http_and_validation_errors_include_compatible_structured_contract() -> None:
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            missing = client.get("/api/not-a-real-route")
            invalid = client.post("/api/assets", json={})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert missing.status_code == 404
    assert missing.json()["detail"] == "Not Found"
    assert missing.json()["error"] | {
        "code": "RESOURCE_NOT_FOUND",
        "state": "error",
    } == missing.json()["error"]
    assert missing.json()["error"]["evidence"][0] == {
        "kind": "request",
        "ref": "/api/not-a-real-route",
    }

    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list)
    assert invalid.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert invalid.json()["error"]["impact"] == "No command was executed."
    assert invalid.json()["error"]["next_step"]
