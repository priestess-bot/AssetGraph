from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.contracts import Capability, canonical_fingerprint
from app.domain.errors import DomainAuthorizationError, DomainUnavailableError
from app.repositories.policy import PolicyRepository
from app.services.policy import PolicyDecisionService, PolicyRequest


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _install_policy(connection: psycopg.Connection, suffix: str) -> tuple[str, str]:
    policy_code = f"test-policy-{suffix}"
    environment = f"test-{suffix}"
    rules = {
        "schema_version": "capability-policy.v1",
        "role_capabilities": {
            "operator": ["write_draft", "upload_asset", "deliver_release"],
            "data": ["rebuild_projection"],
        },
        "required_approval_count": {"deliver_release": 1},
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO capability_policy_versions (
                policy_code, revision_number, status, rules, fingerprint_sha256,
                approved_by, approved_at
            )
            VALUES (%s, 1, 'active', %s, %s, 'security-test', now())
            """,
            (policy_code, Jsonb(rules), canonical_fingerprint(rules)),
        )
        for capability in ("write_draft", "upload_asset", "deliver_release", "rebuild_projection"):
            cursor.execute(
                """
                INSERT INTO capability_flags (
                    capability, environment, enabled, kill_switch_active, changed_by, reason
                )
                VALUES (%s, %s, true, false, 'security-test', 'isolated integration test')
                """,
                (capability, environment),
            )
    connection.commit()
    return policy_code, environment


def _request(
    environment: str,
    *,
    capability: Capability = Capability.WRITE_DRAFT,
    target_id: str = "room-production",
    roles: frozenset[str] = frozenset({"operator"}),
    approvals: tuple[dict, ...] = (),
) -> PolicyRequest:
    return PolicyRequest(
        principal_type="worker",
        principal_id="worker-a",
        roles=roles,
        capability=capability,
        target_type="live_room",
        target_id=target_id,
        action="commit",
        environment=environment,
        plan_or_release_hash="a" * 64,
        site_fingerprint="b" * 64,
        approval_chain=approvals,
        trace_id="c" * 32,
    )


def test_policy_decision_authorization_is_target_bound_single_use_and_commit_checked() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        policy_code, environment = _install_policy(connection, suffix)
        service = PolicyDecisionService(PolicyRepository(connection))
        request = _request(environment)
        authorization, token = service.issue_execution_authorization(
            request,
            ttl=timedelta(minutes=5),
            policy_code=policy_code,
        )

        with pytest.raises(DomainAuthorizationError) as wrong_target:
            service.authorize_commit(
                authorization_code=authorization["authorization_code"],
                raw_token=token,
                request=_request(environment, target_id="reference-room"),
            )
        assert wrong_target.value.code == "AUTHORIZATION_TARGET_MISMATCH"

        consumed = service.authorize_commit(
            authorization_code=authorization["authorization_code"],
            raw_token=token,
            request=request,
        )
        assert consumed["status"] == "consumed"
        with pytest.raises(DomainAuthorizationError) as replay:
            service.authorize_commit(
                authorization_code=authorization["authorization_code"],
                raw_token=token,
                request=request,
            )
        assert replay.value.code == "AUTHORIZATION_NOT_ACTIVE"


def test_authorization_expiry_cross_capability_and_registry_change_fail_closed() -> None:
    suffix = uuid4().hex
    issued_at = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        policy_code, environment = _install_policy(connection, suffix)
        service = PolicyDecisionService(PolicyRepository(connection))

        expired_request = _request(environment)
        expired, expired_token = service.issue_execution_authorization(
            expired_request,
            ttl=timedelta(minutes=1),
            policy_code=policy_code,
            now=issued_at,
        )
        with pytest.raises(DomainAuthorizationError) as expiry:
            service.authorize_commit(
                authorization_code=expired["authorization_code"],
                raw_token=expired_token,
                request=expired_request,
                now=issued_at + timedelta(minutes=2),
            )
        assert expiry.value.code == "AUTHORIZATION_EXPIRED"

        upload_request = _request(environment, capability=Capability.UPLOAD_ASSET)
        upload, upload_token = service.issue_execution_authorization(
            upload_request,
            ttl=timedelta(minutes=5),
            policy_code=policy_code,
        )
        with pytest.raises(DomainAuthorizationError) as cross_capability:
            service.authorize_commit(
                authorization_code=upload["authorization_code"],
                raw_token=upload_token,
                request=_request(environment, capability=Capability.WRITE_DRAFT),
            )
        assert cross_capability.value.code == "AUTHORIZATION_CAPABILITY_MISMATCH"

        protected_request = _request(environment, target_id=f"room-{suffix}")
        protected_auth, protected_token = service.issue_execution_authorization(
            protected_request,
            ttl=timedelta(minutes=5),
            policy_code=policy_code,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO protected_resources (
                    resource_type, resource_id, protection_mode, allowed_capabilities,
                    reason_code, evidence, created_by
                )
                VALUES ('live_room', %s, 'deny_write', '[]'::jsonb,
                        'REFERENCE_ONLY', '{}'::jsonb, 'security-test')
                """,
                (protected_request.target_id,),
            )
        connection.commit()
        with pytest.raises(DomainAuthorizationError) as protected:
            service.authorize_commit(
                authorization_code=protected_auth["authorization_code"],
                raw_token=protected_token,
                request=protected_request,
            )
        assert protected.value.code == "RESOURCE_PROTECTED_AT_COMMIT"


def test_policy_denial_is_persisted_and_go_live_cannot_be_issued() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        policy_code, environment = _install_policy(connection, suffix)
        service = PolicyDecisionService(PolicyRepository(connection))
        denied = service.decide(
            _request(environment, roles=frozenset({"viewer"})),
            policy_code=policy_code,
        )
        assert denied["decision"] == "deny"
        assert "ROLE_CAPABILITY_DENIED" in denied["reason_codes"]

        with pytest.raises(DomainAuthorizationError) as go_live:
            service.issue_execution_authorization(
                _request(environment, capability=Capability.GO_LIVE),
                ttl=timedelta(minutes=1),
                policy_code=policy_code,
            )
        assert go_live.value.code == "POLICY_DECISION_DENIED"


def test_policy_dependency_failure_is_explicitly_unavailable_and_denied() -> None:
    class BrokenRepository:
        def get_active_policy(self, policy_code: str | None = None) -> None:
            del policy_code
            raise OSError("database unavailable")

        def rollback(self) -> None:
            pass

    service = PolicyDecisionService(BrokenRepository())  # type: ignore[arg-type]
    with pytest.raises(DomainUnavailableError) as unavailable:
        service.decide(_request("unavailable"))
    assert unavailable.value.code == "POLICY_SERVICE_UNAVAILABLE"
