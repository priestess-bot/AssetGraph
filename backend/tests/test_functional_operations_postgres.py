from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.services.functional_operations import FunctionalOperationsService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_operations_import_descriptive_report_and_planning_conflicts() -> None:
    suffix = uuid4().hex
    start = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(DATABASE_URL) as connection:
        service = FunctionalOperationsService(connection)
        first = service.import_session({"title": f"First {suffix}", "platform": "douyin", "content_project_code": "CP-ONE", "started_at": start, "ended_at": start + timedelta(minutes=20), "metrics": {"watchers": 100}})
        second = service.import_session({"title": f"Second {suffix}", "platform": "douyin", "content_project_code": "CP-ONE", "started_at": start + timedelta(days=1), "ended_at": start + timedelta(days=1, minutes=20), "metrics": {"watchers": 200}})
        report = service.create_report({"metric_key": "watchers", "session_codes": [first["session_code"], second["session_code"]]})
        assert report["evidence_level"] == "descriptive"
        assert report["results"]["CP-ONE"] == {"average": 150.0, "sample_size": 2}
        room_id = f"room-{suffix}"
        initial = service.create_schedule({"title": "First plan", "target_live_room_id": room_id, "starts_at": start, "duration_minutes": 30})
        conflict = service.create_schedule({"title": "Overlap", "target_live_room_id": room_id, "starts_at": start + timedelta(minutes=15), "duration_minutes": 30})
        assert initial["status"] == "planned"
        assert conflict["status"] == "conflict"
        assert conflict["conflict_codes"] == [initial["schedule_code"]]
