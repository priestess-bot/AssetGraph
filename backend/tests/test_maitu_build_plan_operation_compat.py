from __future__ import annotations

from datetime import UTC, datetime

from app.repositories.maitu import MaituMaterialSlotRepository
from app.schemas.maitu import MaituLiveRoomBuildPlanOperationRead


def test_legacy_blueprint_operation_does_not_expose_internal_columns_or_flatten_details() -> None:
    row = {
        "id": "internal-operation-id",
        "build_plan_id": "internal-plan-id",
        "build_plan_code": "MT-BUILD-LEGACY",
        "operation_type": "replace_layer_asset",
        "operation_name": "替换旧蓝图图层",
        "sort_order": 10,
        "status": "planned",
        "scene_name": "旧场景",
        "layer_name": "旧图层",
        "accepted_asset_types": ["IMG"],
        "match_reasons": [],
        "instruction": "保持旧响应契约。",
        "details": {
            "legacy_only": "must-stay-nested",
            "scene_template_code": "MT-SCENE-LEGACY",
        },
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    normalized = MaituMaterialSlotRepository._normalize_live_room_build_plan_operation(row)
    serialized = MaituLiveRoomBuildPlanOperationRead.model_validate(normalized).model_dump(exclude_none=True)

    assert serialized["details"]["legacy_only"] == "must-stay-nested"
    assert "legacy_only" not in serialized
    assert "scene_template_code" not in serialized
    for internal_field in ("id", "build_plan_id", "build_plan_code", "created_at", "updated_at"):
        assert internal_field not in serialized
