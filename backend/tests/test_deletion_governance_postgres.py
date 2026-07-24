from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainAuthorizationError, DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.deletion_governance import DeletionGovernanceService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_legal_hold_blocks_then_append_only_retry_receipts_reach_completion() -> None:
    suffix = uuid4().hex
    subject_code = f"person-{suffix}"
    target = {
        "target_type": "personal_event",
        "target_code": f"event-{suffix}",
        "source_system": "douyin",
    }
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PrivacyGovernanceRepository(connection)
        service = DeletionGovernanceService(repository)
        hold = service.create_legal_hold(
            subject_type="person",
            subject_code=subject_code,
            scope={"all_personal_data": True},
            reason="Active investigation",
            evidence_refs=[{"artifact_code": f"ART-{suffix}"}],
            owner_principal="legal-owner",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        run = service.request_deletion(
            subject_type="person",
            subject_code=subject_code,
            targets=[target],
            required_processors=["postgres", "object_storage"],
            requested_by="privacy-requester",
        )

        blocked = repository.validate_deletion_run(
            run["deletion_run_code"],
            expected_revision=1,
            actor_id="privacy-requester",
        )
        assert blocked["status"] == "blocked_by_legal_hold"
        assert blocked["revision"] == 3
        assert blocked["legal_hold_snapshot"][0]["hold_code"] == hold["hold_code"]

        repository.release_legal_hold(
            hold["hold_code"],
            expected_revision=1,
            actor_id="legal-owner",
            evidence={"reason": "investigation closed"},
        )
        approved = repository.validate_deletion_run(
            run["deletion_run_code"],
            expected_revision=3,
            actor_id="privacy-approver",
        )
        assert approved["status"] == "approved"
        assert approved["approved_by"] == "privacy-approver"

        executing = repository.start_deletion_run(
            run["deletion_run_code"],
            expected_revision=5,
            actor_id="deletion-worker",
        )
        assert executing["revision"] == 6
        service.record_receipt(
            run["deletion_run_code"],
            processor="postgres",
            target_type=target["target_type"],
            target_code=target["target_code"],
            outcome="deleted",
            retention_basis=None,
            evidence={"row_count": 1},
        )
        service.record_receipt(
            run["deletion_run_code"],
            processor="object_storage",
            target_type=target["target_type"],
            target_code=target["target_code"],
            outcome="failed",
            retention_basis=None,
            evidence={"error_code": "STORE_UNAVAILABLE"},
        )
        partial = repository.verify_deletion_run(
            run["deletion_run_code"],
            expected_revision=6,
            actor_id="deletion-verifier",
        )
        assert partial["status"] == "partial_failed"
        assert partial["revision"] == 8
        assert partial["retry_count"] == 1
        assert partial["next_retry_at"] is not None
        assert partial["escalated_at"] is not None

        repository.start_deletion_run(
            run["deletion_run_code"],
            expected_revision=8,
            actor_id="deletion-worker",
        )
        retried = service.record_receipt(
            run["deletion_run_code"],
            processor="object_storage",
            target_type=target["target_type"],
            target_code=target["target_code"],
            outcome="deleted",
            retention_basis=None,
            evidence={"object_versions_deleted": 2},
        )
        assert retried["attempt"] == 2
        completed = repository.verify_deletion_run(
            run["deletion_run_code"],
            expected_revision=9,
            actor_id="deletion-verifier",
        )
        assert completed["status"] == "completed"
        assert completed["revision"] == 11
        assert [item["to_status"] for item in completed["history"]] == [
            "requested",
            "validating",
            "blocked_by_legal_hold",
            "validating",
            "approved",
            "executing",
            "verifying",
            "partial_failed",
            "executing",
            "verifying",
            "completed",
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM data_tombstones WHERE subject_code = %s",
                (target["target_code"],),
            )
            assert cursor.fetchone()[0] == 1


def test_deletion_self_approval_and_sensitive_receipt_evidence_fail_closed() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PrivacyGovernanceRepository(connection)
        service = DeletionGovernanceService(repository)
        run = service.request_deletion(
            subject_type="person",
            subject_code=f"person-{suffix}",
            targets=[
                {
                    "target_type": "personal_event",
                    "target_code": f"event-{suffix}",
                    "source_system": "douyin",
                }
            ],
            required_processors=["postgres"],
            requested_by="same-person",
        )
        with pytest.raises(DomainAuthorizationError) as self_approval:
            repository.validate_deletion_run(
                run["deletion_run_code"],
                expected_revision=1,
                actor_id="same-person",
            )
        assert self_approval.value.code == "DELETION_SELF_APPROVAL_DENIED"
        assert repository.get_deletion_run(run["deletion_run_code"])["status"] == "requested"

        approved = repository.validate_deletion_run(
            run["deletion_run_code"],
            expected_revision=1,
            actor_id="different-approver",
        )
        repository.start_deletion_run(
            run["deletion_run_code"],
            expected_revision=approved["revision"],
            actor_id="deletion-worker",
        )
        with pytest.raises(DomainValidationError) as sensitive:
            service.record_receipt(
                run["deletion_run_code"],
                processor="postgres",
                target_type="personal_event",
                target_code=f"event-{suffix}",
                outcome="deleted",
                retention_basis=None,
                evidence={"token": "must-not-persist"},
            )
        assert sensitive.value.code == "DELETION_RECEIPT_EVIDENCE_SENSITIVE"
