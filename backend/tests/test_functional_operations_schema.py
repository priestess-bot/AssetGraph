from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.functional_operations import ContentExposureCorrection
from app.services.functional_operations import FunctionalOperationsService


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


def test_timeline_content_projection_uses_the_fixed_variant_chain() -> None:
    class ProjectionCursor:
        def execute(self, statement: str, parameters: object) -> None:
            assert "production_variant_revisions" in statement
            assert parameters == (["VAR-001"],)

        @staticmethod
        def fetchall() -> list[dict[str, object]]:
            return [
                {
                    "variant_code": "VAR-001",
                    "shot_code": "SHOT-001",
                    "segment_code": "SEGMENT-001",
                    "program_phase": "conversion",
                    "semantic_goal": "Guide the next action.",
                    "product_refs": ["PRODUCT-001"],
                    "cta_actions": [{"type": "comment"}],
                    "block_code": "BLOCK-001",
                    "module_type": "conversion",
                    "product_ref": "PRODUCT-001",
                    "template_sources": [
                        {"template_code": "TEMPLATE-001", "revision": 2}
                    ],
                    "cta_intent": {"type": "comment"},
                }
            ]

    projection = FunctionalOperationsService._timeline_content_projections(
        ProjectionCursor(), ["VAR-001"]
    )

    assert projection[("VAR-001", "SHOT-001")] == {
        "status": "resolved",
        "program_segment": {
            "segment_code": "SEGMENT-001",
            "program_phase": "conversion",
            "semantic_goal": "Guide the next action.",
            "product_refs": ["PRODUCT-001"],
            "cta_actions": [{"type": "comment"}],
        },
        "script_blocks": [
            {
                "block_code": "BLOCK-001",
                "module_type": "conversion",
                "product_ref": "PRODUCT-001",
                "template_modules": [
                    {
                        "template_code": "TEMPLATE-001",
                        "revision": 2,
                        "module_key": "conversion",
                    }
                ],
                "cta_intent": {"type": "comment"},
            }
        ],
    }
