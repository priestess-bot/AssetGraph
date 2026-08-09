from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.errors import DomainValidationError
from app.services.functional_live_rooms import FunctionalLiveRoomService


HANDOFF = {
    "plan_code": "LIVEPLAN-001",
    "build_plan_code": "MT-BUILD-001",
    "target_live_room_id": "empty-draft-001",
    "expected_title": "新品空白草稿",
    "checkpoint_contract": "script_layout_checkpoint_v1",
    "source_plan_fingerprint": "a" * 64,
    "operation_count": 2,
    "operation_types": ["preflight_content_build_plan", "fill_default_scene"],
    "operations": [
        {
            "operation_type": "preflight_content_build_plan",
            "target_live_room_id": "empty-draft-001",
            "expected_live_room_title": "新品空白草稿",
        },
        {
            "operation_type": "fill_default_scene",
            "scene_index": 0,
            "scene_name": "开场",
        },
    ],
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
            {
                "operation_index": 0,
                "operation_type": "preflight_content_build_plan",
                "checkpoint_state": "observed",
                "status": "completed",
                "completion_evidence": {
                    "target_live_room_id": "empty-draft-001",
                    "expected_live_room_title": "新品空白草稿",
                    "authoritative_live_room_title": "新品空白草稿",
                    "environment": "working",
                    "not_live": True,
                },
            },
            {
                "operation_index": 1,
                "operation_type": "fill_default_scene",
                "checkpoint_state": "completed",
                "status": "completed",
            },
        ],
    }


def test_completed_checkpoint_without_scene_readback_requires_reconciliation() -> None:
    status, evidence = FunctionalLiveRoomService._project_execution_readback(HANDOFF, _execution())

    assert status == "maitu_reconcile_required"
    assert evidence["status"] == "final_readback_mismatch"
    assert evidence["execution"]["ready_for_go_live"] is False
    assert evidence["execution"]["operation_summary"] == {
        "total": 2,
        "completed": 2,
        "reconcile_required": 0,
        "failed": 0,
    }
    assert evidence["comparison"]["target_room"]["status"] == "matched"
    assert evidence["comparison"]["scenes"][0]["status"] == "pending"


def test_execution_with_a_different_frozen_input_requires_reconciliation() -> None:
    status, evidence = FunctionalLiveRoomService._project_execution_readback(
        HANDOFF, _execution(source_fingerprint="b" * 64)
    )

    assert status == "maitu_reconcile_required"
    assert evidence["status"] == "invalid_execution_contract"


def test_execution_readback_compares_room_scene_layer_geometry_and_script() -> None:
    handoff = {
        **HANDOFF,
        "operation_count": 6,
        "operations": [
            HANDOFF["operations"][0],
            HANDOFF["operations"][1],
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "hero-product",
                "layer_type": "product",
                "asset_code": "ASSET-001",
            },
            {
                "operation_type": "position_asset_layer",
                "scene_index": 0,
                "layer_id": "hero-product",
                "asset_code": "ASSET-001",
                "x": 12,
                "y": 24,
                "width": 320,
                "height": 480,
                "z_index": 4,
            },
            {
                "operation_type": "write_script",
                "scene_index": 0,
                "script_text": "欢迎来到新品直播间。",
            },
            {
                "operation_type": "verify_scene",
                "scene_index": 0,
                "scene_name": "开场",
            },
        ],
    }
    results = [
        {
            "operation_index": 0,
            "completion_evidence": {
                "target_live_room_id": "empty-draft-001",
                "authoritative_live_room_title": "新品空白草稿",
                "environment": "working",
                "not_live": True,
            },
        },
        {
            "operation_index": 5,
            "completion_evidence": {
                "scene_name": "开场",
                "clip_id": 101,
                "verified_layers": [
                    {
                        "layer_id": "hero-product",
                        "layer_type": "product",
                        "asset_code": "ASSET-001",
                        "material_id": 201,
                        "left": 12,
                        "top": 24,
                        "width": 320,
                        "height": 480,
                        "z_index": 4,
                    }
                ],
                "verified_script_text": "欢迎来到新品直播间。",
            },
        },
    ]

    comparison = FunctionalLiveRoomService._execution_readback_comparison(handoff, results)

    assert comparison["status"] == "matched"
    assert comparison["target_room"]["status"] == "matched"
    assert comparison["scenes"][0]["status"] == "matched"
    assert comparison["scenes"][0]["layers"][0]["observed"]["material_id"] == 201
    assert comparison["scenes"][0]["script"]["status"] == "matched"

    evidence_by_index = {item["operation_index"]: item.get("completion_evidence", {}) for item in results}
    execution = {
        **_execution(),
        "expected_operation_count": 6,
        "operation_results": [
            {
                "operation_index": index,
                "operation_type": operation["operation_type"],
                "checkpoint_state": "completed",
                "status": "completed",
                "completion_evidence": evidence_by_index.get(index, {}),
            }
            for index, operation in enumerate(handoff["operations"])
        ],
    }
    status, projection = FunctionalLiveRoomService._project_execution_readback(handoff, execution)
    assert status == "maitu_complete"
    assert projection["comparison"]["status"] == "matched"


def test_execution_readback_marks_observed_geometry_difference() -> None:
    handoff = {
        **HANDOFF,
        "operations": [
            HANDOFF["operations"][0],
            HANDOFF["operations"][1],
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "hero-product",
                "asset_code": "ASSET-001",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
                "z_index": 1,
            },
            {
                "operation_type": "write_script",
                "scene_index": 0,
                "script_text": "话术",
            },
            {"operation_type": "verify_scene", "scene_index": 0, "scene_name": "开场"},
        ],
    }
    results = [
        {
            "operation_index": 0,
            "completion_evidence": {
                "target_live_room_id": "empty-draft-001",
                "authoritative_live_room_title": "新品空白草稿",
                "environment": "working",
                "not_live": True,
            },
        },
        {
            "operation_index": 4,
            "completion_evidence": {
                "scene_name": "开场",
                "verified_layers": [
                    {
                        "layer_id": "hero-product",
                        "asset_code": "ASSET-001",
                        "left": 0,
                        "top": 0,
                        "width": 99,
                        "height": 100,
                        "z_index": 1,
                    }
                ],
                "verified_script_text": "话术",
            },
        },
    ]

    comparison = FunctionalLiveRoomService._execution_readback_comparison(handoff, results)

    assert comparison["status"] == "mismatch"
    assert comparison["scenes"][0]["layers"][0]["status"] == "mismatch"


def test_execution_readback_rejects_wrong_system_host_identity() -> None:
    handoff = {
        "target_live_room_id": "room-1",
        "expected_title": "asser测试",
        "operations": [
            {"operation_type": "preflight_content_build_plan"},
            {
                "operation_type": "fill_default_scene",
                "scene_index": 0,
                "scene_name": "MSB-1",
            },
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "scene_name": "MSB-1",
                "layer_id": "LYR-HOST-1",
                "layer_type": "digital_human",
                "asset_code": "AG-HOST-37200",
                "maitu_source_material_id": 37200,
                "source_material_type": "digital_human",
                "speaker_id": 3760,
                "digital_human_image_id": 7717,
                "x": 86.4,
                "y": 345.6,
                "width": 388.8,
                "height": 1228.8,
                "z_index": 1,
            },
            {
                "operation_type": "position_asset_layer",
                "scene_index": 0,
                "layer_id": "LYR-HOST-1",
                "x": 86.4,
                "y": 345.6,
                "width": 388.8,
                "height": 1228.8,
                "z_index": 1,
            },
            {
                "operation_type": "write_script",
                "scene_index": 0,
                "script_text": "测试话术",
            },
            {
                "operation_type": "verify_scene",
                "scene_index": 0,
                "scene_name": "MSB-1",
            },
        ],
    }
    results = [
        {
            "operation_index": 0,
            "completion_evidence": {
                "target_live_room_id": "room-1",
                "authoritative_live_room_title": "asser测试",
                "environment": "working",
                "not_live": True,
            },
        },
        {
            "operation_index": 5,
            "completion_evidence": {
                "scene_name": "MSB-1",
                "verified_layers": [
                    {
                        "layer_id": "LYR-HOST-1",
                        "layer_type": "digital_human",
                        "asset_code": "AG-HOST-37200",
                        "material_id": 999,
                        "source_material_id": 37200,
                        "speaker_id": 3761,
                        "digital_human_image_id": 7717,
                        "left": 86.4,
                        "top": 345.6,
                        "width": 388.8,
                        "height": 1228.8,
                        "z_index": 1,
                    }
                ],
                "verified_script_text": "测试话术",
            },
        },
    ]

    comparison = FunctionalLiveRoomService._execution_readback_comparison(
        handoff, results
    )

    layer = comparison["scenes"][0]["layers"][0]
    assert comparison["status"] == "mismatch"
    assert layer["status"] == "mismatch"
    assert layer["expected"]["host_identity"]["speaker_id"] == 3760
    assert layer["observed"]["host_identity"]["speaker_id"] == 3761


def test_live_room_release_requires_final_matched_readback() -> None:
    plan = {
        "plan_code": "LIVEPLAN-1",
        "execution_status": "maitu_complete",
        "execution_evidence": {
            "status": "finalized_draft_readback",
            "comparison": {"status": "matched"},
            "execution": {
                "execution_code": "EXEC-1",
                "ready_for_go_live": False,
            },
        },
    }

    FunctionalLiveRoomService._require_release_execution_readback(plan)

    with pytest.raises(DomainValidationError) as invalid:
        FunctionalLiveRoomService._require_release_execution_readback(
            {
                **plan,
                "execution_evidence": {
                    **plan["execution_evidence"],
                    "comparison": {"status": "mismatch"},
                },
            }
        )

    assert invalid.value.code == "LIVE_ROOM_RELEASE_EXECUTION_REQUIRED"


def test_execution_readback_can_project_an_executed_build_plan_without_allowing_replay() -> None:
    class FakeMaitu:
        def get_live_room_build_plan_operations(self, build_plan_code: str) -> dict[str, object]:
            assert build_plan_code == "MT-BUILD-1"
            return {
                "build_plan_code": build_plan_code,
                "status": "executed",
                "can_execute": True,
                "manual_review_required": False,
                "blocked_reasons": [],
                "target_live_room_id": "41172",
                "expected_title": "asser test",
                "checkpoint_source_fingerprint": "a" * 64,
                "operations": [
                    {
                        "operation_type": "preflight_content_build_plan",
                        "expected_live_room_title": "asser test",
                    }
                ],
            }

    service = object.__new__(FunctionalLiveRoomService)
    service.maitu = FakeMaitu()  # type: ignore[assignment]
    plan = {
        "plan_code": "LIVEPLAN-1",
        "review_status": "confirmed",
        "status": "ready",
        "blocked_reasons": [],
        "build_plan": {"build_plan_code": "MT-BUILD-1", "inventory_snapshot": {}},
        "target_live_room_id": "41172",
        "expected_title": "asser test",
    }

    with pytest.raises(DomainValidationError):
        service._execution_handoff(plan)

    handoff = service._execution_handoff(plan, allow_executed=True)

    assert handoff["build_plan_code"] == "MT-BUILD-1"


def test_live_room_release_rights_include_system_managed_host() -> None:
    plan = {
        "primary_template_code": None,
        "secondary_template_codes": [],
        "selected_asset_codes": ["AG-BG-1", "AG-HOST-37200"],
        "build_plan": {
            "live_room_configuration": {},
            "inventory_snapshot": {
                "assets": [
                    {
                        "asset_code": "AG-BG-1",
                        "rights_status": "approved",
                        "rights_note": "brand-owned",
                    },
                    {
                        "asset_code": "AG-HOST-37200",
                        "rights_status": "approved",
                        "rights_note": "room-bound host",
                    },
                ]
            },
        },
    }

    current_assets = [
        {
            "asset_code": asset["asset_code"],
            "rights_status": "approved",
            "rights_note": asset["rights_note"],
            "rights_updated_at": datetime(2026, 8, 9, tzinfo=UTC),
            "rights_updated_by": "reviewer",
            "updated_at": datetime(2026, 8, 9, tzinfo=UTC),
        }
        for asset in plan["build_plan"]["inventory_snapshot"]["assets"]
    ]
    snapshot = FunctionalLiveRoomService._build_release_rights_snapshot(
        plan, current_assets
    )

    assert snapshot["status"] == "valid"
    assert snapshot["asset_count"] == 2
    assert snapshot["asset_codes"] == ["AG-BG-1", "AG-HOST-37200"]

    plan["build_plan"]["inventory_snapshot"]["assets"][1]["rights_status"] = (
        "pending"
    )
    with pytest.raises(DomainValidationError) as invalid:
        FunctionalLiveRoomService._build_release_rights_snapshot(
            plan, current_assets
        )
    assert invalid.value.code == "LIVE_ROOM_RELEASE_RIGHTS_REQUIRED"

    plan["build_plan"]["inventory_snapshot"]["assets"][1]["rights_status"] = (
        "approved"
    )
    current_assets[1]["rights_status"] = "revoked"
    with pytest.raises(DomainValidationError) as revoked:
        FunctionalLiveRoomService._build_release_rights_snapshot(
            plan, current_assets
        )
    assert revoked.value.code == "LIVE_ROOM_RELEASE_RIGHTS_REQUIRED"


def test_live_room_release_quality_gates_replace_pending_execution_gate() -> None:
    gates = FunctionalLiveRoomService._release_quality_gates(
        {
            "gate_results": [
                {
                    "gate": "asset_rights",
                    "status": "pass",
                    "rule_code": "GATE_ASSET_RIGHTS_APPROVED",
                },
                {
                    "gate": "evidence_completeness",
                    "status": "warning",
                    "rule_code": "GATE_EXECUTION_EVIDENCE_PENDING",
                },
            ]
        }
    )

    assert all(gate["status"] == "pass" for gate in gates)
    assert {gate["code"] for gate in gates} >= {
        "GATE_MAITU_DRAFT_EXECUTION_SUCCEEDED",
        "GATE_MAITU_DRAFT_READBACK_MATCHED",
        "GATE_LIVE_ROOM_ASSET_RIGHTS_VALID",
    }
    assert "GATE_EXECUTION_EVIDENCE_PENDING" not in {
        gate["code"] for gate in gates
    }
