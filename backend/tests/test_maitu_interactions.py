from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas.maitu_interactions import SyncRunClaimRead, SyncRunRead
from app.services.maitu_interactions import (
    INTERACTION_PROCESSING_PURPOSE,
    RoutedInteractionAnalyzer,
    _processor_authorizes_interaction_analysis,
    is_arrival_interaction,
    is_digitally_answered,
    prepare_interaction_for_storage,
)
from app.services.providers import ModelCapability, StrategyResult


def test_fixed_interaction_filter_uses_arrival_suffix_and_follow_marker() -> None:
    assert is_arrival_interaction("jd_123来了") is True
    assert is_arrival_interaction("jd_123来了  ") is True
    assert is_arrival_interaction("jd_123来了！") is False
    assert is_arrival_interaction("来了以后多少钱") is False
    assert is_arrival_interaction("jd_a6xz5f02g7b4ss关注了张裕葡萄酒京东自营旗舰店") is True
    assert is_arrival_interaction("关注 了张裕葡萄酒京东自营旗舰店") is False
    assert is_arrival_interaction(None) is False


def test_answered_uses_only_non_empty_digital_reply() -> None:
    assert is_digitally_answered("数字人答复") is True
    assert is_digitally_answered(" \r\n ") is False
    assert is_digitally_answered(None) is False


def test_interaction_processor_policy_requires_all_transmitted_fields(monkeypatch) -> None:
    monkeypatch.setattr("app.services.maitu_interactions.settings.deepseek_processing_region", "cn")
    processor = {
        "status": "active",
        "purposes": [INTERACTION_PROCESSING_PURPOSE],
        "data_classes": ["confidential"],
        "region": "cn",
        "minimum_fields": {
            INTERACTION_PROCESSING_PURPOSE: {
                "allowed": [
                    "instructions",
                    "user_payload.interaction_content",
                    "user_payload.digital_reply_content",
                    "temperature",
                    "max_tokens",
                ]
            }
        },
    }

    assert _processor_authorizes_interaction_analysis(processor) is True
    processor["minimum_fields"][INTERACTION_PROCESSING_PURPOSE]["allowed"].remove("instructions")
    assert _processor_authorizes_interaction_analysis(processor) is False


def test_public_sync_run_schema_excludes_internal_lease_token() -> None:
    now = datetime.now(UTC)
    payload = {
        "run_code": "MT-INT-SYNC-TEST",
        "sync_mode": "full",
        "status": "running",
        "attempt": 1,
        "created_at": now,
        "updated_at": now,
        "lease_token": "11111111-1111-1111-1111-111111111111",
    }

    public = SyncRunRead.model_validate(payload).model_dump()
    worker = SyncRunClaimRead.model_validate(payload).model_dump()

    assert "lease_token" not in public
    assert worker["lease_token"] == payload["lease_token"]


def test_storage_preparation_fingerprints_analysis_input_and_preserves_raw_content() -> None:
    source = {
        "external_interaction_id": "123",
        "content": "  这款多少钱？  ",
        "digital_reply_content": "请看三号链接",
        "source_payload": {"id": 123, "content": "  这款多少钱？  "},
    }

    prepared = prepare_interaction_for_storage(source)
    changed = prepare_interaction_for_storage({**source, "digital_reply_content": "价格以页面为准"})

    assert prepared["content"] == "  这款多少钱？  "
    assert prepared["normalized_content"] == "这款多少钱？"
    assert prepared["is_arrival"] is False
    assert len(prepared["source_fingerprint"]) == 64
    assert prepared["analysis_input_fingerprint"] != changed["analysis_input_fingerprint"]


@dataclass
class _Router:
    request: object | None = None

    def execute(self, request):
        self.request = request
        return StrategyResult(
            capability=ModelCapability.STRUCTURED_GENERATION,
            strategy_revision=request.strategy_revision,
            output_schema_version=request.output_schema_version,
            content={
                "interaction_form": "question",
                "business_intent": "price_promotion_gift",
                "relevance_grade": "good",
                "completeness_grade": "good",
                "resolution_grade": "good",
                "overall_grade": "good",
                "confidence": 0.91,
                "reason": "回复直接说明了价格。",
            },
            input_fingerprint="a" * 64,
            output_fingerprint="b" * 64,
            invocation_evidence_ref="evidence/ref.json",
        )


def test_unanswered_quality_is_forced_without_exposing_identity_to_model() -> None:
    router = _Router()
    result = RoutedInteractionAnalyzer(router).analyze(
        content="这款多少钱？",
        digital_reply_content=None,
    )

    assert result["interaction_form"] == "question"
    assert result["business_intent"] == "price_promotion_gift"
    assert result["relevance_grade"] == "poor"
    assert result["completeness_grade"] == "poor"
    assert result["resolution_grade"] == "poor"
    assert result["overall_grade"] == "poor"
    assert result["reason"] == "未检测到数字人回复。"
    assert router.request.inputs["user_payload"] == {
        "interaction_content": "这款多少钱？",
        "digital_reply_content": "",
    }
