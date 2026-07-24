from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.contracts import Capability, canonical_fingerprint
from app.domain.errors import DomainAuthorizationError, DomainConflictError
from app.repositories.control_plane import ControlPlaneRepository
from app.repositories.policy import PolicyRepository
from app.schemas.control_plane import WorkflowRunCreate
from app.services.policy import PolicyDecisionService, PolicyRequest


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _workflow(suffix: str, *, max_attempts: int = 3) -> dict:
    payload = WorkflowRunCreate.model_validate(
        {
            "workflow_type": "external_effect_test",
            "subject_type": "production_variant",
            "subject_code": f"VARIANT-{suffix}",
            "subject_revision": 1,
            "idempotency_key": f"external-effect-{suffix}",
            "steps": [
                {
                    "step_key": "write",
                    "step_type": f"write_{suffix}",
                    "idempotency_key": f"write-{suffix}",
                    "side_effect_level": "write_external",
                    "max_attempts": max_attempts,
                    "timeout_seconds": 60,
                    "reconcile_strategy": "authoritative_readback",
                    "input_fingerprint": "a" * 64,
                }
            ],
        }
    ).model_dump(mode="json")
    payload["requested_by"] = "operator-a"
    return payload


def _claim(repository: ControlPlaneRepository, suffix: str) -> dict:
    claimed = repository.claim_next_step(
        worker_id="worker-a",
        lease_seconds=60,
        accepted_step_types=[f"write_{suffix}"],
    )
    assert claimed is not None
    return claimed


def _prepare(repository: ControlPlaneRepository, claimed: dict, suffix: str) -> dict:
    return repository.prepare_external_effect(
        claimed["step_code"],
        worker_id="worker-a",
        claim_token=claimed["claim_token"],
        lease_version=claimed["lease_version"],
        target_type="maitu_room",
        target_id=f"room-{suffix}",
        operation_type="write_draft",
        idempotency_key=f"effect-{suffix}",
        plan_or_release_hash="b" * 64,
        request_fingerprint="c" * 64,
    )


def _install_write_policy(connection: psycopg.Connection, suffix: str) -> tuple[str, str]:
    policy_code = f"external-effect-policy-{suffix}"
    environment = f"external-effect-{suffix}"
    rules = {
        "schema_version": "capability-policy.v1",
        "role_capabilities": {"production_worker": ["write_draft"]},
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
        cursor.execute(
            """
            INSERT INTO capability_flags (
                capability, environment, enabled, kill_switch_active, changed_by, reason
            )
            VALUES ('write_draft', %s, true, false, 'security-test', 'atomic effect test')
            """,
            (environment,),
        )
    connection.commit()
    return policy_code, environment


def _effect_policy_request(*, suffix: str, environment: str) -> PolicyRequest:
    return PolicyRequest(
        principal_type="worker",
        principal_id="worker-a",
        roles=frozenset({"production_worker"}),
        capability=Capability.WRITE_DRAFT,
        target_type="maitu_room",
        target_id=f"room-{suffix}",
        action="commit",
        environment=environment,
        plan_or_release_hash="b" * 64,
        site_fingerprint="d" * 64,
        trace_id="e" * 32,
    )


def test_commit_authorization_and_effect_transition_are_atomic_and_policy_bound() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        policy_code, environment = _install_write_policy(connection, suffix)
        control_plane = ControlPlaneRepository(connection)
        policy = PolicyDecisionService(PolicyRepository(connection))
        control_plane.create_workflow_run(_workflow(suffix))
        claimed = _claim(control_plane, suffix)
        prepared = _prepare(control_plane, claimed, suffix)
        request = _effect_policy_request(suffix=suffix, environment=environment)

        authorization, token = policy.issue_execution_authorization(
            request,
            ttl=timedelta(minutes=5),
            policy_code=policy_code,
        )
        policy.authorize_commit(
            authorization_code=authorization["authorization_code"],
            raw_token=token,
            request=request,
            commit=False,
        )
        with pytest.raises(DomainConflictError):
            control_plane.authorize_external_effect(
                prepared["effect_code"],
                expected_revision=999,
                authorization_code=authorization["authorization_code"],
                actor_id="worker-a",
            )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM execution_authorizations WHERE authorization_code = %s",
                (authorization["authorization_code"],),
            )
            assert cursor.fetchone()[0] == "active"
        assert control_plane.get_external_effect(prepared["effect_code"])["phase"] == "prepared"

        policy.authorize_commit(
            authorization_code=authorization["authorization_code"],
            raw_token=token,
            request=request,
            commit=False,
        )
        authorized = control_plane.authorize_external_effect(
            prepared["effect_code"],
            expected_revision=prepared["revision"],
            authorization_code=authorization["authorization_code"],
            actor_id="worker-a",
        )
        assert authorized["phase"] == "authorized"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM execution_authorizations WHERE authorization_code = %s",
                (authorization["authorization_code"],),
            )
            assert cursor.fetchone()[0] == "consumed"

        second_suffix = uuid4().hex
        second_request = replace(request, target_id=f"room-{second_suffix}")
        second_auth, second_token = policy.issue_execution_authorization(
            second_request,
            ttl=timedelta(minutes=5),
            policy_code=policy_code,
        )
        replacement_rules = {
            "schema_version": "capability-policy.v1",
            "role_capabilities": {"production_worker": ["write_draft"]},
            "revision_reason": "commit-time revalidation test",
        }
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE capability_policy_versions SET status = 'superseded' "
                "WHERE policy_code = %s AND revision_number = 1",
                (policy_code,),
            )
            cursor.execute(
                """
                INSERT INTO capability_policy_versions (
                    policy_code, revision_number, status, rules, fingerprint_sha256,
                    approved_by, approved_at
                )
                VALUES (%s, 2, 'active', %s, %s, 'security-test', now())
                """,
                (policy_code, Jsonb(replacement_rules), canonical_fingerprint(replacement_rules)),
            )
        connection.commit()
        with pytest.raises(DomainAuthorizationError) as changed_policy:
            policy.authorize_commit(
                authorization_code=second_auth["authorization_code"],
                raw_token=second_token,
                request=second_request,
            )
        assert changed_policy.value.code == "AUTHORIZATION_POLICY_CHANGED"


def test_worker_independently_reloads_registry_before_authorizing_effect() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        repository.create_workflow_run(_workflow(suffix))
        prepared = _prepare(repository, _claim(repository, suffix), suffix)
        PolicyRepository(connection).register_protected_resource(
            resource_type="maitu_room",
            resource_id=f"room-{suffix}",
            protection_mode="deny_write",
            allowed_capabilities=[],
            reason_code="PRODUCTION_HOLD",
            evidence={"ticket": f"SEC-{suffix}"},
            effective_at=None,
            expires_at=None,
            actor_id="security-test",
        )

        with pytest.raises(DomainAuthorizationError) as protected:
            repository.assert_external_effect_target_writable(
                prepared["effect_code"],
                capability="write_draft",
            )

        assert protected.value.code == "WORKER_TARGET_PROTECTED"
        assert protected.value.details["reason_code"] == "PROTECTED_RESOURCE_DENY_WRITE"
        assert repository.get_external_effect(prepared["effect_code"])["phase"] == "prepared"


def test_external_effect_requires_prepare_authorize_commit_and_readback_before_step_success() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        created = repository.create_workflow_run(_workflow(suffix))
        claimed = _claim(repository, suffix)

        with pytest.raises(DomainConflictError) as missing_readback:
            repository.complete_step(
                claimed["step_code"],
                worker_id="worker-a",
                claim_token=claimed["claim_token"],
                lease_version=claimed["lease_version"],
                output_fingerprint="d" * 64,
                actual_cost={},
            )
        assert missing_readback.value.code == "EXTERNAL_EFFECT_READBACK_REQUIRED"

        prepared = _prepare(repository, claimed, suffix)
        replay = _prepare(repository, claimed, suffix)
        assert replay["effect_code"] == prepared["effect_code"]
        authorized = repository.authorize_external_effect(
            prepared["effect_code"],
            expected_revision=1,
            authorization_code=f"AUTH-{suffix}",
            actor_id="worker-a",
        )
        committing = repository.begin_external_commit(
            prepared["effect_code"],
            expected_revision=authorized["revision"],
            actor_id="worker-a",
        )
        committed = repository.record_external_commit(
            prepared["effect_code"],
            expected_revision=committing["revision"],
            actor_id="worker-a",
            outcome="applied",
            response_summary={"accepted": True},
            external_identity={"draft_id": f"draft-{suffix}"},
        )
        readback = repository.complete_external_readback(
            prepared["effect_code"],
            expected_revision=committed["revision"],
            actor_id="worker-a",
            external_identity={"draft_id": f"draft-{suffix}"},
            readback_evidence={"scene_count": 2, "plan_hash": "b" * 64},
        )
        assert readback["phase"] == "readback_succeeded"
        step = repository.complete_step(
            claimed["step_code"],
            worker_id="worker-a",
            claim_token=claimed["claim_token"],
            lease_version=claimed["lease_version"],
            output_fingerprint="d" * 64,
            actual_cost={"external_writes": 1},
        )
        assert step is not None and step["status"] == "succeeded"
        run = repository.get_workflow_run(created["run_code"])
        assert run is not None and run["status"] == "succeeded"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT to_phase FROM workflow_external_effect_history AS history
                JOIN workflow_external_effects AS effect ON effect.id = history.effect_id
                WHERE effect.effect_code = %s ORDER BY history.revision
                """,
                (prepared["effect_code"],),
            )
            phases = [row[0] for row in cursor.fetchall()]
        assert phases == ["prepared", "authorized", "committing", "committed", "readback_succeeded"]


def test_unknown_external_commit_moves_effect_step_and_run_to_reconcile_without_reclaim() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        created = repository.create_workflow_run(_workflow(suffix))
        claimed = _claim(repository, suffix)
        prepared = _prepare(repository, claimed, suffix)
        authorized = repository.authorize_external_effect(
            prepared["effect_code"],
            expected_revision=1,
            authorization_code=f"AUTH-{suffix}",
            actor_id="worker-a",
        )
        committing = repository.begin_external_commit(
            prepared["effect_code"],
            expected_revision=authorized["revision"],
            actor_id="worker-a",
        )
        unknown = repository.record_external_commit(
            prepared["effect_code"],
            expected_revision=committing["revision"],
            actor_id="worker-a",
            outcome="unknown",
            response_summary={"timeout": True},
            external_identity=None,
            error_code="UPSTREAM_TIMEOUT",
        )
        assert unknown["phase"] == "reconcile_required"
        run = repository.get_workflow_run(created["run_code"])
        assert run is not None and run["status"] == "reconcile_required"
        assert run["steps"][0]["status"] == "reconcile_required"
        assert repository.claim_next_step(
            worker_id="worker-b",
            lease_seconds=60,
            accepted_step_types=[f"write_{suffix}"],
        ) is None


def test_human_task_sla_escalation_expiration_and_absolute_step_timeout() -> None:
    escalation_suffix = uuid4().hex
    expiration_suffix = uuid4().hex
    timeout_suffix = uuid4().hex
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)

        repository.create_workflow_run(_workflow(escalation_suffix))
        escalation_step = _claim(repository, escalation_suffix)
        escalation_task = repository.create_human_task(
            step_code=escalation_step["step_code"],
            task_type="security_review",
            subject={"revision": 1},
            owner_principal="security-owner",
            due_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=1),
        )

        expiration_run = repository.create_workflow_run(_workflow(expiration_suffix))
        expiration_step = _claim(repository, expiration_suffix)
        expiration_task = repository.create_human_task(
            step_code=expiration_step["step_code"],
            task_type="production_approval",
            subject={"revision": 1},
            owner_principal="product-owner",
            due_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )

        swept = repository.sweep_human_tasks()
        assert swept["escalated"] >= 1
        assert swept["expired"] >= 1
        assert repository.get_human_task(escalation_task["task_code"])["status"] == "escalated"
        assert repository.get_human_task(expiration_task["task_code"])["status"] == "expired"
        expired_run = repository.get_workflow_run(expiration_run["run_code"])
        assert expired_run is not None and expired_run["status"] == "failed"

        timeout_run = repository.create_workflow_run(_workflow(timeout_suffix, max_attempts=1))
        timeout_step = _claim(repository, timeout_suffix)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE workflow_steps
                SET started_at = %s, lease_expires_at = now() + interval '1 hour'
                WHERE step_code = %s
                """,
                (datetime(2020, 1, 1, tzinfo=UTC), timeout_step["step_code"]),
            )
        connection.commit()
        repository.claim_next_step(worker_id="sweeper", lease_seconds=60, accepted_step_types=["none"])
        timed_out = repository.get_workflow_run(timeout_run["run_code"])
        assert timed_out is not None
        assert timed_out["status"] == "reconcile_required"
        assert timed_out["steps"][0]["error_code"] == "WORKFLOW_STEP_TIMEOUT"


def test_cancellation_racing_an_unknown_external_commit_requires_single_reconciliation() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        created = repository.create_workflow_run(_workflow(suffix))
        claimed = _claim(repository, suffix)
        prepared = _prepare(repository, claimed, suffix)
        authorized = repository.authorize_external_effect(
            prepared["effect_code"],
            expected_revision=1,
            authorization_code=f"AUTH-{suffix}",
            actor_id="worker-a",
        )
        committing = repository.begin_external_commit(
            prepared["effect_code"],
            expected_revision=authorized["revision"],
            actor_id="worker-a",
        )

        cancelling = repository.cancel_workflow_run(
            created["run_code"],
            requested_by="operator-a",
            reason="operator cancelled while provider response was pending",
        )
        assert cancelling is not None and cancelling["status"] == "cancelling"
        unknown = repository.record_external_commit(
            prepared["effect_code"],
            expected_revision=committing["revision"],
            actor_id="worker-a",
            outcome="unknown",
            response_summary={"timeout": True},
            external_identity=None,
            error_code="UPSTREAM_TIMEOUT",
        )
        assert unknown["phase"] == "reconcile_required"
        current = repository.get_workflow_run(created["run_code"])
        assert current is not None and current["status"] == "reconcile_required"

        with pytest.raises(DomainConflictError) as replay:
            repository.record_external_commit(
                prepared["effect_code"],
                expected_revision=committing["revision"],
                actor_id="worker-a",
                outcome="unknown",
                response_summary={"timeout": True},
                external_identity=None,
            )
        assert replay.value.code == "WORKFLOW_EXTERNAL_EFFECT_REVISION_CONFLICT"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM workflow_external_effects WHERE step_code = %s",
                (claimed["step_code"],),
            )
            assert cursor.fetchone()[0] == 1
