from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.contracts import EventEnvelope
from app.domain.errors import DomainValidationError
from app.repositories.data_governance import DataGovernanceRepository
from app.schemas.data_governance import (
    DataContractDefinition,
    MetricRevisionDefinition,
    StandardEventBatchIngest,
)
from app.services.data_governance import DataGovernanceService
from app.services.functional_operations import FunctionalOperationsService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def test_operations_import_descriptive_report_and_planning_conflicts() -> None:
    suffix = uuid4().hex
    start = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(DATABASE_URL) as connection:
        service = FunctionalOperationsService(connection)
        first = service.import_session(
            {
                "title": f"First {suffix}",
                "platform": "douyin",
                "external_session_id": f"external-{suffix}",
                "account_id": "account-1",
                "target_resource_id": "room-1",
                "source_timezone": "Asia/Shanghai",
                "source_evidence": {"kind": "manual_export", "reference": "report.csv"},
                "content_project_code": "CP-ONE",
                "started_at": start,
                "ended_at": start + timedelta(minutes=20),
                "metrics": {"watchers": 100},
            }
        )
        replay = service.import_session(
            {
                "title": "Ignored replay",
                "platform": "douyin",
                "external_session_id": f"external-{suffix}",
                "started_at": start,
                "ended_at": start + timedelta(minutes=20),
                "metrics": {"watchers": 999},
            }
        )
        assert replay["session_code"] == first["session_code"]
        assert replay["source_timezone"] == "Asia/Shanghai"
        assert replay["source_evidence"] == {
            "kind": "manual_export",
            "reference": "report.csv",
        }
        second = service.import_session(
            {
                "title": f"Second {suffix}",
                "platform": "douyin",
                "content_project_code": "CP-ONE",
                "started_at": start + timedelta(days=1),
                "ended_at": start + timedelta(days=1, minutes=20),
                "metrics": {"watchers": 200},
            }
        )
        report = service.create_report(
            {
                "metric_key": "watchers",
                "session_codes": [first["session_code"], second["session_code"]],
            }
        )
        assert report["evidence_level"] == "descriptive"
        assert report["status"] == "insufficient_data"
        assert report["quality_snapshot"]["eligible_for_descriptive_publication"] is False
        assert report["input_snapshot"]["schema_version"] == "functional-attribution-input.v1"
        assert report["fingerprint_sha256"]
        assert report["results"]["metadata"] == {
            "method": "session_metric_grouped_by_source_backed_exposure",
            "metric_grain": "operation_session",
            "selected_session_count": 2,
            "observed_session_count": 0,
            "session_only_count": 2,
            "source_kind_counts": {},
            "release_bound_exposure_count": 0,
            "evidence_level": "descriptive",
            "metric_definition_state": "metric_unpinned",
            "scene_allocation_method": "proportional_by_active_observed_exposure_duration",
            "scene_allocation_count": 0,
        }
        assert report["results"]["scene_allocations"] == []
        assert {
            result["average"] for result in report["results"]["groups"].values()
        } == {100.0, 200.0}
        assert {
            result["scope_type"] for result in report["results"]["groups"].values()
        } == {"session_only"}
        rerun = service.rerun_report(report["report_code"])
        assert rerun["supersedes_report_code"] == report["report_code"]
        assert rerun["fingerprint_sha256"] == report["fingerprint_sha256"]
        with pytest.raises(DomainValidationError) as non_publishable:
            service.publish_descriptive_report(report["report_code"], "operator")
        assert non_publishable.value.code == "ATTRIBUTION_REPORT_NOT_PUBLISHABLE"
        with pytest.raises(DomainValidationError) as invalid_timezone:
            service.import_session(
                {
                    "title": "Bad timezone",
                    "platform": "douyin",
                    "source_timezone": "not-a-zone",
                    "started_at": start,
                    "ended_at": start + timedelta(minutes=1),
                    "metrics": {},
                }
            )
        assert invalid_timezone.value.code == "OPERATION_SESSION_TIMEZONE_INVALID"
        room_id = f"room-{suffix}"
        initial = service.create_schedule(
            {
                "title": "First plan",
                "target_live_room_id": room_id,
                "starts_at": start,
                "duration_minutes": 30,
            }
        )
        conflict = service.create_schedule(
            {
                "title": "Overlap",
                "target_live_room_id": room_id,
                "starts_at": start + timedelta(minutes=15),
                "duration_minutes": 30,
            }
        )
        assert initial["status"] == "planned"
        assert conflict["status"] == "conflict"
        assert conflict["conflict_codes"] == [initial["schedule_code"]]


def test_reviewable_descriptive_report_can_be_published_idempotently() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        service = FunctionalOperationsService(connection)
        report_code = f"ATTR-REVIEW-{suffix}"
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO functional_attribution_reports
                   (report_code, metric_key, evidence_level, session_codes, results, status,
                    input_snapshot, quality_snapshot, fingerprint_sha256)
                   VALUES (%s, 'orders', 'descriptive', '[]'::jsonb, '{}'::jsonb, 'review_required',
                           '{}'::jsonb, %s, %s)""",
                (
                    report_code,
                    Jsonb(
                        {
                            "publication_scope": "descriptive_only",
                            "eligible_for_descriptive_publication": True,
                        }
                    ),
                    "a" * 64,
                ),
            )
        connection.commit()

        published = service.publish_descriptive_report(report_code, "metrics-reviewer")
        repeated = service.publish_descriptive_report(report_code, "other-reviewer")

        assert published["status"] == "published_descriptive"
        assert published["published_by"] == "metrics-reviewer"
        assert published["published_at"] is not None
        assert repeated["published_by"] == "metrics-reviewer"


def test_operations_pin_active_metric_definition_revisions_in_session_and_report() -> None:
    suffix = uuid4().hex
    start = datetime.now(UTC).replace(microsecond=0)
    metric_code = f"orders-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        governance = DataGovernanceService(DataGovernanceRepository(connection))
        metric = governance.put_metric_revision(
            metric_code=metric_code,
            expected_revision=0,
            owner_principal="metrics-owner",
            definition=MetricRevisionDefinition.model_validate(
                {
                    "name": "Completed orders",
                    "description": "Orders after the configured refund window",
                    "grain": "live_session",
                    "unit": "order",
                    "value_type": "integer",
                    "aggregation": "count",
                    "event_time_field": "event_time",
                    "timezone": "Asia/Shanghai",
                    "deduplication_keys": ["order_id"],
                    "null_rule": {"order_id": "reject"},
                    "outlier_rule": {},
                    "event_contract_refs": [{"code": "commerce-orders", "revision": 1}],
                    "schema_compatibility": {},
                    "quality_slo": {},
                }
            ),
            activate=True,
        )
        operations = FunctionalOperationsService(connection)
        session = operations.import_session(
            {
                "title": f"Governed metrics {suffix}",
                "platform": "douyin",
                "external_session_id": f"external-{suffix}",
                "started_at": start,
                "ended_at": start + timedelta(minutes=20),
                "metrics": {"orders": 12},
                "metric_definition_refs": [
                    {
                        "metric_key": "orders",
                        "metric_code": metric_code,
                        "revision_number": metric["revision_number"],
                    }
                ],
            }
        )
        reference = session["metric_definition_refs"][0]
        assert reference["metric_code"] == metric_code
        assert reference["revision_number"] == 1
        assert reference["name"] == "Completed orders"

        governance.put_metric_revision(
            metric_code=metric_code,
            expected_revision=1,
            owner_principal="metrics-owner",
            definition=MetricRevisionDefinition.model_validate(
                {
                    "name": "Completed orders v2",
                    "description": "Orders after the configured refund window",
                    "grain": "live_session",
                    "unit": "order",
                    "value_type": "integer",
                    "aggregation": "count",
                    "event_time_field": "event_time",
                    "timezone": "Asia/Shanghai",
                    "deduplication_keys": ["order_id"],
                    "null_rule": {"order_id": "reject"},
                    "outlier_rule": {},
                    "event_contract_refs": [{"code": "commerce-orders", "revision": 1}],
                    "schema_compatibility": {},
                    "quality_slo": {},
                }
            ),
            activate=True,
        )
        replay = operations.import_session(
            {
                "title": "Ignored source replay",
                "platform": "douyin",
                "external_session_id": f"external-{suffix}",
                "started_at": start,
                "ended_at": start + timedelta(minutes=20),
                "metrics": {"orders": 99},
                "metric_definition_refs": [
                    {
                        "metric_key": "orders",
                        "metric_code": metric_code,
                        "revision_number": 1,
                    }
                ],
            }
        )
        assert replay["session_code"] == session["session_code"]
        assert replay["metric_definition_refs"][0]["revision_number"] == 1

        report = operations.create_report(
            {"metric_key": "orders", "session_codes": [session["session_code"]]}
        )
        assert report["metric_definition_ref"]["fingerprint_sha256"] == metric[
            "fingerprint_sha256"
        ]
        assert report["results"]["metadata"]["metric_definition_state"] == "resolved"


def test_session_time_mapping_is_revisioned_and_bounded_by_session_duration() -> None:
    suffix = uuid4().hex
    start = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(DATABASE_URL) as connection:
        operations = FunctionalOperationsService(connection)
        session = operations.import_session(
            {
                "title": f"Aligned session {suffix}",
                "platform": "douyin",
                "started_at": start,
                "ended_at": start + timedelta(minutes=10),
                "metrics": {},
            }
        )
        first = operations.create_time_mapping(
            session["session_code"],
            {
                "expected_revision": 0,
                "source_clock": "recording_elapsed_ms",
                "source_kind": "recording_anchor",
                "source_offset_ms": 120,
                "drift_ppm": 3.5,
                "coverage_start_ms": 0,
                "coverage_end_ms": 300_000,
                "evidence_note": "Matched the first product scene to the recording.",
                "actor": "operator",
            },
        )
        second = operations.create_time_mapping(
            session["session_code"],
            {
                "expected_revision": 1,
                "source_clock": "recording_elapsed_ms",
                "source_kind": "recording_anchor",
                "source_offset_ms": 150,
                "drift_ppm": 4,
                "coverage_start_ms": 0,
                "coverage_end_ms": 600_000,
                "evidence_note": "Matched opening and closing anchors.",
                "actor": "operator",
            },
        )
        history = operations.list_time_mappings(session["session_code"])
        assert second["revision_number"] == 2
        assert [item["status"] for item in history] == ["active", "superseded"]
        assert history[1]["mapping_code"] == first["mapping_code"]

        with pytest.raises(DomainValidationError) as stale:
            operations.create_time_mapping(
                session["session_code"],
                {
                    "expected_revision": 1,
                    "source_clock": "recording_elapsed_ms",
                    "source_kind": "manual_calibration",
                    "source_offset_ms": 0,
                    "drift_ppm": 0,
                    "coverage_start_ms": 0,
                    "coverage_end_ms": 600_000,
                    "evidence_note": "Stale edit.",
                    "actor": "operator",
                },
            )
        assert stale.value.code == "TIME_MAPPING_REVISION_CONFLICT"

        with pytest.raises(DomainValidationError) as outside:
            operations.create_time_mapping(
                session["session_code"],
                {
                    "expected_revision": 2,
                    "source_clock": "recording_elapsed_ms",
                    "source_kind": "manual_calibration",
                    "source_offset_ms": 0,
                    "drift_ppm": 0,
                    "coverage_start_ms": 0,
                    "coverage_end_ms": 600_001,
                    "evidence_note": "Outside the session.",
                    "actor": "operator",
                },
            )
        assert outside.value.code == "TIME_MAPPING_COVERAGE_OUTSIDE_SESSION"


def test_event_batch_metric_snapshot_is_frozen_and_preferred_by_descriptive_attribution() -> None:
    suffix = uuid4().hex
    contract_code = f"session-orders-{suffix}"
    metric_code = f"session-gmv-{suffix}"
    start = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(DATABASE_URL) as connection:
        governance = DataGovernanceService(DataGovernanceRepository(connection))
        governance.put_contract(
            contract_code=contract_code,
            revision_number=1,
            owner_principal="data-owner",
            activate=True,
            definition=DataContractDefinition.model_validate(
                {
                    "source_system": "commerce-platform",
                    "schema_version": "commerce-event.v1",
                    "json_schema": {
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
                    "lateness_policy": {"max_lateness_seconds": 3600},
                    "compatibility_window": {"accepted_revisions": [1]},
                    "expected_volume": {"events_per_hour": 100},
                    "quality_slo": {"completeness": 0.99},
                }
            ),
        )
        metric = governance.put_metric_revision(
            metric_code=metric_code,
            expected_revision=0,
            owner_principal="metrics-owner",
            activate=True,
            definition=MetricRevisionDefinition.model_validate(
                {
                    "name": "Session GMV",
                    "description": "Accepted order amount within a live session.",
                    "grain": "live_session",
                    "unit": "CNY",
                    "currency": "CNY",
                    "value_type": "currency",
                    "aggregation": "sum",
                    "event_time_field": "event_time",
                    "timezone": "UTC",
                    "deduplication_keys": ["order_id"],
                    "null_rule": {"amount": "reject"},
                    "outlier_rule": {},
                    "event_contract_refs": [
                        {"code": contract_code, "revision": 1}
                    ],
                    "schema_compatibility": {},
                    "quality_slo": {},
                }
            ),
        )
        operations = FunctionalOperationsService(connection)
        session = operations.import_session(
            {
                "title": f"Event metric session {suffix}",
                "platform": "douyin",
                "external_session_id": f"external-{suffix}",
                "started_at": start,
                "ended_at": start + timedelta(minutes=20),
                "metrics": {},
            }
        )
        rows = []
        for index, amount in enumerate((12.5, 7.5), start=1):
            event_time = start + timedelta(minutes=index)
            rows.append(
                {
                    "entity_type": "live_session",
                    "entity_id": session["session_code"],
                    "envelope": EventEnvelope(
                        event_id=uuid4(),
                        source_system="commerce-platform",
                        source_event_id=f"order-{suffix}-{index}",
                        schema_version="commerce-event.v1",
                        operation="upsert",
                        event_time=event_time,
                        processing_time=event_time,
                        payload={"order_id": f"order-{suffix}-{index}", "amount": amount},
                    ),
                }
            )
        batch = governance.ingest_event_batch(
            StandardEventBatchIngest(
                contract_code=contract_code,
                contract_revision=1,
                source_batch_id=f"export-{suffix}",
                rows=rows,
            )
        )
        snapshot = operations.create_session_metric_snapshot(
            session["session_code"],
            {
                "metric_key": "gmv",
                "metric_code": metric_code,
                "revision_number": metric["revision_number"],
                "value_json_pointer": "/amount",
            },
        )
        report = operations.create_report(
            {"metric_key": "gmv", "session_codes": [session["session_code"]]}
        )

        assert batch["status"] == "accepted"
        assert snapshot["status"] == "ready"
        assert float(snapshot["value"]) == 20.0
        assert snapshot["source_event_count"] == 2
        assert snapshot["source_batches"][0]["batch_code"] == batch["batch_code"]
        assert snapshot["fingerprint_sha256"]
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT aggregation, allocation_status, value
                   FROM functional_session_metric_buckets
                   WHERE snapshot_code = %s ORDER BY event_time""",
                (snapshot["snapshot_code"],),
            )
            assert cursor.fetchall() == [("sum", "allocatable", 12.5), ("sum", "allocatable", 7.5)]
        frozen_session = report["input_snapshot"]["sessions"][0]
        assert frozen_session["metric_value"] == 20.0
        assert frozen_session["metric_snapshot"]["snapshot_code"] == snapshot["snapshot_code"]
        assert report["metric_definition_ref"]["metric_code"] == metric_code
