from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_legacy_compatibility import (  # noqa: E402
    _cardinality_audit,
    _migration_audit,
    _relation_guard_audit,
    _sql_assertions,
    verify_report_fingerprint,
)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "phase-0-legacy-compatibility-audit-2026-07-23.json"
)


def test_archived_compatibility_report_is_fingerprinted_and_qualifying() -> None:
    report_text = REPORT_PATH.read_text(encoding="utf-8")
    report = json.loads(report_text)

    assert report["schema_version"] == "legacy-compatibility-audit.v1"
    assert report["status"] == "passed"
    assert report["classification"] == "representative_integration_database"
    assert report["qualifies_for_chk_0294"] is True
    assert report["raw_business_rows_retained"] is False
    assert report["credentials_retained"] is False
    assert report["relation_guards"]["passed"] is True
    assert report["cardinality"]["representative_sample_coverage"]["passed"] is True
    assert report["api_audit"]["passed"] is True
    assert report["canonical_fact_write_check"]["passed"] is True
    assert all(item["passed"] for item in report["semantic_assertions"])
    assert verify_report_fingerprint(report)
    assert "console-local-test" not in report_text
    assert "postgresql://" not in report_text


def test_compatibility_report_fingerprint_detects_tampering() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report["status"] = "failed"
    assert verify_report_fingerprint(report) is False


@pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)
def test_live_database_compatibility_invariants_and_cardinality_hold() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        migration = _migration_audit(connection)
        guards = _relation_guard_audit(connection)
        cardinality = _cardinality_audit(connection)
        assertions = _sql_assertions(connection)

    assert migration["passed"] is True
    assert guards["passed"] is True
    assert cardinality["passed"] is True
    assert all(assertion["passed"] for assertion in assertions)
