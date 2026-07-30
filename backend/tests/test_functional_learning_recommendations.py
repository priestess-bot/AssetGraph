from __future__ import annotations

from typing import Any

import pytest

from app.services.functional_learning import FunctionalLearningService


def _effect(**overrides: Any) -> dict[str, Any]:
    return {
        "effect_code": "EFFECT-001",
        "revision_number": 1,
        "evidence_level": "associational",
        "status": "approved",
        "context": {"recommendation_score": 0.8},
        "eligibility_snapshot": {
            "selected_session_count": 3,
            "association_blockers": [],
            "recommendation_eligible": True,
        },
        **overrides,
    }


def test_effect_signal_requires_approved_associational_evidence_and_three_sessions() -> None:
    descriptive = _effect(
        effect_code="EFFECT-DESCRIPTIVE",
        evidence_level="descriptive",
        eligibility_snapshot={
            "selected_session_count": 8,
            "association_blockers": [],
            "recommendation_eligible": False,
        },
    )
    small_sample = _effect(
        effect_code="EFFECT-SMALL",
        eligibility_snapshot={
            "selected_session_count": 2,
            "association_blockers": [],
            "recommendation_eligible": True,
        },
    )
    eligible = _effect()

    evidence = FunctionalLearningService._effect_evidence(
        [descriptive, small_sample, eligible]
    )

    by_code = {item["effect_code"]: item for item in evidence}
    assert by_code["EFFECT-DESCRIPTIVE"]["eligible"] is False
    assert by_code["EFFECT-DESCRIPTIVE"]["contribution"] == 0
    assert "EFFECT_EVIDENCE_NOT_ASSOCIATIONAL" in by_code["EFFECT-DESCRIPTIVE"]["blockers"]
    assert by_code["EFFECT-SMALL"]["eligible"] is False
    assert by_code["EFFECT-SMALL"]["contribution"] == 0
    assert "EFFECT_SAMPLE_SIZE_BELOW_MINIMUM" in by_code["EFFECT-SMALL"]["blockers"]
    assert by_code["EFFECT-001"]["eligible"] is True
    assert by_code["EFFECT-001"]["contribution"] == pytest.approx(0.8)


def test_material_recommendation_explains_constraint_content_and_effect_scores() -> None:
    result = FunctionalLearningService._material_recommendation(
        {
            "asset_code": "ASSET-SUMMER-TABLE",
            "title": "夏日聚餐桌面商品图",
            "description": "适合夏日聚餐直播间",
            "subject": "商品",
            "usage": "桌面陈列",
            "media_kind": "image",
            "material_roles": ["product", "foreground"],
            "execution_capability": "local_only",
            "rights_status": "approved",
            "status": "active",
        },
        "夏日聚餐，商品放在桌面陈列",
        [_effect()],
    )

    assert result["constraint_eligible"] is True
    assert result["constraint_score"] == pytest.approx(1.0)
    assert result["content_score"] > 0
    assert result["effect_score"] == pytest.approx(0.8)
    assert result["effect_signal_used"] is True
    assert result["recommendation_mode"] == "advisory_only"
    assert result["total_score"] == pytest.approx(
        round(0.45 + 0.4 * result["content_score"] + 0.15 * 0.8, 4)
    )
    assert result["constraint_reasons"]
    assert result["content_reasons"]
    assert result["effect_reasons"]


def test_descriptive_effect_remains_visible_but_does_not_change_template_score() -> None:
    result = FunctionalLearningService._template_recommendation(
        {
            "template_code": "TEMPLATE-SUMMER",
            "name": "夏日聚餐模板",
            "description": "聚餐商品讲解",
            "revision_number": 2,
            "content_readiness": "ready",
            "buildability": "reference_only",
            "content_strategy": {"theme": "夏日聚餐"},
            "confidence": 0.9,
        },
        "夏日聚餐商品讲解",
        [
            _effect(
                evidence_level="descriptive",
                eligibility_snapshot={
                    "selected_session_count": 12,
                    "association_blockers": [],
                    "recommendation_eligible": False,
                },
            )
        ],
    )

    assert result["constraint_eligible"] is True
    assert result["effect_evidence"]
    assert result["effect_evidence"][0]["eligible"] is False
    assert result["effect_score"] == 0
    assert result["effect_signal_used"] is False
