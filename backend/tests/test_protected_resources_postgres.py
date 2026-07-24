from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from app.domain.contracts import Capability
from app.domain.errors import DomainAuthorizationError
from app.repositories.policy import PolicyRepository
from app.services.policy import PolicyDecisionService, PolicyRequest


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _request(*, environment: str, capability: Capability, target_id: str, role: str) -> PolicyRequest:
    return PolicyRequest(
        principal_type="worker",
        principal_id="worker-security-test",
        roles=frozenset({role}),
        capability=capability,
        target_type="maitu_room",
        target_id=target_id,
        action="commit",
        environment=environment,
        plan_or_release_hash="a" * 64,
    )


def test_baseline_capabilities_are_non_transitive_and_go_live_is_hard_disabled() -> None:
    suffix = uuid4().hex
    environment = f"protected-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO capability_flags (
                    capability, environment, enabled, kill_switch_active, changed_by, reason
                ) VALUES ('upload_asset', %s, true, false, 'security-test', 'role isolation test')
                """,
                (environment,),
            )
        connection.commit()
        service = PolicyDecisionService(PolicyRepository(connection))

        cross_role = service.decide(
            _request(
                environment=environment,
                capability=Capability.UPLOAD_ASSET,
                target_id=f"room-{suffix}",
                role="draft_writer",
            ),
            policy_code="baseline-least-privilege",
        )
        go_live = service.decide(
            _request(
                environment=environment,
                capability=Capability.GO_LIVE,
                target_id=f"room-live-{suffix}",
                role="broadcast_operator",
            ),
            policy_code="baseline-least-privilege",
        )

        assert cross_role["decision"] == "deny"
        assert "ROLE_CAPABILITY_DENIED" in cross_role["reason_codes"]
        assert go_live["decision"] == "deny"
        assert "GO_LIVE_GLOBALLY_DISABLED" in go_live["reason_codes"]
        with pytest.raises(DomainAuthorizationError):
            service.issue_execution_authorization(
                _request(
                    environment=environment,
                    capability=Capability.GO_LIVE,
                    target_id=f"room-live-{suffix}",
                    role="broadcast_operator",
                ),
                ttl=timedelta(minutes=1),
                policy_code="baseline-least-privilege",
            )


def test_registry_lifecycle_is_versioned_and_reference_rooms_are_system_locked() -> None:
    suffix = uuid4().hex
    resource_id = f"account-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PolicyRepository(connection)
        created = repository.register_protected_resource(
            resource_type="platform_account",
            resource_id=resource_id,
            protection_mode="allowlisted_write",
            allowed_capabilities=["upload_asset"],
            reason_code="ACCOUNT_SCOPE_LIMIT",
            evidence={"ticket": f"SEC-{suffix}"},
            effective_at=None,
            expires_at=None,
            actor_id="security-test",
        )
        updated = repository.register_protected_resource(
            resource_type="platform_account",
            resource_id=resource_id,
            protection_mode="deny_write",
            allowed_capabilities=[],
            reason_code="ACCOUNT_SECURITY_HOLD",
            evidence={"ticket": f"SEC-{suffix}-2"},
            effective_at=None,
            expires_at=None,
            actor_id="security-test",
            expected_revision=created["revision"],
        )
        revoked = repository.revoke_protected_resource(
            resource_type="platform_account",
            resource_id=resource_id,
            expected_revision=updated["revision"],
            reason_code="ACCOUNT_HOLD_CLEARED",
            actor_id="security-test",
        )

        assert (created["revision"], updated["revision"], revoked["revision"]) == (1, 2, 3)
        assert repository.get_protected_resource("platform_account", resource_id) is None
        listed = repository.list_protected_resources(
            resource_type="platform_account",
            include_revoked=True,
        )
        assert next(item for item in listed if item["resource_id"] == resource_id)["revision"] == 3
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type FROM protected_resource_events
                WHERE resource_id = %s ORDER BY revision
                """,
                (resource_id,),
            )
            assert [row[0] for row in cursor.fetchall()] == ["registered", "updated", "revoked"]

        for reference_room_id in ("38336", "38995"):
            reference = repository.get_protected_resource("maitu_room", reference_room_id)
            assert reference is not None
            assert reference["evidence"]["system_locked"] is True
            with pytest.raises(DomainAuthorizationError) as locked:
                repository.revoke_protected_resource(
                    resource_type="maitu_room",
                    resource_id=reference_room_id,
                    expected_revision=1,
                    reason_code="INVALID_REMOVAL_ATTEMPT",
                    actor_id="security-test",
                )
            assert locked.value.code == "PROTECTED_RESOURCE_SYSTEM_LOCKED"


def test_pdp_denies_seeded_reference_room_even_for_the_correct_role() -> None:
    suffix = uuid4().hex
    environment = f"protected-pdp-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO capability_flags (
                    capability, environment, enabled, kill_switch_active, changed_by, reason
                ) VALUES ('write_draft', %s, true, false, 'security-test', 'PDP protection test')
                """,
                (environment,),
            )
        connection.commit()
        decision = PolicyDecisionService(PolicyRepository(connection)).decide(
            _request(
                environment=environment,
                capability=Capability.WRITE_DRAFT,
                target_id="38336",
                role="draft_writer",
            ),
            policy_code="baseline-least-privilege",
        )

        assert decision["decision"] == "deny"
        assert "PROTECTED_RESOURCE_DENY_WRITE" in decision["reason_codes"]
