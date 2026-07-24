from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rehearse_disaster_recovery import (  # noqa: E402
    DisasterRecoveryError,
    _safe_workspace,
    re_full_identifier,
    verify_report_fingerprint,
)


def test_disaster_recovery_identifiers_and_workspace_are_fail_closed(tmp_path: Path) -> None:
    assert re_full_identifier("assetgraph_dr_rehearsal")
    assert not re_full_identifier("AssetGraph")
    assert not re_full_identifier("assetgraph-dr")
    assert not re_full_identifier("1assetgraph")

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(DisasterRecoveryError, match="already exists"):
        _safe_workspace(existing)


def test_archived_dr_report_is_complete_fingerprinted_and_non_production() -> None:
    report = json.loads(
        (
            REPO_ROOT
            / "docs"
            / "evidence"
            / "phase-0-disaster-recovery-baseline-2026-07-23-attempt-4.json"
        ).read_text(encoding="utf-8")
    )

    assert report["schema_version"] == "disaster-recovery-rehearsal.v1"
    assert report["status"] == "passed"
    assert report["classification"] == "local_baseline"
    assert report["qualifies_for_chk_0295"] is True
    assert report["database"]["measured_rpo_ms"] >= 0
    assert report["database"]["measured_rto_ms"] > 0
    assert report["database"]["marker_boundary_passed"] is True
    assert report["database"]["pg_verifybackup_passed"] is True
    assert report["database"]["pg_amcheck_passed"] is True
    assert report["database"]["data_checksum_check_passed"] is True
    assert report["object_storage"]["measured_rpo_bytes"] == 0
    assert report["object_storage"]["restore"]["passed"] is True
    assert report["cross_store_validation"]["passed"] is True
    assert report["known_limits"]
    assert verify_report_fingerprint(report)


def test_failed_dr_attempts_never_claim_qualification() -> None:
    evidence_root = REPO_ROOT / "docs" / "evidence"
    failed_reports = [
        evidence_root / "phase-0-disaster-recovery-baseline-2026-07-23.json",
        evidence_root / "phase-0-disaster-recovery-baseline-2026-07-23-attempt-2.json",
        evidence_root / "phase-0-disaster-recovery-baseline-2026-07-23-attempt-3.json",
    ]
    for path in failed_reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["status"] == "failed"
        assert report["qualifies_for_chk_0295"] is False
        assert verify_report_fingerprint(report)
