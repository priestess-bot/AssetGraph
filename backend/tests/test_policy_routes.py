from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_control_plane_operator
from app.api.routes import policy
from app.domain.errors import DomainAuthorizationError
from app.main import app


NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _resource(**overrides: Any) -> dict[str, Any]:
    return {
        "resource_type": "external_resource",
        "resource_id": "external-1",
        "protection_mode": "deny_write",
        "allowed_capabilities": [],
        "reason_code": "SECURITY_HOLD",
        "evidence": {"ticket": "SEC-1"},
        "effective_at": NOW,
        "expires_at": None,
        "revoked_at": None,
        "created_by": "operator-a",
        "created_at": NOW,
        "revision": 1,
        **overrides,
    }


class FakePolicyRepository:
    def __init__(self) -> None:
        self.resource = _resource()
        self.last_register: dict[str, Any] | None = None

    def list_protected_resources(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [self.resource]

    def register_protected_resource(self, **kwargs: Any) -> dict[str, Any]:
        self.last_register = kwargs
        updates = {
            key: value
            for key, value in kwargs.items()
            if key in self.resource and value is not None
        }
        return {**self.resource, **updates}

    def revoke_protected_resource(self, **_kwargs: Any) -> dict[str, Any]:
        raise DomainAuthorizationError(
            "PROTECTED_RESOURCE_SYSTEM_LOCKED",
            "System-locked protected resources cannot be revoked",
        )


@pytest.fixture
def client() -> tuple[TestClient, FakePolicyRepository]:
    repository = FakePolicyRepository()
    app.dependency_overrides[policy.get_policy_repository] = lambda: repository
    app.dependency_overrides[require_control_plane_operator] = lambda: "operator-a"
    with TestClient(app) as test_client:
        yield test_client, repository
    app.dependency_overrides.pop(policy.get_policy_repository, None)
    app.dependency_overrides.pop(require_control_plane_operator, None)


def test_protected_resource_routes_derive_actor_and_map_system_lock(
    client: tuple[TestClient, FakePolicyRepository],
) -> None:
    test_client, repository = client

    listed = test_client.get("/api/policy/protected-resources")
    created = test_client.post(
        "/api/policy/protected-resources",
        json={
            "resource_type": "external_resource",
            "resource_id": "external-1",
            "protection_mode": "deny_write",
            "reason_code": "SECURITY_HOLD",
            "evidence": {"ticket": "SEC-1"},
        },
    )
    revoked = test_client.post(
        "/api/policy/protected-resources/maitu_room/38336/revoke",
        json={"expected_revision": 1, "reason_code": "INVALID_REMOVAL_ATTEMPT"},
    )

    assert listed.status_code == 200
    assert created.status_code == 201
    assert repository.last_register is not None
    assert repository.last_register["actor_id"] == "operator-a"
    assert revoked.status_code == 403
    assert revoked.json()["detail"]["code"] == "PROTECTED_RESOURCE_SYSTEM_LOCKED"


def test_protected_resource_request_rejects_allowlist_on_deny_write(
    client: tuple[TestClient, FakePolicyRepository],
) -> None:
    test_client, repository = client

    response = test_client.post(
        "/api/policy/protected-resources",
        json={
            "resource_type": "platform_account",
            "resource_id": "account-1",
            "protection_mode": "deny_write",
            "allowed_capabilities": ["upload_asset"],
            "reason_code": "SECURITY_HOLD",
        },
    )

    assert response.status_code == 422
    assert repository.last_register is None
