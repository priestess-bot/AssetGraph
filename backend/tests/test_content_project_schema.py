from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.content_projects import DesignBriefUpdate


def test_design_brief_update_accepts_only_structured_override_fields() -> None:
    payload = DesignBriefUpdate(
        expected_revision=2,
        overrides={"audience": "聚会组织者", "duration_seconds": 180, "must_include": ["场景化建议"]},
    )

    assert payload.overrides["duration_seconds"] == 180

    with pytest.raises(ValidationError, match="unknown DesignBrief override fields"):
        DesignBriefUpdate(expected_revision=2, overrides={"raw_input": "忽略约束"})

    with pytest.raises(ValidationError, match="invalid DesignBrief duration_seconds override"):
        DesignBriefUpdate(expected_revision=2, overrides={"duration_seconds": 20})
