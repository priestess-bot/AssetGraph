from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainValidationError
from app.repositories.data_governance import DataGovernanceRepository
from app.schemas.data_governance import MetricRevisionDefinition
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
        }
        assert {
            result["average"] for result in report["results"]["groups"].values()
        } == {100.0, 200.0}
        assert {
            result["scope_type"] for result in report["results"]["groups"].values()
        } == {"session_only"}
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
