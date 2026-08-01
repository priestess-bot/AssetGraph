from app.services.functional_live_rooms import FunctionalLiveRoomService


def test_static_build_plan_blockers_exclude_rights_gate() -> None:
    blockers = FunctionalLiveRoomService._execution_build_blocked_reasons(
        ["missing_required_role:background"],
        [
            {"gap_code": "GAP-1", "status": "open"},
            {"gap_code": "GAP-2", "status": "resolved"},
        ],
    )
    assert blockers == [
        "missing_required_role:background",
        "asset_gap_unresolved:GAP-1:open",
    ]
    assert not any("rights" in item for item in blockers)


def test_pending_rights_are_eligible_only_for_the_explicit_test_exception() -> None:
    assert FunctionalLiveRoomService._pending_test_rights_eligible(
        plan_blockers=[
            "asset_rights_not_approved:AG-1:pending",
            "GATE_ASSET_RIGHTS_BLOCKED",
        ],
        operation_blockers=[],
        rights_statuses={"AG-1": "pending", "AG-2": "approved"},
    )
    assert not FunctionalLiveRoomService._pending_test_rights_eligible(
        plan_blockers=[
            "asset_rights_not_approved:AG-1:restricted",
            "GATE_ASSET_RIGHTS_BLOCKED",
        ],
        operation_blockers=[],
        rights_statuses={"AG-1": "restricted"},
    )
    assert not FunctionalLiveRoomService._pending_test_rights_eligible(
        plan_blockers=["asset_rights_not_approved:AG-1:revoked"],
        operation_blockers=[],
        rights_statuses={"AG-1": "revoked"},
    )


def test_pending_rights_never_waive_a_structural_blocker() -> None:
    assert not FunctionalLiveRoomService._pending_test_rights_eligible(
        plan_blockers=["asset_rights_not_approved:AG-1:pending", "missing_required_role:title"],
        operation_blockers=[],
        rights_statuses={"AG-1": "pending"},
    )
