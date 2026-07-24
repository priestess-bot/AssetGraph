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
