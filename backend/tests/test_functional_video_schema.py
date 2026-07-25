from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.functional_videos import FunctionalVideoPlanCreate


def test_video_plan_create_requires_exactly_one_content_source() -> None:
    assert FunctionalVideoPlanCreate(project_code="CONTENT-001").project_code == "CONTENT-001"
    assert FunctionalVideoPlanCreate(live_room_plan_code="LIVEPLAN-001").live_room_plan_code == "LIVEPLAN-001"

    with pytest.raises(ValidationError, match="exactly one"):
        FunctionalVideoPlanCreate()
    with pytest.raises(ValidationError, match="exactly one"):
        FunctionalVideoPlanCreate(project_code="CONTENT-001", live_room_plan_code="LIVEPLAN-001")


def test_video_plan_create_validates_each_visual_selection_list() -> None:
    plan = FunctionalVideoPlanCreate(
        project_code="CONTENT-001",
        visual_asset_codes=["AG-VID-001"],
        visual_group_codes=["AG-GRP-001"],
        visual_material_pack_codes=["AG-PACK-001"],
    )

    assert plan.visual_group_codes == ["AG-GRP-001"]
    assert plan.visual_material_pack_codes == ["AG-PACK-001"]
    with pytest.raises(ValidationError, match="unique"):
        FunctionalVideoPlanCreate(
            project_code="CONTENT-001",
            visual_material_pack_codes=["AG-PACK-001", "AG-PACK-001"],
        )


def test_video_plan_create_bounds_background_music_gain() -> None:
    plan = FunctionalVideoPlanCreate(
        project_code="CONTENT-001",
        product_sticker_asset_code="AG-IMG-001",
        background_music_asset_code="AG-AUD-001",
        background_music_gain_db=-20,
    )

    assert plan.background_music_asset_code == "AG-AUD-001"
    assert plan.product_sticker_asset_code == "AG-IMG-001"
    assert plan.background_music_gain_db == -20
    with pytest.raises(ValidationError):
        FunctionalVideoPlanCreate(
            project_code="CONTENT-001",
            background_music_asset_code="AG-AUD-001",
            background_music_gain_db=-40,
        )
