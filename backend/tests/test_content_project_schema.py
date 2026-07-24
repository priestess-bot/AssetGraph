from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.content_projects import DesignBriefUpdate, ProgramShotRevisionCreate, ScriptRevisionCreate


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


def test_human_script_revision_requires_bounded_nonempty_blocks() -> None:
    revision = ScriptRevisionCreate(
        expected_revision=3,
        blocks=[{"module_type": "opening", "content": "从聚会场景开始说明选择依据。", "estimated_duration_ms": 30_000}],
    )
    assert revision.blocks[0].module_type == "opening"

    with pytest.raises(ValidationError):
        ScriptRevisionCreate(expected_revision=3, blocks=[])


def test_program_shot_revision_requires_sources_and_a_shot_per_segment() -> None:
    revision = ProgramShotRevisionCreate(
        expected_revision=3,
        segments=[{"semantic_goal": "解释选择依据", "script_block_codes": ["BLOCK-001"]}],
        shots=[{"program_segment_index": 0, "shot_goal": "展示讲解主体", "script_block_codes": ["BLOCK-001"]}],
    )
    assert revision.segments[0].script_block_codes == ["BLOCK-001"]

    with pytest.raises(ValidationError, match="outside submitted segments"):
        ProgramShotRevisionCreate(
            expected_revision=3,
            segments=[{"semantic_goal": "解释选择依据", "script_block_codes": ["BLOCK-001"]}],
            shots=[{"program_segment_index": 1, "shot_goal": "展示讲解主体", "script_block_codes": ["BLOCK-001"]}],
        )

    with pytest.raises(ValidationError, match="unique and non-empty"):
        ProgramShotRevisionCreate(
            expected_revision=3,
            segments=[{"semantic_goal": "解释选择依据", "script_block_codes": ["BLOCK-001", "BLOCK-001"]}],
            shots=[{"program_segment_index": 0, "shot_goal": "展示讲解主体", "script_block_codes": ["BLOCK-001"]}],
        )
