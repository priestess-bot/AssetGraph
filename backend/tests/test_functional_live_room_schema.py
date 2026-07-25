from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.functional_live_rooms import FunctionalLiveRoomPlanCreate


def test_live_room_plan_input_accepts_distinct_explicit_asset_gap_codes() -> None:
    payload = FunctionalLiveRoomPlanCreate(
        project_code="CONTENT-001",
        target_live_room_id="room-001",
        expected_title="缺口关联计划",
        asset_codes=["AG-IMG-001"],
        asset_gap_codes=["AG-GAP-001", "AG-GAP-002"],
    )

    assert payload.asset_gap_codes == ["AG-GAP-001", "AG-GAP-002"]


def test_live_room_plan_input_accepts_a_scoped_asset_gap_waiver_reason() -> None:
    payload = FunctionalLiveRoomPlanCreate(
        project_code="CONTENT-001",
        target_live_room_id="room-001",
        expected_title="缺口豁免计划",
        asset_codes=["AG-IMG-001"],
        asset_gap_codes=["AG-GAP-001"],
        asset_gap_waivers={"AG-GAP-001": "本次活动使用已审核的临时背景。"},
    )

    assert payload.asset_gap_waivers == {"AG-GAP-001": "本次活动使用已审核的临时背景。"}


def test_live_room_plan_input_rejects_blank_asset_gap_waiver_reason() -> None:
    with pytest.raises(ValidationError, match="asset gap waivers"):
        FunctionalLiveRoomPlanCreate(
            project_code="CONTENT-001",
            target_live_room_id="room-001",
            expected_title="无效缺口豁免",
            asset_codes=["AG-IMG-001"],
            asset_gap_waivers={"AG-GAP-001": "  "},
        )


def test_live_room_plan_input_rejects_duplicate_asset_gap_codes() -> None:
    with pytest.raises(ValidationError, match="selection codes must be unique"):
        FunctionalLiveRoomPlanCreate(
            project_code="CONTENT-001",
            target_live_room_id="room-001",
            expected_title="重复缺口",
            asset_codes=["AG-IMG-001"],
            asset_gap_codes=["AG-GAP-001", "AG-GAP-001"],
        )


def test_live_room_plan_input_accepts_a_bounded_room_constraint_override() -> None:
    payload = FunctionalLiveRoomPlanCreate(
        project_code="CONTENT-001",
        target_live_room_id="room-001",
        expected_title="房间私有位置覆盖",
        asset_codes=["AG-IMG-001"],
        room_constraint_overrides={
            "AG-IMG-001": {
                "reason": "适配当前房间的商品陈列区域",
                "geometry": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3},
                "z_order": 12,
            }
        },
    )

    assert payload.room_constraint_overrides["AG-IMG-001"].z_order == 12


def test_live_room_plan_input_rejects_out_of_canvas_room_override() -> None:
    with pytest.raises(ValidationError, match="normalized canvas"):
        FunctionalLiveRoomPlanCreate(
            project_code="CONTENT-001",
            target_live_room_id="room-001",
            expected_title="非法位置覆盖",
            asset_codes=["AG-IMG-001"],
            room_constraint_overrides={
                "AG-IMG-001": {
                    "reason": "超出画布",
                    "geometry": {"x": 0.8, "y": 0.2, "width": 0.4, "height": 0.3},
                }
            },
        )
