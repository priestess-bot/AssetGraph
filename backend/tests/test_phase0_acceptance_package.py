from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.assemble_phase0_acceptance import (  # noqa: E402
    checklist_gate,
    owner_register_gate,
    regression_gate,
    signoff_gate,
    verify_report_fingerprint,
)


PACKAGE_PATH = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "phase-0-acceptance-package-preparation-2026-07-23.json"
)


def test_preparation_package_is_fingerprinted_and_blocked_on_real_inputs() -> None:
    package = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))

    assert package["schema_version"] == "phase0-acceptance-package.v1"
    assert package["status"] == "blocked"
    assert package["qualifies_for_chk_0296"] is False
    assert package["qualification_gates"] == {
        "checklist_prerequisites_complete": False,
        "phase_owners_assigned": False,
        "capacity_baseline_qualified": False,
        "production_copy_migration_qualified": False,
        "legacy_compatibility_qualified": True,
        "disaster_recovery_qualified": True,
        "full_regression_qualified": True,
        "evidence_archive_complete": True,
        "five_party_signoff_matches_package": False,
    }
    assert verify_report_fingerprint(package)
    assert package["credentials_retained"] is False
    assert package["raw_business_rows_retained"] is False


def test_checklist_gate_reports_only_real_pre_acceptance_blockers() -> None:
    result = checklist_gate(
        REPO_ROOT
        / "docs"
        / "plans"
        / "2026-07-23-live-content-production-operations-implementation-checklist.md"
    )
    assert result["passed"] is False
    assert result["incomplete_usage_controls"] == ["CHK-0002"]
    assert result["incomplete_phase0_prerequisites"] == ["CHK-0110", "CHK-0260"]
    assert result["acceptance_checkbox_currently_checked"] is False
    assert result["archive_checkbox_currently_checked"] is False


def test_owner_and_signoff_examples_are_deliberately_rejected() -> None:
    owner_result = owner_register_gate(
        REPO_ROOT / "docs" / "operations" / "phase-owner-register.v1.example.json"
    )
    assert owner_result["passed"] is False
    assert len(owner_result["errors"]) == 54

    signoff_result = signoff_gate(
        REPO_ROOT
        / "docs"
        / "operations"
        / "phase-0-acceptance-signoff.v1.example.json",
        "f" * 64,
    )
    assert signoff_result["passed"] is False
    assert any(
        "fingerprint does not match" in error for error in signoff_result["errors"]
    )
    assert any("product is not approved" in error for error in signoff_result["errors"])


def test_regression_report_is_complete_and_tamper_evident() -> None:
    path = REPO_ROOT / "docs" / "evidence" / "phase-0-regression-2026-07-23.json"
    result = regression_gate(path)
    assert result["passed"] is True
    assert result["suite_count"] == 13

    report = json.loads(path.read_text(encoding="utf-8"))
    report["suites"][0]["result"] = "fabricated"
    assert verify_report_fingerprint(report) is False
