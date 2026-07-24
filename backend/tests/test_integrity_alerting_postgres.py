from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.contracts import Capability, canonical_fingerprint
from app.domain.errors import DomainConflictError
from app.repositories.control_plane import ControlPlaneRepository
from app.repositories.evidence import EvidenceRepository
from app.repositories.integrity import IntegrityRepository, assert_projection_event_is_new
from app.repositories.policy import PolicyRepository
from app.schemas.control_plane import WorkflowRunCreate
from app.services.integrity import EvidenceIntegrityMonitor
from app.services.manifests import seal_run_manifest
from app.services.policy import PolicyDecisionService, PolicyRequest


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _manifest(seed: int) -> dict:
    return {
        "input_revisions": [{"object_type": "content_project", "code": "CONTENT-1", "revision": 1}],
        "input_artifacts": [],
        "inventory_refs": [],
        "material_refs": [],
        "constraint_refs": [],
        "rights_refs": [],
        "template_refs": [],
        "fact_refs": [],
        "content_refs": [],
        "model_strategies": [],
        "prompt_revisions": [],
        "code_revision": "integrity-test",
        "tool_versions": [{"name": "assetgraph", "version": "test"}],
        "random_seed": seed,
        "environment": {"profile": "isolated-postgres"},
    }


def _issue_authorization(connection: psycopg.Connection, suffix: str) -> tuple[dict, str, PolicyRequest]:
    policy_code = f"integrity-policy-{suffix}"
    environment = f"integrity-{suffix}"
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
            ) VALUES (%s, 1, 'active', %s, %s, 'security-test', now())
            """,
            (policy_code, Jsonb(rules), canonical_fingerprint(rules)),
        )
        cursor.execute(
            """
            INSERT INTO capability_flags (
                capability, environment, enabled, kill_switch_active, changed_by, reason
            ) VALUES ('write_draft', %s, true, false, 'security-test', 'integrity test')
            """,
            (environment,),
        )
    connection.commit()
    request = PolicyRequest(
        principal_type="worker",
        principal_id="worker-integrity",
        roles=frozenset({"production_worker"}),
        capability=Capability.WRITE_DRAFT,
        target_type="maitu_room",
        target_id=f"room-{suffix}",
        action="commit",
        environment=environment,
        plan_or_release_hash="a" * 64,
        site_fingerprint="b" * 64,
    )
    return (*PolicyDecisionService(PolicyRepository(connection)).issue_execution_authorization(
        request,
        ttl=timedelta(minutes=5),
        policy_code=policy_code,
    ), request)


def _create_external_effect(connection: psycopg.Connection, suffix: str) -> dict:
    repository = ControlPlaneRepository(connection)
    payload = WorkflowRunCreate.model_validate(
        {
            "workflow_type": "integrity_external_effect",
            "subject_type": "production_variant",
            "subject_code": f"VARIANT-{suffix}",
            "subject_revision": 1,
            "idempotency_key": f"integrity-{suffix}",
            "steps": [
                {
                    "step_key": "write",
                    "step_type": f"write_{suffix}",
                    "idempotency_key": f"write-{suffix}",
                    "side_effect_level": "write_external",
                    "reconcile_strategy": "authoritative_readback",
                    "timeout_seconds": 60,
                    "input_fingerprint": "c" * 64,
                }
            ],
        }
    ).model_dump(mode="json")
    payload["requested_by"] = "operator-integrity"
    repository.create_workflow_run(payload)
    claimed = repository.claim_next_step(
        worker_id="worker-integrity",
        lease_seconds=60,
        accepted_step_types=[f"write_{suffix}"],
    )
    prepared = repository.prepare_external_effect(
        claimed["step_code"],
        worker_id="worker-integrity",
        claim_token=claimed["claim_token"],
        lease_version=claimed["lease_version"],
        target_type="maitu_room",
        target_id=f"room-{suffix}",
        operation_type="write_draft",
        idempotency_key=f"effect-{suffix}",
        plan_or_release_hash="a" * 64,
        request_fingerprint="d" * 64,
    )
    authorized = repository.authorize_external_effect(
        prepared["effect_code"],
        expected_revision=1,
        authorization_code=f"AUTH-INTEGRITY-{suffix}",
        actor_id="worker-integrity",
    )
    committing = repository.begin_external_commit(
        prepared["effect_code"],
        expected_revision=authorized["revision"],
        actor_id="worker-integrity",
    )
    return repository.record_external_commit(
        prepared["effect_code"],
        expected_revision=committing["revision"],
        actor_id="worker-integrity",
        outcome="applied",
        response_summary={"accepted": True},
        external_identity={"draft_id": f"draft-{suffix}"},
    )


def test_authorization_and_external_operation_results_have_valid_hash_chains() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        authorization, token, request = _issue_authorization(connection, suffix)
        PolicyDecisionService(PolicyRepository(connection)).authorize_commit(
            authorization_code=authorization["authorization_code"],
            raw_token=token,
            request=request,
        )
        effect = _create_external_effect(connection, suffix)
        report = IntegrityRepository(connection).verify_hash_chains()
        assert report["failures"] == 0

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type, previous_chain_hash, chain_hash
                FROM execution_authorization_history
                WHERE authorization_code = %s ORDER BY revision
                """,
                (authorization["authorization_code"],),
            )
            history = cursor.fetchall()
            assert [row[0] for row in history] == ["issued", "consumed"]
            assert history[1][1] == history[0][2]
            cursor.execute(
                """
                SELECT evidence FROM workflow_external_effect_history AS history
                JOIN workflow_external_effects AS effect ON effect.id = history.effect_id
                WHERE effect.effect_code = %s AND history.to_phase = 'committed'
                """,
                (effect["effect_code"],),
            )
            evidence = cursor.fetchone()[0]
        assert len(evidence["response_fingerprint"]) == 64
        assert len(evidence["external_identity_fingerprint"]) == 64


def test_integrity_monitor_alerts_for_artifact_damage_duplicates_replay_lag_and_bad_signature() -> None:
    suffix = uuid4().hex
    event_id = uuid4()
    projection_name = f"integrity-projection-{suffix}"
    signing_key = b"integrity-signing-key"

    class BrokenArtifactVerifier:
        def verify_storage(self, artifact_code: str) -> dict:
            return {
                "artifact_code": artifact_code,
                "valid": False,
                "expected_checksum": "a" * 64,
                "stored_checksum": "b" * 64,
                "expected_size": 10,
                "stored_size": 9,
                "version_id": "corrupt-version",
            }

    with psycopg.connect(DATABASE_URL) as connection:
        integrity = IntegrityRepository(connection)
        result = EvidenceIntegrityMonitor(integrity).verify_artifact(
            BrokenArtifactVerifier(), f"ART-{suffix}"
        )
        assert not result["valid"]

        first = integrity.consume_projection_event(
            projection_name=projection_name,
            event_id=str(event_id),
            payload={"value": 1},
        )
        duplicate = integrity.consume_projection_event(
            projection_name=projection_name,
            event_id=str(event_id),
            payload={"value": 1},
        )
        conflict = integrity.consume_projection_event(
            projection_name=projection_name,
            event_id=str(event_id),
            payload={"value": 2},
        )
        assert not first["duplicate"] and duplicate["duplicate"] and conflict["duplicate"]
        with pytest.raises(DomainConflictError) as duplicate_error:
            assert_projection_event_is_new(duplicate)
        assert duplicate_error.value.code == "PROJECTION_EVENT_ALREADY_CONSUMED"

        evidence = EvidenceRepository(connection)
        evidence.enqueue_outbox(
            aggregate_type="content_project",
            aggregate_code=f"CONTENT-{suffix}",
            aggregate_revision=1,
            event_type="content.updated",
            schema_version="content-event.v1",
            payload={"revision": 1},
            occurred_at=datetime.now(UTC),
            trace_id=None,
            event_id=event_id,
        )
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE transactional_outbox_events
                SET publish_attempts = 3, last_error_code = 'BROKER_DOWN'
                WHERE event_id = %s
                """,
                (event_id,),
            )
        connection.commit()
        evidence.advance_projection_checkpoint(
            projection_name=projection_name,
            projection_version="projection.v1",
            event_id=str(event_id),
            watermark_occurred_at=datetime.now(UTC) - timedelta(minutes=10),
            lag_seconds=600,
        )
        counts = integrity.scan_operational_integrity(
            outbox_replay_threshold=3,
            projection_lag_threshold_seconds=60,
        )
        assert counts["outbox"] >= 1 and counts["projection"] >= 1

        sealed = seal_run_manifest(_manifest(7), signing_key=signing_key, key_id=f"integrity-key-{suffix}")
        manifest = evidence.persist_run_manifest(run_code=f"RUN-{suffix}", sealed=sealed)
        signature_report = integrity.verify_signed_manifests(
            signing_keys={f"integrity-key-{suffix}": b"wrong-key"}
        )
        assert signature_report["failures"] >= 1

        alerts = integrity.list_alerts()
        by_subject = {(row["subject_type"], row["subject_code"]): row for row in alerts}
        assert by_subject[("artifact", f"ART-{suffix}")]["reason_code"] == "ARTIFACT_STORAGE_INTEGRITY_INVALID"
        assert by_subject[("projection", projection_name)]["reason_code"] in {
            "PROJECTION_EVENT_PAYLOAD_CONFLICT",
            "PROJECTION_LAG_THRESHOLD_EXCEEDED",
        }
        assert by_subject[("run_manifest", manifest["manifest_code"])]["reason_code"] == (
            "RUN_MANIFEST_INTEGRITY_INVALID"
        )
