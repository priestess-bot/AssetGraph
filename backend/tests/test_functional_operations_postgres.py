from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainValidationError
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
