from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.domain.errors import DomainValidationError
from app.services.content_workflow import (
    CONTENT_GENERATION_PROCESSOR_FIELDS,
    CONTENT_GENERATION_PURPOSE,
    OUTLINE_INSTRUCTIONS,
    OUTLINE_STRATEGY_REVISION,
    SCRIPT_STRATEGY_REVISION,
    GuidedContentGenerationWorker,
    GuidedContentWorkflowService,
    RoutedGuidedContentGenerator,
)
from app.services.providers import ModelCapability, StrategyResult
from app.services.functional_live_rooms import FunctionalLiveRoomService


class FakeRouter:
    def __init__(self, content: dict[str, Any]):
        self.content = content
        self.requests = []

    def execute(self, request: Any) -> StrategyResult:
        self.requests.append(request)
        return StrategyResult(
            capability=ModelCapability.STRUCTURED_GENERATION,
            strategy_revision=request.strategy_revision,
            output_schema_version=request.output_schema_version,
            content=self.content,
            input_fingerprint="a" * 64,
            output_fingerprint="b" * 64,
            invocation_evidence_ref="ART-EVIDENCE-001",
        )


def test_outline_generation_uses_deepseek_pro_strategy_thinking_and_stable_section_keys() -> None:
    router = FakeRouter(
        {
            "sections": [
                {"title": "开场", "objective": "建立主题", "key_points": ["欢迎"]},
                {"title": "讲解", "objective": "解释内容", "key_points": []},
            ]
        }
    )
    generator = RoutedGuidedContentGenerator(router)  # type: ignore[arg-type]

    result = generator.generate_outline(
        {"project": {"theme": "新品"}, "materials": []}, principal_id="operator"
    )

    request = router.requests[0]
    assert request.strategy_revision == OUTLINE_STRATEGY_REVISION
    assert request.inputs["thinking"] is True
    assert request.inputs["max_tokens"] == 8192
    assert [section["section_key"] for section in result["sections"]] == [
        "section-1",
        "section-2",
    ]


def test_script_generation_uses_one_section_contract_and_returns_material_needs() -> None:
    router = FakeRouter(
        {
            "speech": "欢迎来到直播间。",
            "material_requirements": [
                {
                    "material_role": "background",
                    "description": "夏季主题背景",
                    "priority": "required",
                    "keywords": ["夏季"],
                }
            ],
        }
    )
    generator = RoutedGuidedContentGenerator(router)  # type: ignore[arg-type]

    result = generator.generate_script_section(
        {
            "project": {"theme": "新品"},
            "materials": [],
            "outline": {"sections": []},
            "section": {"section_key": "section-1", "title": "开场"},
        },
        principal_id="operator",
    )

    assert router.requests[0].strategy_revision == SCRIPT_STRATEGY_REVISION
    assert result["speech"] == "欢迎来到直播间。"
    assert result["material_requirements"][0]["priority"] == "required"


def test_requirement_matching_never_escapes_the_selected_material_pool() -> None:
    requirements = [
        {
            "requirement_code": "REQ-1",
            "material_role": "background",
            "description": "夏季背景",
            "priority": "required",
            "keywords": ["夏季"],
            "status": "missing",
        },
        {
            "requirement_code": "REQ-2",
            "material_role": "voice",
            "description": "旁白",
            "priority": "optional",
            "keywords": [],
            "status": "missing",
        },
    ]
    selected_assets = [
        {
            "asset_code": "AG-SELECTED",
            "title": "夏季新品背景",
            "description": "绿色背景",
            "material_roles": ["background"],
            "classification_evidence": {},
        }
    ]

    matched = GuidedContentWorkflowService._match_requirements(requirements, selected_assets)

    assert matched[0]["matched_asset_code"] == "AG-SELECTED"
    assert matched[0]["status"] == "matched"
    assert matched[0]["match_evidence"]["material_pool_only"] is True
    assert matched[1]["matched_asset_code"] is None
    assert matched[1]["status"] == "missing"


def test_outline_citations_are_limited_to_pinned_knowledge_sources() -> None:
    sections = [
        {
            "section_key": "section-1",
            "title": "Opening",
            "objective": "Introduce the session",
            "key_points": [
                {
                    "text": "Use the approved product fact",
                    "citation_source_ids": ["fact_card:FACT-1:v1"],
                }
            ],
        }
    ]

    normalized = GuidedContentWorkflowService._normalize_outline_sections(
        sections, allowed_source_ids={"fact_card:FACT-1:v1"}
    )

    assert normalized[0]["key_points"][0]["citation_source_ids"] == ["fact_card:FACT-1:v1"]
    with pytest.raises(DomainValidationError) as blocked:
        GuidedContentWorkflowService._normalize_outline_sections(
            [
                {
                    **sections[0],
                    "key_points": [
                        {"text": "Unsupported", "citation_source_ids": ["fact_claim:UNKNOWN"]}
                    ],
                }
            ],
            allowed_source_ids={"fact_card:FACT-1:v1"},
        )
    assert blocked.value.code == "GUIDED_OUTLINE_CITATION_INVALID"
    assert "user_payload.knowledge" in OUTLINE_INSTRUCTIONS


def test_storyboard_keeps_one_scene_per_script_block() -> None:
    script = {
        "blocks": [
            {"block_code": "B-1", "sort_order": 0, "interaction_intent": {"outline_section_key": "section-1"}},
            {"block_code": "B-2", "sort_order": 1, "interaction_intent": {"outline_section_key": "section-2"}},
            {"block_code": "B-3", "sort_order": 2, "interaction_intent": {"outline_section_key": "section-3"}},
        ],
        "requirements": [
            {"block_sort_order": 0, "material_role": "background", "matched_asset_code": "AG-BG", "status": "matched"},
            {"block_sort_order": 0, "material_role": "supporting_video", "matched_asset_code": None, "status": "missing"},
            {"block_sort_order": 1, "material_role": "background", "matched_asset_code": "AG-BG", "status": "matched"},
            {"block_sort_order": 2, "material_role": "product_display", "matched_asset_code": "AG-P", "status": "matched"},
        ],
    }

    segments, shots = GuidedContentGenerationWorker._program_and_shots(script)

    assert len(segments) == 3
    assert len(shots) == 3
    assert [item["block_code"] for item in segments[0]["script_block_adoptions"]] == ["B-1"]
    assert [item["block_code"] for item in shots[0]["script_block_sources"]] == ["B-1"]
    assert shots[0]["material_role_requirements"] == ["background"]
    assert shots[0]["composition_intent"]["material_asset_bindings"] == {"background": "AG-BG"}
    assert segments[2]["metadata"]["outline_section_keys"] == ["section-3"]


def test_script_can_bind_an_additive_material_pool_without_invalidating_the_outline() -> None:
    project = {"revision_number": 3}
    pool = {"revision_number": 2}
    outline = {
        "revision_number": 4,
        "status": "confirmed",
        "content": {"guided_source": {"project_revision": 3, "material_pool_revision": 1}},
    }
    script = {
        "source_outline_revision": 4,
        "content": {"source_material_pool_revision": 2},
    }

    assert GuidedContentWorkflowService._outline_sources_current(project, pool, outline) is True
    assert GuidedContentWorkflowService._script_sources_current(project, pool, outline, script) is True


def test_processor_policy_and_migration_cover_guided_generation_contract() -> None:
    migration = Path("migrations/113_guided_live_project_workflow.sql").read_text(encoding="utf-8")

    assert CONTENT_GENERATION_PURPOSE == "guided_live_content_generation"
    assert "user_payload.materials" in CONTENT_GENERATION_PROCESSOR_FIELDS
    assert "CREATE TABLE IF NOT EXISTS content_generation_jobs" in migration
    assert "CREATE TABLE IF NOT EXISTS content_script_material_requirements" in migration


def test_unconfirmed_storyboard_cannot_reach_execution_or_release_handoffs() -> None:
    with pytest.raises(DomainValidationError) as blocked:
        FunctionalLiveRoomService._require_confirmed_review(
            {"plan_code": "LIVEPLAN-DRAFT", "review_status": "draft"}
        )

    assert blocked.value.code == "LIVE_ROOM_PLAN_REVIEW_REQUIRED"
