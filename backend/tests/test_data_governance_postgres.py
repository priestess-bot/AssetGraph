from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from pydantic import ValidationError

from app.domain.contracts import EventEnvelope
from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.data_governance import DataGovernanceRepository
from app.schemas.data_governance import (
    DataContractDefinition,
    EvidenceAssignment,
    MetricRevisionDefinition,
    StandardEventBatchIngest,
    StandardEventIngest,
)
from app.services.data_governance import DataGovernanceService, validate_evidence_assignment


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _contract() -> DataContractDefinition:
    return DataContractDefinition.model_validate(
        {
            "source_system": "ops-platform",
            "schema_version": "commerce-event.v1",
            "json_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "minLength": 1},
                    "amount": {"type": "number", "minimum": 0},
                },
                "required": ["order_id", "amount"],
                "additionalProperties": False,
            },
            "event_id_path": "/event_id",
            "event_time_path": "/event_time",
            "operation_path": "/operation",
            "primary_key_paths": ["/order_id"],
            "upsert_delete_semantics": {
                "allowed_operations": ["insert", "upsert", "delete"],
                "delete_requires_tombstone": True,
            },
            "lateness_policy": {
                "max_lateness_seconds": 3600,
                "max_future_clock_skew_seconds": 60,
            },
            "compatibility_window": {"accepted_revisions": [1]},
            "enum_mappings": {},
            "field_classifications": {"order_id": "confidential"},
            "expected_volume": {"events_per_hour": 1000},
            "quality_slo": {"completeness": 0.999, "max_lag_seconds": 300},
        }
    )


def _event(
    source_event_id: str,
    *,
    event_time: datetime,
    processing_time: datetime,
    payload: dict | None = None,
    schema_version: str = "commerce-event.v1",
) -> StandardEventIngest:
    return StandardEventIngest(
        contract_code="commerce-orders",
        contract_revision=1,
        entity_type="order",
        entity_id=source_event_id,
        envelope=EventEnvelope(
            event_id=uuid4(),
            source_system="ops-platform",
            source_event_id=source_event_id,
            schema_version=schema_version,
            operation="upsert",
            event_time=event_time,
            processing_time=processing_time,
            payload=payload or {"order_id": source_event_id, "amount": 12.5},
        ),
    )


def _metric(name: str) -> MetricRevisionDefinition:
    return MetricRevisionDefinition.model_validate(
        {
            "name": name,
            "description": "Gross merchandise value after the configured refund window",
            "grain": "live_session,business_day",
            "unit": "currency_minor",
            "currency": "CNY",
            "value_type": "currency",
            "aggregation": "sum",
            "event_time_field": "event_time",
            "timezone": "Asia/Shanghai",
            "business_day_boundary": "04:00",
            "dimensions": ["live_session_code", "product_code"],
            "deduplication_keys": ["order_id"],
            "refund_window_days": 14,
            "null_rule": {"amount": "reject"},
            "outlier_rule": {"amount": {"max": 100000000}},
            "event_contract_refs": [{"code": "commerce-orders", "revision": 1}],
            "schema_compatibility": {"minimum": "commerce-event.v1"},
            "quality_slo": {"completeness": 0.999},
        }
    )


def test_contract_ingestion_is_schema_versioned_idempotent_and_quarantines_late_events() -> None:
    suffix = uuid4().hex
    contract_code = f"commerce-orders-{suffix}"
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        service = DataGovernanceService(DataGovernanceRepository(connection))
        contract = service.put_contract(
            contract_code=contract_code,
            revision_number=1,
            owner_principal="data-owner",
            definition=_contract(),
            activate=True,
        )
        request = _event(f"order-{suffix}", event_time=now, processing_time=now)
        request = request.model_copy(update={"contract_code": contract_code})
        accepted = service.ingest_event(request)
        replay = service.ingest_event(request)
        assert accepted["id"] == replay["id"]
        assert accepted["quality_status"] == "accepted"
        assert contract["owner_principal"] == "data-owner"

        changed = _event(
            f"order-{suffix}",
            event_time=now,
            processing_time=now,
            payload={"order_id": f"order-{suffix}", "amount": 99},
        ).model_copy(update={"contract_code": contract_code})
        with pytest.raises(DomainConflictError) as reused:
            service.ingest_event(changed)
        assert reused.value.code == "SOURCE_EVENT_ID_REUSED"

        late = _event(
            f"late-{suffix}",
            event_time=now - timedelta(hours=2),
            processing_time=now,
        ).model_copy(update={"contract_code": contract_code})
        quarantined = service.ingest_event(late)
        assert quarantined["quality_status"] == "quarantined"
        assert quarantined["quarantine_reason"] == "EVENT_TOO_LATE"


def test_unknown_schema_and_invalid_payload_fail_closed_without_zero_filling() -> None:
    suffix = uuid4().hex
    contract_code = f"contract-{suffix}"
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        service = DataGovernanceService(DataGovernanceRepository(connection))
        service.put_contract(
            contract_code=contract_code,
            revision_number=1,
            owner_principal="data-owner",
            definition=_contract(),
            activate=True,
        )
        unknown = _event(
            f"unknown-{suffix}",
            event_time=now,
            processing_time=now,
            schema_version="commerce-event.v2",
        ).model_copy(update={"contract_code": contract_code})
        with pytest.raises(DomainValidationError) as schema:
            service.ingest_event(unknown)
        assert schema.value.code == "DATA_CONTRACT_SCHEMA_VERSION_UNKNOWN"

        invalid = _event(
            f"invalid-{suffix}",
            event_time=now,
            processing_time=now,
            payload={"order_id": f"invalid-{suffix}", "amount": 1, "silent_zero": 0},
        ).model_copy(update={"contract_code": contract_code})
        with pytest.raises(DomainValidationError) as payload:
            service.ingest_event(invalid)
        assert payload.value.code == "DATA_CONTRACT_PAYLOAD_INVALID"
        assert "Additional properties" in payload.value.details["violations"][0]["message"]

        with pytest.raises(ValidationError, match="delete events must be tombstones"):
            EventEnvelope(
                event_id=uuid4(),
                source_system="ops-platform",
                source_event_id=f"delete-{suffix}",
                schema_version="commerce-event.v1",
                operation="delete",
                event_time=now,
                processing_time=now,
                payload={},
                tombstone=False,
            )


def test_event_batches_seal_a_checksum_and_isolate_rejected_rows() -> None:
    suffix = uuid4().hex
    contract_code = f"batch-contract-{suffix}"
    now = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(DATABASE_URL) as connection:
        service = DataGovernanceService(DataGovernanceRepository(connection))
        service.put_contract(
            contract_code=contract_code,
            revision_number=1,
            owner_principal="data-owner",
            definition=_contract(),
            activate=True,
        )
        accepted = _event(
            f"accepted-{suffix}", event_time=now, processing_time=now
        ).model_copy(update={"contract_code": contract_code})
        late = _event(
            f"late-{suffix}",
            event_time=now - timedelta(hours=2),
            processing_time=now,
        ).model_copy(update={"contract_code": contract_code})
        invalid = _event(
            f"invalid-{suffix}",
            event_time=now,
            processing_time=now,
            payload={"order_id": f"invalid-{suffix}", "amount": "invalid"},
        ).model_copy(update={"contract_code": contract_code})
        request = StandardEventBatchIngest(
            contract_code=contract_code,
            contract_revision=1,
            source_batch_id=f"export-{suffix}",
            rows=[
                {
                    "entity_type": accepted.entity_type,
                    "entity_id": accepted.entity_id,
                    "envelope": accepted.envelope,
                },
                {
                    "entity_type": late.entity_type,
                    "entity_id": late.entity_id,
                    "envelope": late.envelope,
                },
                {
                    "entity_type": invalid.entity_type,
                    "entity_id": invalid.entity_id,
                    "envelope": invalid.envelope,
                },
            ],
        )

        batch = service.ingest_event_batch(request)
        replay = service.ingest_event_batch(request)

        assert batch["status"] == "partial_failed"
        assert batch["accepted_count"] == 1
        assert batch["quarantined_count"] == 1
        assert batch["rejected_count"] == 1
        assert batch["source_checksum"]
        assert replay["batch_code"] == batch["batch_code"]
        assert replay["replayed"] is True
        violations = service.list_quality_violations(batch["batch_code"])
        assert len(violations) == 2
        invalid_violation = next(
            item for item in violations
            if item["rule_code"] == "DATA_CONTRACT_PAYLOAD_INVALID"
        )
        assert invalid_violation["field_path"] == "/amount"
        assert invalid_violation["event_id"] == str(invalid.envelope.event_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM standard_events WHERE quality_batch_id IS NOT NULL"
            )
            assert cursor.fetchone()[0] >= 2
            cursor.execute(
                "SELECT count(*) FROM data_quality_violations WHERE batch_id = %s",
                (batch["id"],),
            )
            assert cursor.fetchone()[0] == 2


def test_metric_revisions_require_expected_revision_and_active_rows_are_immutable() -> None:
    suffix = uuid4().hex
    metric_code = f"gmv-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        service = DataGovernanceService(DataGovernanceRepository(connection))
        first = service.put_metric_revision(
            metric_code=metric_code,
            expected_revision=0,
            owner_principal="metrics-owner",
            definition=_metric("GMV v1"),
            activate=True,
        )
        assert first["revision_number"] == 1
        with pytest.raises(DomainConflictError) as conflict:
            service.put_metric_revision(
                metric_code=metric_code,
                expected_revision=0,
                owner_principal="metrics-owner",
                definition=_metric("conflicting definition"),
                activate=True,
            )
        assert conflict.value.code == "METRIC_REVISION_CONFLICT"
        second = service.put_metric_revision(
            metric_code=metric_code,
            expected_revision=1,
            owner_principal="metrics-owner",
            definition=_metric("GMV v2"),
            activate=True,
        )
        assert second["revision_number"] == 2
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revision_number, status FROM metric_definition_revisions
                WHERE metric_code = %s ORDER BY revision_number
                """,
                (metric_code,),
            )
            assert cursor.fetchall() == [(1, "superseded"), (2, "active")]
        with pytest.raises(psycopg.errors.RaiseException, match="immutable catalog revision"):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE metric_definition_revisions SET description = 'tampered'
                    WHERE metric_code = %s AND revision_number = 2
                    """,
                    (metric_code,),
                )
        connection.rollback()


def test_evidence_level_cannot_be_manually_or_methodologically_promoted() -> None:
    assert (
        validate_evidence_assignment(
            EvidenceAssignment(
                declared_level="associational",
                method="regression",
            )
        ).value
        == "associational"
    )
    with pytest.raises(DomainValidationError) as unsupported:
        validate_evidence_assignment(
            EvidenceAssignment(
                declared_level="randomized",
                method="cohort_comparison",
            )
        )
    assert unsupported.value.code == "EVIDENCE_LEVEL_UNSUPPORTED"
    with pytest.raises(DomainValidationError) as allocation:
        validate_evidence_assignment(
            EvidenceAssignment(
                declared_level="randomized",
                method="randomized_experiment",
                allocation_evidence={"randomized": True, "srm_check_passed": False},
            )
        )
    assert allocation.value.code == "RANDOMIZATION_EVIDENCE_INCOMPLETE"
