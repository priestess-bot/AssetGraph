from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.functional_operations import ContentExposureCorrection


def test_content_exposure_correction_requires_a_replacement_only_for_supersede() -> None:
    started_at = datetime.now(UTC)
    replacement = {
        "session_code": "OPS-001",
        "plan_code": "PLAN-001",
        "scene_code": "SCENE-001",
        "started_at": started_at,
        "ended_at": started_at + timedelta(minutes=1),
        "source_kind": "recording_match",
        "evidence_note": "Corrected against the recording.",
    }
    supersede = ContentExposureCorrection(
        source_exposure_code="EXPOSURE-001",
        correction_kind="supersede",
        reason="The original scene match was wrong.",
        replacement=replacement,
    )
    assert supersede.replacement is not None

    retract = ContentExposureCorrection(
        source_exposure_code="EXPOSURE-001",
        correction_kind="retract",
        reason="The source evidence was withdrawn.",
    )
    assert retract.replacement is None

    with pytest.raises(ValidationError, match="requires replacement"):
        ContentExposureCorrection(
            source_exposure_code="EXPOSURE-001",
            correction_kind="supersede",
            reason="No replacement.",
        )
