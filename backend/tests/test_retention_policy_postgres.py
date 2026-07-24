from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.domain.errors import DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.retention import RetentionPolicyService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_six_versioned_retention_classes_match_the_approved_baseline() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PrivacyGovernanceRepository(connection)
        policies = {row["data_class"]: row for row in repository.list_active_retention_policies()}

        assert set(policies) >= {
            "external_raw_capture",
            "raw_personal_event",
            "deidentified_standard_event",
            "aggregate_published_result",
            "critical_audit_evidence",
            "intermediate_artifact",
        }
        assert policies["external_raw_capture"]["retention_days"] == 30
        assert policies["raw_personal_event"]["retention_days"] == 90
        assert policies["deidentified_standard_event"]["retention_days"] == 180
        assert policies["aggregate_published_result"]["retention_days"] is None
        assert policies["critical_audit_evidence"]["retention_days"] is None
        assert policies["intermediate_artifact"]["retention_days"] == 30
        assert all(int(policy["revision_number"]) == 1 for policy in policies.values())


def test_retention_resolution_uses_policy_ranges_and_explicit_indefinite_semantics() -> None:
    created_at = datetime(2026, 7, 23, tzinfo=UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        service = RetentionPolicyService(PrivacyGovernanceRepository(connection))
        personal = service.resolve(
            data_class="raw_personal_event",
            created_at=created_at,
            requested_days=45,
        )
        aggregate = service.resolve(
            data_class="aggregate_published_result",
            created_at=created_at,
        )

        assert personal.policy_code == "raw-personal-event"
        assert personal.policy_revision == 1
        assert personal.expires_at == created_at + timedelta(days=45)
        assert aggregate.retention_days is None
        assert aggregate.expires_at is None

        with pytest.raises(DomainValidationError) as too_long:
            service.resolve(
                data_class="raw_personal_event",
                created_at=created_at,
                requested_days=91,
            )
        assert too_long.value.code == "RETENTION_DURATION_OUT_OF_RANGE"

        with pytest.raises(DomainValidationError) as fixed_override:
            service.resolve(
                data_class="external_raw_capture",
                created_at=created_at,
                requested_days=60,
            )
        assert fixed_override.value.code == "RETENTION_OVERRIDE_DENIED"
