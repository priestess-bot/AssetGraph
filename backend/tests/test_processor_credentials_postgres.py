from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.domain.contracts import DataClassification
from app.domain.errors import DomainAuthorizationError, DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.processor_credentials import CredentialGovernanceService, ExternalProcessorService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _register_processor(service: ExternalProcessorService, suffix: str) -> str:
    code = f"processor-{suffix}"
    service.register(
        processor_code=code,
        revision_number=1,
        activate=True,
        purposes=["model_inference"],
        data_classes=[DataClassification.INTERNAL],
        region="jp-east",
        retention_terms="zero-day API retention; abuse logs excluded by contract v1",
        credential_owner="platform-security",
        rotation_policy="rotate every 30 days and on incident",
        minimum_fields={
            "model_inference": {
                "required": ["goal"],
                "allowed": ["context.locale", "goal"],
            }
        },
        exit_plan="switch the strategy binding to the local provider adapter",
        approved_by="privacy-approver",
    )
    return code


def test_external_processor_projects_minimum_fields_and_audits_denial() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PrivacyGovernanceRepository(connection)
        service = ExternalProcessorService(repository)
        processor_code = _register_processor(service, suffix)

        prepared = service.prepare_payload(
            processor_code=processor_code,
            purpose="model_inference",
            region="jp-east",
            data_classification=DataClassification.INTERNAL,
            payload={
                "goal": "generate a title",
                "context": {"locale": "zh-CN", "debug": "must not leave"},
                "internal_note": "must not leave",
            },
            principal_id="provider-router-test",
        )
        assert prepared.payload == {"goal": "generate a title", "context": {"locale": "zh-CN"}}
        assert prepared.fields_sent == ("context.locale", "goal")

        with pytest.raises(DomainAuthorizationError) as denied:
            service.prepare_payload(
                processor_code=processor_code,
                purpose="model_inference",
                region="us-west",
                data_classification=DataClassification.INTERNAL,
                payload={"goal": "generate a title"},
                principal_id="provider-router-test",
            )
        assert denied.value.code == "EXTERNAL_PROCESSOR_CALL_DENIED"
        assert denied.value.details["reason_codes"] == ["PROCESSOR_REGION_DENIED"]
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT decision, fields_sent, reason_codes
                FROM external_processor_call_audits
                WHERE processor_code = %s ORDER BY occurred_at
                """,
                (processor_code,),
            )
            rows = cursor.fetchall()
        assert rows[0][0] == "allow" and rows[0][1] == ["context.locale", "goal"]
        assert rows[1][0] == "deny" and rows[1][1] == []


def test_credential_registry_marks_due_and_rotates_only_secret_references() -> None:
    suffix = uuid4().hex
    credential_code = f"credential-{suffix}"
    processor_code = f"processor-{suffix}"
    old_ref = f"vault://processors/{suffix}/v1"
    new_ref = f"vault://processors/{suffix}/v2"
    old_rotation = datetime.now(UTC) - timedelta(days=2)
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PrivacyGovernanceRepository(connection)
        _register_processor(ExternalProcessorService(repository), suffix)
        credentials = CredentialGovernanceService(repository)
        registered = credentials.register(
            credential_code=credential_code,
            processor_code=processor_code,
            secret_ref=old_ref,
            allowed_scopes=["model_inference"],
            allowed_regions=["jp-east"],
            credential_owner="platform-security",
            rotation_interval_days=1,
            rotated_at=old_rotation,
            actor_id="credential-manager",
        )
        assert registered["revision"] == 1
        due = repository.refresh_due_credentials(actor_id="credential-scheduler", now=datetime.now(UTC))
        marked = next(item for item in due if item["credential_code"] == credential_code)
        assert marked["status"] == "rotation_due"
        assert marked["revision"] == 2

        rotated = credentials.rotate(
            credential_code,
            expected_revision=2,
            new_secret_ref=new_ref,
            rotated_at=datetime.now(UTC),
            actor_id="credential-manager",
            evidence={"change_ticket": f"SEC-{suffix}"},
        )
        assert rotated["status"] == "active"
        assert rotated["revision"] == 3
        assert rotated["secret_ref"] == new_ref

        with pytest.raises(DomainValidationError) as raw_secret:
            credentials.rotate(
                credential_code,
                expected_revision=3,
                new_secret_ref="sk-abcdefghijklmnopqrstuv",
                rotated_at=datetime.now(UTC),
                actor_id="credential-manager",
                evidence={},
            )
        assert raw_secret.value.code == "CREDENTIAL_SECRET_REF_INVALID"

        revoked = credentials.revoke(
            credential_code,
            expected_revision=3,
            actor_id="credential-manager",
            evidence={"reason": "processor contract ended"},
        )
        assert revoked["status"] == "revoked"
        assert revoked["revision"] == 4
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type, old_secret_ref_fingerprint, new_secret_ref_fingerprint, evidence::text
                FROM credential_rotation_events
                WHERE credential_code = %s ORDER BY revision
                """,
                (credential_code,),
            )
            events = cursor.fetchall()
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'credential_records'
                """
            )
            columns = {row[0] for row in cursor.fetchall()}
        assert [event[0] for event in events] == ["registered", "marked_due", "rotated", "revoked"]
        assert all(old_ref not in str(event) and new_ref not in str(event) for event in events)
        assert "secret_value" not in columns and "credential_value" not in columns
