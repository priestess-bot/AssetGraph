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


def test_live_room_plan_input_rejects_duplicate_asset_gap_codes() -> None:
    with pytest.raises(ValidationError, match="selection codes must be unique"):
        FunctionalLiveRoomPlanCreate(
            project_code="CONTENT-001",
            target_live_room_id="room-001",
            expected_title="重复缺口",
            asset_codes=["AG-IMG-001"],
            asset_gap_codes=["AG-GAP-001", "AG-GAP-001"],
        )
