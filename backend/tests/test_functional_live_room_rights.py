from __future__ import annotations

from app.services.functional_live_rooms import FunctionalLiveRoomService


def _rights_gate(status: str) -> dict:
    gates, _ = FunctionalLiveRoomService._evaluate_plan(
        detail={
            "revision_number": 1,
            "status": "generated",
            "fact_cards": [],
            "content": {},
            "shot_list": {"shots": []},
        },
        snapshot={
            "asset_codes": ["AG-IMG-001"],
            "assets": [
                {
                    "asset_code": "AG-IMG-001",
                    "material_roles": [],
                    "rights_status": status,
                }
            ],
        },
        blueprint={"scenes": []},
        build_plan={"build_plan_code": "MT-BUILD-001", "operations": [], "go_live": False},
        compiler_blocked_reasons=[],
    )
    return next(gate for gate in gates if gate["gate"] == "material_rights")


def test_pending_or_revoked_asset_rights_block_execution() -> None:
    assert _rights_gate("pending")["status"] == "blocked"
    assert _rights_gate("revoked")["rule_code"] == "GATE_ASSET_RIGHTS_BLOCKED"


def test_approved_asset_rights_pass_execution_gate() -> None:
    assert _rights_gate("approved")["status"] == "pass"
