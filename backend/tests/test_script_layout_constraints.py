from __future__ import annotations

from app.schemas.maitu import MaituScriptAssetSelectionSceneRead, MaituScriptLayoutPlanRead
from app.services.script_layout_build_plan_builder import ScriptLayoutBuildPlanBuilder
from app.services.script_layout_planner import ScriptLayoutPlanner


def _selection(
    need_type: str,
    asset_code: str,
    material_role: str,
    *constraints: dict[str, object],
) -> dict[str, object]:
    return {
        "need_type": need_type,
        "required_category": need_type,
        "accepted_asset_types": ["IMG"],
        "description": need_type,
        "keywords": [],
        "priority": "high",
        "status": "selected",
        "selected_asset_code": asset_code,
        "selected_asset_material_roles": [material_role],
        "selected_asset_constraint_rules": list(constraints),
    }


def test_staged_script_layout_contract_preserves_roles_constraints_and_resolved_order() -> None:
    scene = {
        "scene_index": 0,
        "scene_name": "产品讲解",
        "scene_goal": "explanation",
        "duration_seconds": 30,
        "script": "介绍产品。",
        "asset_selections": [
            _selection(
                "digital_human",
                "HOST",
                "digital_human",
            ),
            _selection(
                "product_video",
                "VIDEO",
                "supporting_video",
                {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
                {"kind": "below_role", "hard": True, "parameters": {"role": "digital_human"}},
            ),
            _selection(
                "background_image",
                "BACKGROUND",
                "background",
                {"kind": "pin_layer_bottom", "hard": True, "parameters": {}},
            ),
        ],
        "selected_count": 3,
        "missing_count": 0,
    }

    staged_scene = MaituScriptAssetSelectionSceneRead.model_validate(scene).model_dump()
    assert staged_scene["asset_selections"][1]["selected_asset_material_roles"] == ["supporting_video"]
    assert len(staged_scene["asset_selections"][1]["selected_asset_constraint_rules"]) == 2

    layout = ScriptLayoutPlanner().plan([staged_scene])
    serialized_layout = MaituScriptLayoutPlanRead.model_validate(layout).model_dump()
    layers = serialized_layout["scenes"][0]["layers"]
    assert [layer["asset_code"] for layer in layers] == ["BACKGROUND", "VIDEO", "HOST"]
    assert [layer["z_index"] for layer in layers] == [1, 2, 3]
    assert layers[1]["material_roles"] == ["supporting_video"]
    assert layers[1]["constraint_evidence"]["stacking"]["resolved_z_order"] == 2

    build_plan = ScriptLayoutBuildPlanBuilder().build(
        serialized_layout,
        target_live_room_id="41172",
        expected_title="asser测试",
    )
    position_operations = [
        operation for operation in build_plan["operations"] if operation["operation_type"] == "position_asset_layer"
    ]
    assert [operation["asset_code"] for operation in position_operations] == ["BACKGROUND", "VIDEO", "HOST"]
    assert [operation["z_index"] for operation in position_operations] == [1, 2, 3]
    assert position_operations[1]["constraint_evidence"]["stacking"]["resolved_z_order"] == 2
