from __future__ import annotations

from datetime import UTC, datetime

from app.services.functional_live_rooms import FunctionalLiveRoomService


HANDOFF = {
    "plan_code": "LIVEPLAN-001",
    "build_plan_code": "MT-BUILD-001",
    "target_live_room_id": "empty-draft-001",
    "checkpoint_contract": "script_layout_checkpoint_v1",
    "source_plan_fingerprint": "a" * 64,
    "operation_count": 2,
    "operation_types": ["preflight_content_build_plan", "fill_default_scene"],
}


def _execution(*, source_fingerprint: str = "a" * 64) -> dict:
    return {
        "execution_code": "MT-EXEC-001",
        "execution_status": "completed",
        "checkpoint_contract": "script_layout_checkpoint_v1",
        "mode": "script_layout_draft",
        "expected_operation_count": 2,
        "finalized_at": datetime(2026, 7, 25, tzinfo=UTC),
        "finished_at": datetime(2026, 7, 25, 1, tzinfo=UTC),
        "ready_for_go_live": False,
        "manual_review_required": False,
        "details": {"source_plan_fingerprint": source_fingerprint},
        "operation_results": [
            {"checkpoint_state": "observed", "status": "completed"},
            {"checkpoint_state": "completed", "status": "completed"},
        ],
    }


def test_completed_fenced_execution_projects_a_draft_readback_without_go_live() -> None:
    status, evidence = FunctionalLiveRoomService._project_execution_readback(HANDOFF, _execution())

    assert status == "maitu_complete"
    assert evidence["status"] == "finalized_draft_readback"
    assert evidence["execution"]["ready_for_go_live"] is False
    assert evidence["execution"]["operation_summary"] == {
        "total": 2,
        "completed": 2,
        "reconcile_required": 0,
        "failed": 0,
    }


def test_execution_with_a_different_frozen_input_requires_reconciliation() -> None:
    status, evidence = FunctionalLiveRoomService._project_execution_readback(
        HANDOFF, _execution(source_fingerprint="b" * 64)
    )

    assert status == "maitu_reconcile_required"
    assert evidence["status"] == "invalid_execution_contract"
