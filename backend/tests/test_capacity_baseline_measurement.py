from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.measure_capacity_baseline import (  # noqa: E402
    load_capacity_input,
    measure_database,
    verify_report_fingerprint,
)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "phase-0-capacity-baseline-integration-2026-07-23.json"
)


def test_integration_capacity_report_can_never_qualify_for_chk_0110() -> None:
    report_text = REPORT_PATH.read_text(encoding="utf-8")
    report = json.loads(report_text)

    assert report["schema_version"] == "capacity-baseline-report.v1"
    assert report["status"] == "passed"
    assert report["classification"] == "representative_integration_database"
    assert report["qualifies_for_chk_0110"] is False
    assert report["qualification_gates"]["operational_classification"] is False
    assert report["qualification_gates"]["source_snapshot_attested"] is False
    assert report["qualification_gates"]["approved_capacity_input"] is False
    assert report["qualification_gates"]["object_storage_reconciled"] is False
    assert report["credentials_retained"] is False
    assert report["raw_business_rows_retained"] is False
    assert verify_report_fingerprint(report)
    assert "postgresql://" not in report_text


def test_capacity_input_example_is_deliberately_non_approvable() -> None:
    payload, errors = load_capacity_input(
        REPO_ROOT / "docs" / "operations" / "capacity-baseline-input.v1.example.json"
    )
    assert payload is not None
    assert errors
    assert any("positive integer" in error for error in errors)
    assert any("approved owner/decision_ref" in error for error in errors)


def test_complete_capacity_input_contract_is_accepted(tmp_path: Path) -> None:
    contract = {
        "schema_version": "capacity-baseline-input.v1",
        "configured_limits": {
            "live_capture_concurrency": 2,
            "live_session_concurrency": 2,
            "render_concurrency": 1,
            "browser_use_concurrency": 1,
            "workflow_worker_concurrency": 4,
        },
        "forecast": {
            signal: {
                "annual_growth_rate": 0.2,
                "peak_factor": 2.0,
                "source_ref": f"FORECAST-{signal}",
            }
            for signal in (
                "assets",
                "recording_hours",
                "events",
                "artifacts_bytes",
                "workflows",
            )
        },
        "unit_costs": [
            {
                "cost_code": "storage_gib_month",
                "amount": 0.1,
                "currency": "CNY",
                "unit": "GiB-month",
                "source_ref": "QUOTE-001",
            }
        ],
        "thresholds": [
            {
                "signal": "artifact_bytes",
                "warning": 80,
                "stop": 100,
                "owner": "operations-owner",
                "decision_ref": "THRESHOLD-001",
            }
        ],
        "approvals": {
            role: {
                "owner": f"{role}-owner",
                "decision": "approved",
                "decision_ref": f"APPROVAL-{role}",
            }
            for role in ("engineering", "data", "operations")
        },
    }
    path = tmp_path / "capacity-input.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    payload, errors = load_capacity_input(path)
    assert payload == contract
    assert errors == []


@pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)
def test_capacity_collector_reads_all_required_database_domains() -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SELECT current_database()")
            expected_database = cursor.fetchone()[0]
        measurement = measure_database(
            connection,
            expected_database=expected_database,
            window_start=datetime(2026, 7, 1, tzinfo=UTC),
            window_end=datetime(2026, 7, 24, tzinfo=UTC),
        )
        connection.rollback()

    assert measurement["window"]["interval_semantics"] == "half-open [start,end)"
    assert {
        "assets",
        "recordings",
        "events",
        "live_sessions",
        "renders",
        "artifacts",
        "workflows",
        "browser_use",
    } <= measurement.keys()
    assert measurement["assets"]["totals"]["total_rows"] >= 0
    assert measurement["events"]["standard_events_exact"]["peak_event_time_eps"] >= 0
    assert measurement["browser_use"]["historical_limit"] is None
