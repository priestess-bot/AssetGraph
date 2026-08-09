from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.routes import releases
from app.main import app


class FakeReleaseRepository:
    def __init__(self) -> None:
        self.project_codes: list[str | None] = []
        self.release = {
            "release_code": "RELEASE-PROJECT",
            "status": "approved",
            "approvals": [{"decision": "approve"}],
            "created_at": datetime(2026, 8, 9, tzinfo=UTC),
        }

    def list_releases(self, project_code: str | None = None) -> list[dict]:
        self.project_codes.append(project_code)
        return [{"release_code": "RELEASE-PROJECT"}] if project_code else []

    def get_release(self, release_code: str) -> dict | None:
        return self.release if release_code == "RELEASE-PROJECT" else None


@pytest.fixture
def client() -> Iterator[tuple[TestClient, FakeReleaseRepository]]:
    repository = FakeReleaseRepository()
    app.dependency_overrides[releases.repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client, repository
    app.dependency_overrides.pop(releases.repository, None)


def test_list_releases_forwards_optional_project_filter(
    client: tuple[TestClient, FakeReleaseRepository],
) -> None:
    http, repository = client

    global_response = http.get("/api/releases")
    project_response = http.get("/api/releases", params={"project_code": "CONTENT-001"})

    assert global_response.status_code == 200
    assert global_response.json() == []
    assert project_response.status_code == 200
    assert project_response.json() == [{"release_code": "RELEASE-PROJECT"}]
    assert repository.project_codes == [None, "CONTENT-001"]


def test_list_releases_rejects_an_empty_project_filter(
    client: tuple[TestClient, FakeReleaseRepository],
) -> None:
    http, repository = client

    response = http.get("/api/releases", params={"project_code": ""})

    assert response.status_code == 422
    assert repository.project_codes == []


def test_release_product_api_has_no_unprotected_decision_route(
    client: tuple[TestClient, FakeReleaseRepository],
) -> None:
    http, _repository = client

    response = http.post(
        "/api/releases/RELEASE-PROJECT/decision",
        json={
            "decision": "approve",
            "idempotency_key": "release-approve-001",
        },
    )

    assert response.status_code == 404


def test_delivery_package_serializes_database_values_as_an_attachment(
    client: tuple[TestClient, FakeReleaseRepository],
) -> None:
    http, _repository = client

    response = http.get("/api/releases/RELEASE-PROJECT/delivery-package")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="RELEASE-PROJECT-delivery-package.json"'
    )
    assert response.json()["created_at"] == "2026-08-09T00:00:00+00:00"
