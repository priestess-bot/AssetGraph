from __future__ import annotations

from datetime import UTC, datetime

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
