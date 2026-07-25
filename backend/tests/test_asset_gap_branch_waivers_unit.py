from __future__ import annotations

import pytest

from app.repositories.material_library import MaterialLibraryRepository, MaterialLibraryValidationError


def _gap(status: str = "open") -> dict[str, object]:
    return {
        "gap_code": "AG-GAP-001",
        "title": "需要审核的背景",
        "role": "background",
        "severity": "high",
        "status": status,
        "gap_type": "rights_pending",
        "impact_summary": "影响主背景选择",
        "alternative_asset_codes": ["AG-IMG-ALT"],
        "resolution_asset_code": None,
        "resolution_snapshot": {},
    }


def test_branch_waiver_freezes_an_effective_status_without_mutating_the_library_gap() -> None:
    gap = _gap()

    snapshot = MaterialLibraryRepository._gap_branch_snapshot(gap, "本次活动使用临时审核素材")

    assert gap["status"] == "open"
    assert snapshot["source_status"] == "open"
    assert snapshot["status"] == "waived"
    assert snapshot["branch_waiver"] == {
        "schema_version": "asset-gap-branch-waiver.v1",
        "reason": "本次活动使用临时审核素材",
        "scope": "current_live_room_configuration_revision",
    }


def test_branch_waiver_rejects_a_non_active_gap() -> None:
    with pytest.raises(MaterialLibraryValidationError, match="cannot receive a branch waiver"):
        MaterialLibraryRepository._gap_branch_snapshot(_gap("resolved"), "不应覆盖已经解决的缺口")
