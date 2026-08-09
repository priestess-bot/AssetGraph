from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.evidence import EvidenceRepository
from app.repositories.releases import ReleaseRepository
from app.services.releases import ReleaseService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _artifact(repository: EvidenceRepository, suffix: str) -> dict:
    return repository.register_artifact(
        artifact_kind="release_test",
        media_type="application/json",
        schema_version="artifact.v1",
        storage_uri=f"s3://release-test/{suffix}",
        checksum_sha256=suffix.ljust(64, "0"),
        byte_size=10,
        producer_type="workflow_run",
        producer_code=f"RUN-{suffix}",
        producer_revision=1,
        sensitivity="internal",
        retention_policy_code="test",
        encryption_key_ref=None,
        metadata={},
    )


def _candidate(
    service: ReleaseService,
    artifact: dict,
    suffix: str,
    *,
    quality_status: str = "pass",
    carrier_kind: str = "live_room_draft",
) -> dict:
    return service.create_candidate(
        subject_type="production_variant",
        subject_code=f"VARIANT-{suffix}",
        subject_revision=1,
        carrier_kind=carrier_kind,
        subject_refs={
            "content_project_revision": {"code": f"CONTENT-{suffix}", "revision": 1},
            "production_variant_revision": {"code": f"VARIANT-{suffix}", "revision": 1},
            "story_brief_revision": {"code": f"STORY-{suffix}", "revision": 1},
            "script_revision": {"code": f"SCRIPT-{suffix}", "revision": 1},
            "program_revision": {"code": f"PROGRAM-{suffix}", "revision": 1},
            "shot_list_revision": {"code": f"SHOTS-{suffix}", "revision": 1},
        },
        artifact_refs=[
            {
                "artifact_code": artifact["artifact_code"],
                "checksum_sha256": artifact["checksum_sha256"],
                "role": "build_plan",
            }
        ],
        rights_snapshot={"status": "valid", "snapshot_revision": 1},
        quality_snapshot={
            "gates": [{"code": "preflight", "status": quality_status, "blocking": True}]
        },
        lineage_snapshot={"complete": True, "edge_count": 3},
        carrier_facet={
            (
                "production_timeline_ref"
                if carrier_kind == "rendered_video"
                else "build_plan_ref"
            ): {"code": f"PLAN-{suffix}", "revision": 1}
        },
        created_by="producer-a",
    )


def test_release_validation_approval_delivery_and_exposure_are_independent_facts() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        release_repository = ReleaseRepository(connection)
        service = ReleaseService(
            release_repository,
            signing_key=b"release-test-signing-key",
            signing_key_id="release-test-key",
        )
        artifact = _artifact(EvidenceRepository(connection), suffix)
        candidate = _candidate(service, artifact, suffix)
        replay = _candidate(service, artifact, suffix)
        assert candidate["release_code"] == replay["release_code"]
        assert candidate["status"] == "candidate"
        assert service.verify_manifest_signature(candidate["release_code"])
        wrong_key_service = ReleaseService(
            release_repository,
            signing_key=b"wrong-signing-key",
            signing_key_id="release-test-key",
        )
        assert not wrong_key_service.verify_manifest_signature(candidate["release_code"])

        awaiting = service.validate_candidate(candidate["release_code"], actor_id="validator-a")
        assert awaiting["status"] == "awaiting_approval"
        with pytest.raises(DomainValidationError) as self_approval:
            release_repository.add_approval(
                candidate["release_code"],
                decision="approve",
                structured_reason={"reason_code": "ALL_GATES_PASS"},
                approved_scope={},
                decided_by="producer-a",
            )
        assert self_approval.value.code == "RELEASE_SELF_APPROVAL_FORBIDDEN"
        approval = release_repository.add_approval(
            candidate["release_code"],
            decision="approve",
            structured_reason={"reason_code": "ALL_GATES_PASS"},
            approved_scope={"target_type": "maitu_room"},
            decided_by="approver-b",
        )
        assert approval["decision"] == "approve"
        approved = release_repository.get_release(candidate["release_code"])
        assert approved is not None and approved["status"] == "approved"
        assert approved["deliveries"] == []

        with pytest.raises(DomainConflictError) as early_exposure:
            release_repository.append_exposure(
                release_code=candidate["release_code"],
                source_system="maitu_readback",
                source_event_id=f"early-{suffix}",
                live_session_code=f"SESSION-{suffix}",
                external_session_id=None,
                exposed_content_type="shot",
                exposed_content_code=f"SHOT-{suffix}",
                exposed_content_revision=1,
                start_ms=0,
                end_ms=1000,
                event_time=datetime.now(UTC),
                time_mapping_revision="mapping.v1",
                source_evidence={"artifact_code": artifact["artifact_code"]},
                confidence=1,
            )
        assert early_exposure.value.code == "EXPOSURE_RELEASE_NOT_DELIVERED"

        delivery = release_repository.create_delivery_attempt(
            candidate["release_code"],
            target_type="maitu_room",
            target_id=f"room-{suffix}",
            adapter_type="maitu_authoritative_api",
            idempotency_key=f"delivery-{suffix}",
            authorization_id=None,
            request_summary={"manifest_code": candidate["manifest"]["manifest_code"]},
        )
        replay_delivery = release_repository.create_delivery_attempt(
            candidate["release_code"],
            target_type="maitu_room",
            target_id=f"room-{suffix}",
            adapter_type="maitu_authoritative_api",
            idempotency_key=f"delivery-{suffix}",
            authorization_id=None,
            request_summary={},
        )
        assert replay_delivery["delivery_code"] == delivery["delivery_code"]
        release_repository.transition_delivery(
            delivery["delivery_code"], expected_status="prepared", target_status="authorized"
        )
        release_repository.transition_delivery(
            delivery["delivery_code"], expected_status="authorized", target_status="committing"
        )
        with pytest.raises(DomainValidationError) as no_readback:
            release_repository.transition_delivery(
                delivery["delivery_code"], expected_status="committing", target_status="succeeded"
            )
        assert no_readback.value.code == "DELIVERY_READBACK_REQUIRED"
        succeeded = release_repository.transition_delivery(
            delivery["delivery_code"],
            expected_status="committing",
            target_status="succeeded",
            response_summary={"status": "ok"},
            external_identity={"room_id": f"room-{suffix}", "draft_id": f"draft-{suffix}"},
            readback_evidence={"scene_count": 3, "matches_manifest": True},
        )
        assert succeeded["status"] == "succeeded"
        delivered = release_repository.get_release(candidate["release_code"])
        assert delivered is not None and delivered["status"] == "delivered"

        exposure = release_repository.append_exposure(
            release_code=candidate["release_code"],
            source_system="maitu_readback",
            source_event_id=f"exposure-{suffix}",
            live_session_code=f"SESSION-{suffix}",
            external_session_id=f"external-{suffix}",
            exposed_content_type="shot",
            exposed_content_code=f"SHOT-{suffix}",
            exposed_content_revision=1,
            start_ms=0,
            end_ms=1000,
            event_time=datetime.now(UTC),
            time_mapping_revision="mapping.v1",
            source_evidence={"readback": succeeded["readback_evidence"]},
            confidence=1,
        )
        assert exposure["live_session_code"] == f"SESSION-{suffix}"

        summaries = release_repository.list_releases()
        summary = next(item for item in summaries if item["release_code"] == candidate["release_code"])
        assert summary["subject_type"] == "production_variant"
        assert summary["subject_code"] == f"VARIANT-{suffix}"
        assert summary["status"] == "delivered"
        assert summary["manifest_code"] == candidate["manifest"]["manifest_code"]
        assert summary["delivery_count"] == 1

        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM releases WHERE release_code = %s", (candidate["release_code"],))
            release_count = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT count(*) FROM delivery_attempts AS delivery
                JOIN releases AS release ON release.id = delivery.release_id
                WHERE release.release_code = %s
                """,
                (candidate["release_code"],),
            )
            delivery_count = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT count(*) FROM content_exposure_events AS exposure
                JOIN release_manifests AS manifest ON manifest.id = exposure.release_manifest_id
                WHERE manifest.release_code = %s
                """,
                (candidate["release_code"],),
            )
            exposure_count = cursor.fetchone()[0]
        assert (release_count, delivery_count, exposure_count) == (1, 1, 1)


def test_list_releases_filters_live_room_and_video_candidates_by_project() -> None:
    live_suffix = uuid4().hex
    video_suffix = uuid4().hex
    foreign_suffix = uuid4().hex
    unassociated_suffix = uuid4().hex
    project_code = f"CONTENT-{uuid4().hex}"
    foreign_project_code = f"CONTENT-{uuid4().hex}"

    with psycopg.connect(DATABASE_URL) as connection:
        release_repository = ReleaseRepository(connection)
        service = ReleaseService(
            release_repository,
            signing_key=b"release-test-signing-key",
            signing_key_id="release-test-key",
        )
        evidence = EvidenceRepository(connection)
        live_release = _candidate(service, _artifact(evidence, live_suffix), live_suffix)
        video_release = _candidate(
            service,
            _artifact(evidence, video_suffix),
            video_suffix,
            carrier_kind="rendered_video",
        )
        foreign_release = _candidate(service, _artifact(evidence, foreign_suffix), foreign_suffix)
        unassociated_release = _candidate(
            service,
            _artifact(evidence, unassociated_suffix),
            unassociated_suffix,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO functional_live_room_plans (
                    plan_code, project_code, variant_code, configuration_code,
                    target_live_room_id, expected_title, blueprint, build_plan,
                    status, release_code
                )
                VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb, 'ready', %s)
                """,
                (
                    f"LIVEPLAN-{live_suffix}",
                    project_code,
                    f"VARIANT-{live_suffix}",
                    f"CONFIG-{live_suffix}",
                    f"ROOM-{live_suffix}",
                    "Project live-room release",
                    live_release["release_code"],
                ),
            )
            cursor.execute(
                "INSERT INTO video_production_jobs (job_code, topic) VALUES (%s, %s)",
                (f"JOB-{video_suffix}", "Project rendered-video release"),
            )
            cursor.execute(
                """
                INSERT INTO functional_video_plans (
                    plan_code, project_code, variant_code, video_job_code,
                    title, production_timeline, render_profile, release_code
                )
                VALUES (%s, %s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb, %s)
                """,
                (
                    f"VIDEOPLAN-{video_suffix}",
                    project_code,
                    f"VARIANT-{video_suffix}",
                    f"JOB-{video_suffix}",
                    "Project rendered-video release",
                    video_release["release_code"],
                ),
            )
            cursor.execute(
                """
                INSERT INTO functional_live_room_plans (
                    plan_code, project_code, variant_code, configuration_code,
                    target_live_room_id, expected_title, blueprint, build_plan,
                    status, release_code
                )
                VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb, 'ready', %s)
                """,
                (
                    f"LIVEPLAN-{foreign_suffix}",
                    foreign_project_code,
                    f"VARIANT-{foreign_suffix}",
                    f"CONFIG-{foreign_suffix}",
                    f"ROOM-{foreign_suffix}",
                    "Foreign live-room release",
                    foreign_release["release_code"],
                ),
            )
        connection.commit()

        scoped_codes = {
            release["release_code"]
            for release in release_repository.list_releases(project_code=project_code)
        }
        assert scoped_codes == {live_release["release_code"], video_release["release_code"]}
        assert {
            release["release_code"]
            for release in release_repository.list_releases(project_code=foreign_project_code)
        } == {foreign_release["release_code"]}
        assert unassociated_release["release_code"] not in scoped_codes


def test_stale_delivery_callbacks_cannot_overwrite_revoked_or_delivered_releases() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ReleaseRepository(connection)
        service = ReleaseService(repository, signing_key=b"release-test-signing-key", signing_key_id="release-test-key")

        candidate = _candidate(service, _artifact(EvidenceRepository(connection), suffix), suffix)
        service.validate_candidate(candidate["release_code"], actor_id="validator-a")
        repository.add_approval(
            candidate["release_code"],
            decision="approve",
            structured_reason={"reason_code": "ALL_GATES_PASS"},
            approved_scope={"target_type": "maitu_room"},
            decided_by="approver-b",
        )
        first = repository.create_delivery_attempt(
            candidate["release_code"],
            target_type="maitu_room",
            target_id=f"room-first-{suffix}",
            adapter_type="maitu_authoritative_api",
            idempotency_key=f"delivery-first-{suffix}",
            authorization_id=None,
            request_summary={},
        )
        second = repository.create_delivery_attempt(
            candidate["release_code"],
            target_type="maitu_room",
            target_id=f"room-second-{suffix}",
            adapter_type="maitu_authoritative_api",
            idempotency_key=f"delivery-second-{suffix}",
            authorization_id=None,
            request_summary={},
        )
        for delivery in (first, second):
            repository.transition_delivery(delivery["delivery_code"], expected_status="prepared", target_status="authorized")
            repository.transition_delivery(delivery["delivery_code"], expected_status="authorized", target_status="committing")

        repository.transition_delivery(
            first["delivery_code"],
            expected_status="committing",
            target_status="succeeded",
            external_identity={"room_id": f"room-first-{suffix}"},
            readback_evidence={"matches_manifest": True},
        )
        with pytest.raises(DomainConflictError) as delivered_conflict:
            repository.transition_delivery(
                second["delivery_code"],
                expected_status="committing",
                target_status="failed",
                error_code="STALE_CALLBACK",
            )
        assert delivered_conflict.value.code == "DELIVERY_RELEASE_STATUS_CONFLICT"
        delivered = repository.get_release(candidate["release_code"])
        assert delivered is not None and delivered["status"] == "delivered"
        assert {item["delivery_code"]: item["status"] for item in delivered["deliveries"]} == {
            first["delivery_code"]: "succeeded",
            second["delivery_code"]: "committing",
        }

        revoked_suffix = uuid4().hex
        revoked_candidate = _candidate(
            service,
            _artifact(EvidenceRepository(connection), revoked_suffix),
            revoked_suffix,
        )
        service.validate_candidate(revoked_candidate["release_code"], actor_id="validator-a")
        repository.add_approval(
            revoked_candidate["release_code"],
            decision="approve",
            structured_reason={"reason_code": "ALL_GATES_PASS"},
            approved_scope={"target_type": "maitu_room"},
            decided_by="approver-b",
        )
        revoked_delivery = repository.create_delivery_attempt(
            revoked_candidate["release_code"],
            target_type="maitu_room",
            target_id=f"room-revoked-{revoked_suffix}",
            adapter_type="maitu_authoritative_api",
            idempotency_key=f"delivery-revoked-{revoked_suffix}",
            authorization_id=None,
            request_summary={},
        )
        repository.transition_delivery(
            revoked_delivery["delivery_code"], expected_status="prepared", target_status="authorized"
        )
        repository.transition_delivery(
            revoked_delivery["delivery_code"], expected_status="authorized", target_status="committing"
        )
        repository.transition_release(
            revoked_candidate["release_code"],
            expected_status="delivery_pending",
            target_status="revoked",
            actor_id="release-operator",
            reason_code="RELEASE_REVOKED",
            evidence={"reason": "operator revocation"},
        )
        with pytest.raises(DomainConflictError) as revoked_conflict:
            repository.transition_delivery(
                revoked_delivery["delivery_code"],
                expected_status="committing",
                target_status="succeeded",
                external_identity={"room_id": f"room-revoked-{revoked_suffix}"},
                readback_evidence={"matches_manifest": True},
            )
        assert revoked_conflict.value.code == "DELIVERY_RELEASE_STATUS_CONFLICT"
        revoked = repository.get_release(revoked_candidate["release_code"])
        assert revoked is not None and revoked["status"] == "revoked"
        assert revoked["deliveries"][0]["status"] == "committing"


def test_release_gate_failure_returns_candidate_and_latest_reference_is_forbidden() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ReleaseRepository(connection)
        service = ReleaseService(repository, signing_key=b"key", signing_key_id="key-id")
        artifact = _artifact(EvidenceRepository(connection), suffix)
        blocked = _candidate(service, artifact, suffix, quality_status="blocked")
        with pytest.raises(DomainValidationError) as gate:
            service.validate_candidate(blocked["release_code"], actor_id="validator-a")
        assert gate.value.code == "RELEASE_GATE_FAILED"
        assert repository.get_release(blocked["release_code"])["status"] == "candidate"

        with pytest.raises(DomainValidationError) as latest:
            service.create_candidate(
                subject_type="production_variant",
                subject_code=f"VARIANT-{suffix}-latest",
                subject_revision=1,
                carrier_kind="live_room_draft",
                subject_refs={key: {"code": "latest", "revision": 1} for key in (
                    "content_project_revision",
                    "production_variant_revision",
                    "story_brief_revision",
                    "script_revision",
                    "program_revision",
                    "shot_list_revision",
                )},
                artifact_refs=[
                    {
                        "artifact_code": artifact["artifact_code"],
                        "checksum_sha256": artifact["checksum_sha256"],
                    }
                ],
                rights_snapshot={"status": "valid"},
                quality_snapshot={"gates": [{"code": "all", "status": "pass"}]},
                lineage_snapshot={"complete": True},
                carrier_facet={"build_plan_ref": {"code": "PLAN-1", "revision": 1}},
                created_by="producer-a",
            )
        assert latest.value.code == "RELEASE_LATEST_REFERENCE_FORBIDDEN"


def test_illegal_release_transition_is_denied_with_append_only_audit() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ReleaseRepository(connection)
        service = ReleaseService(repository, signing_key=b"key", signing_key_id="key-id")
        candidate = _candidate(service, _artifact(EvidenceRepository(connection), suffix), suffix)

        with pytest.raises(DomainConflictError) as invalid:
            repository.transition_release(
                candidate["release_code"],
                expected_status="candidate",
                target_status="delivered",
                actor_id="operator-a",
                reason_code="INVALID_SKIP",
                evidence={},
            )
        assert invalid.value.code == "STATE_TRANSITION_NOT_ALLOWED"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, outcome, reason_code, details FROM audit_events
                WHERE target_type = 'release' AND target_code = %s
                ORDER BY occurred_at DESC LIMIT 1
                """,
                (candidate["release_code"],),
            )
            audit = cursor.fetchone()
        assert audit[1:] == (
            "denied",
            "STATE_TRANSITION_NOT_ALLOWED",
            {
                "machine": "release",
                "current": "candidate",
                "requested_target": "delivered",
                "allowed": ["revoked", "validating"],
            },
        )
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM audit_events WHERE id = %s", (audit[0],))
        connection.rollback()
