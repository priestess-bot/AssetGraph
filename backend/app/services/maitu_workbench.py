from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import settings
from app.domain.contracts import Capability, DataClassification
from app.domain.errors import DomainUnavailableError, DomainValidationError
from app.domain.protected_resources import protected_resource_denial
from app.repositories.evidence import EvidenceRepository
from app.repositories.maitu_workbench import MaituWorkbenchConflictError
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.artifacts import ContentAddressedArtifactService
from app.services.object_storage import MinioObjectStorage
from app.services.online_models import (
    OnlineModelError,
    OpenAICompatibleChatClient,
)
from app.services.processor_credentials import ExternalProcessorService
from app.services.providers import (
    ArtifactProviderEvidenceSink,
    ModelCapability,
    OpenAICompatibleStructuredAdapter,
    ProviderBinding,
    ProviderRouter,
    StrategyRequest,
)
from app.services.script_asset_gap_reporter import BLOCKING_NEED_TYPES, ScriptAssetGapReporter
from app.services.script_asset_need_planner import ScriptAssetNeedPlanner
from app.services.script_asset_selector import ScriptAssetSelector
from app.services.script_layout_build_plan_builder import ScriptLayoutBuildPlanBuilder
from app.services.script_layout_planner import ScriptLayoutPlanner


PLAN_PROMPT_VERSION = "maitu-workbench-plan-v3"
PLAN_STRATEGY_REVISION = "maitu.creative-plan.v2"
PIPELINE_SOURCE = "strategy_script_scene_plan+deterministic_asset_layout_v2"
PIPELINE_STAGE_ORDER = [
    "strategy_script_and_scene_generation",
    "script_asset_needs",
    "script_asset_selections",
    "script_asset_gap_report",
    "script_layout_plan",
    "script_layout_build_plan",
]
ALLOWED_DRAFT_OPERATION_TYPES = {
    "preflight_content_build_plan",
    "fill_default_scene",
    "create_scene",
    "insert_asset_layer",
    "position_asset_layer",
    "write_script",
    "verify_scene",
    "save_draft",
}
FORBIDDEN_OPERATION_TYPES = {
    "go_live",
    "start_live",
    "publish_live",
    "start_broadcast",
    "publish",
}
MATERIAL_CATEGORY_BY_NEED_TYPE = {
    "digital_human": "digital_human_video",
    "product_image": "product_image",
    "background_image": "background_image",
    "supporting_visual": "floating_sticker",
    "product_video": "product_video",
    "promotion_sticker": "floating_sticker",
    "brand_logo_title": "floating_sticker",
}
MATERIAL_ASSET_TYPES_BY_NEED_TYPE = {
    "digital_human": {"IMG", "VID"},
    "product_image": {"IMG"},
    "background_image": {"IMG"},
    "supporting_visual": {"IMG", "VID"},
    "product_video": {"VID"},
    "promotion_sticker": {"IMG"},
    "brand_logo_title": {"IMG"},
}
PROTECTED_REFERENCE_ROOM_IDS = frozenset({"38336", "38995"})
FreshBlankRoomVerifier = Callable[
    [str, set[str] | frozenset[str]],
    dict[str, Any],
]
REFERENCE_TEMPLATE_CONTRACT = "maitu-workbench-reference-template.v1"
_REFERENCE_AUDIO_POLICY_FIELDS = (
    "max_active_speech",
    "max_active_bgm",
    "unknown_audio_default_muted",
    "allow_overlapping_bgm_crossfade",
    "speech_ducking_db",
)
_REFERENCE_BLOCKING_REASONS = {
    "template_has_no_components",
    "template_has_no_scenes",
    "template_confidence_below_0_8",
    "fewer_than_three_independent_source_sessions",
    "component_identity_is_missing_or_duplicate",
    "audio_policy_does_not_limit_speech_to_one",
    "audio_policy_does_not_limit_bgm_to_one",
    "audio_policy_does_not_mute_unknown_audio",
    "audio_policy_allows_overlapping_bgm",
}
_REFERENCE_COMPONENT_BLOCKING_SUFFIXES = {
    "_is_not_observable": "component_is_not_observable",
    "_source_is_not_verified": "component_source_is_not_verified",
    "_has_no_geometry": "component_has_no_geometry",
    "_unknown_audio_is_not_muted": "component_unknown_audio_is_not_muted",
}


class WorkbenchModelUnavailableError(RuntimeError):
    """The required online planning model is not configured or reachable."""


class WorkbenchModelGenerationError(RuntimeError):
    """The online model returned an invalid planning result."""


class WorkbenchDraftSafetyError(MaituWorkbenchConflictError):
    """A durable job attempted to exceed the draft-only execution boundary."""


def _reference_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def _reference_text(value: Any, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:maximum] if text else None


def _sanitize_reference_geometry(value: Any) -> dict[str, int | float] | None:
    if not isinstance(value, dict):
        return None
    geometry = {key: _reference_number(value.get(key)) for key in ("x", "y", "width", "height")}
    if any(item is None for item in geometry.values()):
        return None
    x = float(geometry["x"] or 0)
    y = float(geometry["y"] or 0)
    width = float(geometry["width"] or 0)
    height = float(geometry["height"] or 0)
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
        return None
    return {key: item for key, item in geometry.items() if item is not None}


def _sanitize_reference_regions(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    regions: list[dict[str, Any]] = []
    for value in values[:100]:
        if not isinstance(value, dict):
            continue
        role = _reference_text(value.get("role"), maximum=64)
        geometry = _sanitize_reference_geometry(value.get("geometry"))
        if role and geometry:
            regions.append({"role": role, "geometry": geometry})
    return regions


def _sanitize_reference_blocking_reasons(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    reasons: list[str] = []
    for value in values:
        reason = _reference_text(value, maximum=512)
        normalized: str | None = None
        if reason in _REFERENCE_BLOCKING_REASONS:
            normalized = reason
        elif reason and reason.startswith("component_"):
            normalized = next(
                (
                    replacement
                    for suffix, replacement in _REFERENCE_COMPONENT_BLOCKING_SUFFIXES.items()
                    if reason.endswith(suffix)
                ),
                None,
            )
        elif reason and re.fullmatch(r"(?:speech|bgm)_bus_overlap:.+", reason):
            normalized = reason.split(":", 1)[0]
        if normalized and normalized not in reasons:
            reasons.append(normalized)
    return reasons


def sanitize_reference_template(publication: dict[str, Any]) -> dict[str, Any]:
    projection = publication.get("projection_payload")
    if not isinstance(projection, dict):
        raise MaituWorkbenchConflictError("Published reference template projection is invalid")

    template_code = str(publication.get("template_code") or "")
    revision_number = int(publication.get("revision_number") or 0)
    projection_fingerprint = str(publication.get("projection_fingerprint") or "")
    if projection.get("template_code") not in {None, template_code}:
        raise MaituWorkbenchConflictError("Published reference template code is inconsistent")
    if projection.get("revision_number") not in {None, revision_number}:
        raise MaituWorkbenchConflictError("Published reference template revision is inconsistent")
    if projection.get("projection_fingerprint") not in {None, projection_fingerprint}:
        raise MaituWorkbenchConflictError("Published reference template fingerprint is inconsistent")

    canvas_source = projection.get("canvas") if isinstance(projection.get("canvas"), dict) else {}
    canvas: dict[str, Any] = {}
    for key in ("width", "height", "rotation_degrees"):
        number = _reference_number(canvas_source.get(key))
        if number is not None:
            canvas[key] = number
    pixel_aspect_ratio = _reference_text(canvas_source.get("pixel_aspect_ratio"), maximum=32)
    if pixel_aspect_ratio:
        canvas["pixel_aspect_ratio"] = pixel_aspect_ratio

    global_components = [
        item for item in projection.get("components") or [] if isinstance(item, dict)
    ]
    scenes: list[dict[str, Any]] = []
    for index, source in enumerate(projection.get("scenes") or []):
        if not isinstance(source, dict):
            continue
        scene_key = source.get("scene_key") or source.get("scene_code")
        linked = [
            item
            for item in global_components
            if item.get("scene_key") == scene_key
            or (len(projection.get("scenes") or []) == 1 and item.get("scene_key") == "default")
        ]
        embedded = source.get("components") if isinstance(source.get("components"), list) else []
        start = _reference_number(source.get("start_seconds"))
        end = _reference_number(source.get("end_seconds"))
        duration = _reference_number(source.get("duration_seconds"))
        if duration is None and start is not None and end is not None and float(end) > float(start):
            duration = float(end) - float(start)
        scene: dict[str, Any] = {"order": len(scenes) + 1}
        title = _reference_text(
            source.get("title") or source.get("name") or source.get("scene_name"),
            maximum=255,
        )
        purpose = _reference_text(source.get("purpose") or source.get("scene_goal"), maximum=2000)
        if title:
            scene["title"] = title
        if duration is not None and float(duration) > 0:
            scene["duration_seconds"] = duration
        if purpose:
            scene["purpose"] = purpose
        scene["approximate_regions"] = _sanitize_reference_regions([*embedded, *linked])
        scenes.append(scene)

    audio_source = (
        projection.get("audio_policy") if isinstance(projection.get("audio_policy"), dict) else {}
    )
    audio_policy = {
        key: value
        for key in _REFERENCE_AUDIO_POLICY_FIELDS
        if (value := audio_source.get(key)) is not None
        and isinstance(value, (bool, int, float))
        and (isinstance(value, bool) or math.isfinite(float(value)))
    }
    return {
        "contract_version": REFERENCE_TEMPLATE_CONTRACT,
        "reference_mode": "reference_only",
        "layout_fidelity": "approximate",
        "approximate_composition": {"canvas": canvas},
        "scenes": scenes,
        "audio_policy": audio_policy,
        "blocking_reasons": _sanitize_reference_blocking_reasons(
            projection.get("blocking_reasons")
        ),
    }


def _reference_template_generation_context(snapshot: Any) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    composition = snapshot.get("approximate_composition")
    canvas = composition.get("canvas") if isinstance(composition, dict) else {}
    scenes: list[dict[str, Any]] = []
    for source in snapshot.get("scenes") or []:
        if not isinstance(source, dict):
            continue
        scene: dict[str, Any] = {"order": len(scenes) + 1}
        title = _reference_text(source.get("title"), maximum=255)
        duration = _reference_number(source.get("duration_seconds"))
        purpose = _reference_text(source.get("purpose"), maximum=2000)
        if title:
            scene["title"] = title
        if duration is not None and float(duration) > 0:
            scene["duration_seconds"] = duration
        if purpose:
            scene["purpose"] = purpose
        scene["approximate_regions"] = _sanitize_reference_regions(
            source.get("approximate_regions")
        )
        scenes.append(scene)
    return {
        "reference_mode": "reference_only",
        "layout_fidelity": "approximate",
        "scene_sequence": scenes,
        "approximate_composition": {
            "canvas": {
                key: value
                for key in ("width", "height", "rotation_degrees", "pixel_aspect_ratio")
                if (value := canvas.get(key)) is not None
            }
        },
        "audio_policy": {
            key: value
            for key in _REFERENCE_AUDIO_POLICY_FIELDS
            if (value := (snapshot.get("audio_policy") or {}).get(key)) is not None
        },
        "blocking_reasons": _sanitize_reference_blocking_reasons(
            snapshot.get("blocking_reasons")
        ),
    }


class _MaterialIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    need_type: Literal[
        "digital_human",
        "product_image",
        "background_image",
        "supporting_visual",
        "product_video",
        "promotion_sticker",
        "brand_logo_title",
    ]
    required_category: Literal[
        "digital_human_video",
        "product_image",
        "background_image",
        "floating_sticker",
        "product_video",
    ]
    accepted_asset_types: list[Literal["IMG", "VID"]] = Field(..., min_length=1, max_length=2)
    description: str = Field(..., min_length=1, max_length=1000)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    priority: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def validate_taxonomy(self) -> "_MaterialIntent":
        if self.required_category != MATERIAL_CATEGORY_BY_NEED_TYPE[self.need_type]:
            raise ValueError("material intent category does not match need_type")
        if not set(self.accepted_asset_types) <= MATERIAL_ASSET_TYPES_BY_NEED_TYPE[self.need_type]:
            raise ValueError("material intent asset types do not match need_type")
        return self


class _CreativeScene(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scene_name: str = Field(..., min_length=1, max_length=128)
    scene_goal: Literal[
        "opening",
        "product_explanation",
        "explanation",
        "conversion",
        "transition",
        "closing",
    ]
    duration_seconds: int = Field(..., ge=1, le=900)
    script: str = Field(..., min_length=1, max_length=10000)
    keywords: list[str] = Field(..., min_length=1, max_length=30)
    composition_intent: str = Field(..., min_length=1, max_length=1000)
    material_intents: list[_MaterialIntent] = Field(..., max_length=20)


class _CreativePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=255)
    host_persona: str = Field(..., min_length=1, max_length=500)
    target_audience: str = Field(..., min_length=1, max_length=500)
    selling_angle: str = Field(..., min_length=1, max_length=1000)
    scenes: list[_CreativeScene] = Field(..., min_length=1, max_length=12)
    compliance_focus: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class PlanGenerationResult:
    strategy_revision: str
    invocation_evidence_ref: str | None
    prompt_version: str
    content: dict[str, Any]
    input_fingerprint: str
    output_fingerprint: str


class PlanGenerationProvider(Protocol):
    def generate(self, context: dict[str, Any]) -> PlanGenerationResult: ...


class RoutedPlanGenerationProvider:
    """Provider-neutral creative-plan producer with durable invocation evidence."""

    def __init__(
        self,
        router: ProviderRouter,
        *,
        strategy_revision: str = PLAN_STRATEGY_REVISION,
    ) -> None:
        self.router = router
        self.strategy_revision = strategy_revision

    def generate(self, context: dict[str, Any]) -> PlanGenerationResult:
        schema = _CreativePlan.model_json_schema()
        allowed_keywords = [
            str(value)
            for value in (context.get("allowed_keywords") or [])
            if str(value).strip()
        ]
        if allowed_keywords:
            for definition_name in ("_CreativeScene", "_MaterialIntent"):
                keyword_items = (
                    schema["$defs"][definition_name]["properties"]["keywords"]["items"]
                )
                keyword_items["enum"] = allowed_keywords
        system_prompt = (
            "你是麦兔商业直播工作台的剧本与场景规划模型。直接生成可执行的完整场景计划，"
            "不得新增产品事实、价格、优惠、库存或功效承诺。每个 scene.script 只能逐句选用输入"
            " allowed_script_sentences 中的原句，不得改写、拼接新事实或添加目录外句子；每个"
            " scene.keywords 和 material_intents[].keywords 只能选用 allowed_keywords。所有场景"
            " duration_seconds 之和必须精确等于 target_duration_seconds。返回严格 JSON 对象，"
            "顶层只能包含 title, host_persona, target_audience, selling_angle, scenes, compliance_focus。"
            "每个 scene 只能包含 scene_name, scene_goal, duration_seconds, script, keywords, "
            "composition_intent, material_intents。每个 material_intent 只能包含 need_type, "
            "required_category, accepted_asset_types, description, keywords, priority。若 context 中存在"
            " reference_template，它只能作为 reference_only / approximate 的结构参考：仅可借鉴场景"
            "顺序、时长节奏、内容目的、近似构图和音频策略；不得把它当作精确麦兔组件、图层、素材"
            "或坐标操作，不得推断或复用任何组件/素材标识，也不得把其中任何文案当作产品事实。产品"
            "事实仍只能来自 approved_product_facts 和 allowed_script_sentences。"
            "输出必须逐项满足 user payload 中 creative_plan_json_schema 的类型、枚举、必填字段和"
            " additionalProperties 限制，不得用自然语言替代枚举值。keywords 中每个值都必须从"
            " Schema enum 原样复制，不得自造描述性关键词。"
        )
        user_payload = {
            "prompt_version": PLAN_PROMPT_VERSION,
            "task": "生成完整商业口播剧本、具体场景规划和素材组合意图",
            "creative_plan_json_schema": schema,
            "material_taxonomy": {
                need_type: {
                    "required_category": MATERIAL_CATEGORY_BY_NEED_TYPE[need_type],
                    "accepted_asset_types": sorted(MATERIAL_ASSET_TYPES_BY_NEED_TYPE[need_type]),
                }
                for need_type in sorted(MATERIAL_CATEGORY_BY_NEED_TYPE)
            },
            "context": context,
        }
        try:
            result = self.router.execute(
                StrategyRequest(
                    capability=ModelCapability.STRUCTURED_GENERATION,
                    strategy_revision=self.strategy_revision,
                    input_schema_version="maitu-creative-plan-input.v2",
                    output_schema_version="maitu-creative-plan-output.v1",
                    inputs={
                        "instructions": system_prompt,
                        "user_payload": user_payload,
                        "temperature": 0.2,
                        "max_tokens": 5000,
                    },
                    output_json_schema=schema,
                    data_classification=DataClassification.CONFIDENTIAL,
                    principal_id="maitu-plan-producer",
                )
            )
        except DomainUnavailableError as exc:
            raise WorkbenchModelUnavailableError(str(exc)) from exc
        except DomainValidationError as exc:
            raise WorkbenchModelGenerationError(str(exc)) from exc
        try:
            plan = _CreativePlan.model_validate(result.content)
        except ValidationError as exc:
            raise WorkbenchModelGenerationError(
                "Model strategy returned an invalid creative-plan contract"
            ) from exc
        return PlanGenerationResult(
            strategy_revision=result.strategy_revision,
            invocation_evidence_ref=result.invocation_evidence_ref,
            prompt_version=PLAN_PROMPT_VERSION,
            content=plan.model_dump(mode="json"),
            input_fingerprint=result.input_fingerprint,
            output_fingerprint=result.output_fingerprint,
        )


class UnavailablePlanGenerationProvider:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def generate(self, context: dict[str, Any]) -> PlanGenerationResult:
        del context
        raise WorkbenchModelUnavailableError(self.reason)


class DeterministicPlanGenerationProvider:
    """Explicit test provider; production dependency construction never selects it."""

    def __init__(self, content: dict[str, Any] | None = None) -> None:
        self.content = content

    def generate(self, context: dict[str, Any]) -> PlanGenerationResult:
        content = self.content or self._content_from_context(context)
        normalized = _CreativePlan.model_validate(content).model_dump(mode="json")
        return PlanGenerationResult(
            strategy_revision="test.maitu.creative-plan.v1",
            invocation_evidence_ref=None,
            prompt_version=PLAN_PROMPT_VERSION,
            content=normalized,
            input_fingerprint=fingerprint(context),
            output_fingerprint=fingerprint(normalized),
        )

    @staticmethod
    def _content_from_context(context: dict[str, Any]) -> dict[str, Any]:
        sentences = list(context["allowed_script_sentences"])
        keywords = list(context["allowed_keywords"])
        target_seconds = int(context["target_duration_seconds"])
        product_name = str(context["approved_product_facts"]["product_name"])
        scene_count = 3
        durations = _allocate_seconds(target_seconds, scene_count)
        groups = [sentences[index::scene_count] for index in range(scene_count)]
        fallback_sentence = sentences[0]
        return {
            "title": "结构化商品讲解",
            "host_persona": "专业、克制、判断直接",
            "target_audience": "需要按用途和口味选购的用户",
            "selling_angle": "以已核验事实建立选择标准",
            "scenes": [
                {
                    "scene_name": "需求入口",
                    "scene_goal": "opening",
                    "duration_seconds": durations[0],
                    "script": "".join(groups[0] or [fallback_sentence]),
                    "keywords": _dedupe([product_name, *keywords])[:4],
                    "composition_intent": "建立品牌氛围并保留清晰主播区域",
                    "material_intents": [
                        {
                            "need_type": "background_image",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "与已审批商品定位一致的主题背景",
                            "keywords": _dedupe([product_name, *keywords])[:4],
                            "priority": "high",
                        }
                    ],
                },
                {
                    "scene_name": "事实讲解",
                    "scene_goal": "product_explanation",
                    "duration_seconds": durations[1],
                    "script": "".join(groups[1] or [fallback_sentence]),
                    "keywords": _dedupe([product_name, *keywords])[:4],
                    "composition_intent": "商品主体与主播同时可见，突出商品识别",
                    "material_intents": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "展示事实卡对应商品主体",
                            "keywords": [product_name],
                            "priority": "high",
                        }
                    ],
                },
                {
                    "scene_name": "选择与合规",
                    "scene_goal": "transition",
                    "duration_seconds": durations[2],
                    "script": "".join(groups[2] or [fallback_sentence]),
                    "keywords": _dedupe([product_name, *keywords])[:4],
                    "composition_intent": "保持商品信息并以克制方式完成循环重入",
                    "material_intents": [],
                },
            ],
            "compliance_focus": ["不使用未核验优惠", "不承诺库存与价格"],
        }


def build_production_plan_generation_provider(
    connection: Any | None = None,
) -> PlanGenerationProvider:
    configured = settings.deepseek_api_key
    if configured is None or not configured.get_secret_value().strip():
        return UnavailablePlanGenerationProvider("Creative-plan model strategy is not configured")
    if connection is None:
        return UnavailablePlanGenerationProvider(
            "Governed provider evidence storage requires a database connection"
        )
    if not settings.deepseek_processing_region:
        return UnavailablePlanGenerationProvider(
            "Creative-plan processor region is not configured"
        )
    try:
        client = OpenAICompatibleChatClient(
            api_key=configured.get_secret_value(),
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.online_model_timeout_seconds,
            max_attempts=settings.online_model_max_attempts,
        )
    except OnlineModelError as exc:
        return UnavailablePlanGenerationProvider(str(exc))
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    artifact_service = ContentAddressedArtifactService(
        EvidenceRepository(connection),
        storage,
        bucket_name=settings.minio_bucket,
    )
    adapter = OpenAICompatibleStructuredAdapter(
        client,
        adapter_code="deepseek-openai-compatible-chat.v1",
        provider_code="deepseek",
    )
    binding = ProviderBinding(
        strategy_revision=PLAN_STRATEGY_REVISION,
        capability=ModelCapability.STRUCTURED_GENERATION,
        adapter=adapter,
        provider_model=settings.deepseek_flash_model,
        allowed_classifications=frozenset(
            {DataClassification.INTERNAL, DataClassification.CONFIDENTIAL}
        ),
        max_canonical_input_bytes=2_000_000,
        processor_code=settings.deepseek_processor_code,
        processing_region=settings.deepseek_processing_region,
        processing_purpose="model_inference",
    )
    router = ProviderRouter(
        [binding],
        ArtifactProviderEvidenceSink(artifact_service, producer_code="maitu-plan-producer"),
        ExternalProcessorService(PrivacyGovernanceRepository(connection)),
    )
    return RoutedPlanGenerationProvider(router)


class _SnapshotBoundAssetRepository:
    """Restrict deterministic retrieval to the run's immutable inventory snapshot."""

    def __init__(self, repository: Any, snapshot: dict[str, Any]) -> None:
        self.repository = repository
        available = [
            item
            for item in (snapshot.get("items") or [])
            if item.get("availability_status") == "available"
        ]
        self.items_by_asset_code = {
            str(item["asset_code"]): item for item in available if item.get("asset_code")
        }
        self.items_by_material_id = {
            str(item["material_id"]): item for item in available if item.get("material_id")
        }

    def select_assets_for_script_asset_need(
        self,
        need: dict[str, Any],
        scene: dict[str, Any],
        *,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        candidates = self.repository.select_assets_for_script_asset_need(
            need,
            scene,
            limit=max(200, limit),
        )
        bound: list[dict[str, Any]] = []
        for candidate in candidates:
            enriched = self.bind_candidate(candidate)
            if enriched is not None:
                bound.append(enriched)
            if len(bound) >= limit:
                break
        return bound

    def bind_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        asset_code = str(candidate.get("asset_code") or "")
        material_id = str(candidate.get("maitu_material_id") or "")
        item = self.items_by_asset_code.get(asset_code) or self.items_by_material_id.get(material_id)
        if item is None:
            return None
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return {
            **candidate,
            "maitu_material_id": item.get("material_id"),
            "source_material_type": item.get("material_type"),
            "source_material_url": item.get("source_material_url"),
            "source_cover_url": item.get("source_cover_url"),
            "speaker_id": item.get("speaker_id"),
            "digital_human_image_id": item.get("digital_human_image_id"),
            "sound_enabled": metadata.get("sound_enabled"),
        }


class MaituWorkbenchService:
    def __init__(
        self,
        repository: Any,
        maitu_repository: Any,
        *,
        generation_provider: PlanGenerationProvider | None = None,
    ) -> None:
        self.repository = repository
        self.maitu_repository = maitu_repository
        self.generation_provider = generation_provider or build_production_plan_generation_provider(
            getattr(repository, "connection", None)
        )

    # Versioned facts and immutable inventory --------------------------

    def create_product_fact_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.create_product_fact_card(
            payload,
            content_sha256=fingerprint(payload["content"]),
        )

    def create_product_fact_card_version(
        self,
        fact_card_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self.repository.create_product_fact_card_version(
            fact_card_code,
            payload,
            content_sha256=fingerprint(payload["content"]),
        )

    def create_inventory_sync_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_identity = {
            key: payload.get(key)
            for key in ("source_system", "project_code", "sync_mode", "config")
        }
        return self.repository.create_inventory_sync_job(
            payload,
            request_fingerprint=fingerprint(request_identity),
        )

    def complete_inventory_sync_job(
        self,
        sync_job_code: str,
        worker_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        snapshot_identity = {
            "source_revision": payload.get("source_revision"),
            "schema_version": payload.get("schema_version"),
            "quality_status": payload.get("quality_status"),
            "summary": payload.get("summary") or {},
            "items": sorted(payload.get("items") or [], key=lambda item: str(item.get("item_key") or "")),
        }
        return self.repository.complete_inventory_sync_job(
            sync_job_code,
            worker_id,
            payload["lease_token"],
            payload,
            snapshot_fingerprint=fingerprint(snapshot_identity),
        )

    # Run planning ------------------------------------------------------

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_live_room_id = str(payload.get("target_live_room_id") or "").strip()
        if target_live_room_id in PROTECTED_REFERENCE_ROOM_IDS:
            raise MaituWorkbenchConflictError(
                "Protected reference rooms are read-only and cannot be execution targets"
            )
        fact_version = self.repository.resolve_product_fact_card_version(
            payload["fact_card_code"],
            payload.get("fact_card_version"),
            require_approved=True,
        )
        if fact_version is None:
            raise MaituWorkbenchConflictError("An approved product fact card version is required")
        snapshot = self.repository.get_inventory_snapshot(payload["inventory_snapshot_code"])
        if snapshot is None:
            raise MaituWorkbenchConflictError("Inventory snapshot does not exist")
        reference_template = self._resolve_reference_template(payload)
        return self.repository.create_run(
            payload,
            fact_card_version=fact_version,
            inventory_snapshot=snapshot,
            reference_template=reference_template,
        )

    def update_run_target_live_room(
        self,
        run_code: str,
        target_live_room_id: str,
    ) -> dict[str, Any] | None:
        if target_live_room_id in PROTECTED_REFERENCE_ROOM_IDS:
            raise MaituWorkbenchConflictError(
                "Protected reference rooms are read-only and cannot be execution targets"
            )
        return self.repository.update_run_target_live_room(run_code, target_live_room_id)

    def create_initial_plan(self, run_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plan(
            run_code,
            expected_revision=0,
            trigger_type="initial",
            reason=payload.get("reason"),
            requested_by=payload.get("requested_by"),
        )

    def replan(self, run_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._plan(
            run_code,
            expected_revision=int(payload["expected_plan_revision"]),
            trigger_type="replan",
            reason=payload["reason"],
            requested_by=payload.get("requested_by"),
            inventory_snapshot_code=payload.get("inventory_snapshot_code"),
            fact_card_version_number=payload.get("fact_card_version"),
        )

    def _plan(
        self,
        run_code: str,
        *,
        expected_revision: int,
        trigger_type: str,
        reason: str | None,
        requested_by: str | None,
        inventory_snapshot_code: str | None = None,
        fact_card_version_number: int | None = None,
    ) -> dict[str, Any]:
        run = self.repository.get_run(run_code)
        if run is None:
            raise KeyError(run_code)
        if int(run["active_plan_revision"]) != expected_revision:
            raise MaituWorkbenchConflictError("Expected plan revision is stale")
        fact_card_code = str(run["fact_card_version"].get("fact_card_code") or "")
        fact_version = self.repository.resolve_product_fact_card_version(
            fact_card_code,
            fact_card_version_number
            if fact_card_version_number is not None
            else int(run["fact_card_version"].get("version_number") or 0),
            require_approved=True,
        )
        if fact_version is None:
            raise MaituWorkbenchConflictError("Planning requires an approved fact card version")
        snapshot = self.repository.get_inventory_snapshot(
            inventory_snapshot_code or run["inventory_snapshot_code"],
            include_items=True,
        )
        if snapshot is None:
            raise MaituWorkbenchConflictError("Planning inventory snapshot does not exist")
        raw_overrides = (
            self.repository.get_manual_decision_overrides(run_code, expected_revision)
            if expected_revision > 0
            else []
        )
        overrides = _json_compatible(raw_overrides)
        if not isinstance(overrides, list):
            raise MaituWorkbenchConflictError("Manual decision overrides are malformed")
        self.repository.mark_run_planning(run_code, expected_revision=expected_revision)
        generation_context = self._generation_context(run, fact_version, snapshot, overrides, reason)
        try:
            generation = None
            model_plan = None
            for generation_attempt in range(2):
                try:
                    generation = self.generation_provider.generate(generation_context)
                    model_plan = self._validate_generated_plan(
                        generation.content,
                        generation_context,
                    )
                    break
                except WorkbenchModelGenerationError as exc:
                    if generation_attempt == 1:
                        raise
                    generation_context = {
                        **generation_context,
                        "validation_retry": {
                            "attempt": 2,
                            "previous_error": str(exc),
                            "instruction": (
                                "重新生成完整计划并修正该错误；仍须满足全部 JSON Schema、事实、"
                                "关键词白名单和精确总时长约束，不得只返回局部补丁。"
                            ),
                        },
                    }
            if generation is None or model_plan is None:
                raise WorkbenchModelGenerationError("Model strategy produced no validated result")
        except WorkbenchModelUnavailableError:
            self.repository.mark_run_failed(
                run_code,
                "MODEL_UNAVAILABLE",
                "Creative-plan model strategy is unavailable",
                expected_revision=expected_revision,
            )
            raise
        except WorkbenchModelGenerationError:
            self.repository.mark_run_failed(
                run_code,
                "MODEL_OUTPUT_INVALID",
                "Creative-plan model strategy output is invalid",
                expected_revision=expected_revision,
            )
            raise

        try:
            script_draft, scene_plan = self._model_script_and_scene_plan(model_plan)
            asset_need_plan = ScriptAssetNeedPlanner().plan(
                scene_plan["scenes"],
                include_default_host=bool(run["include_default_host"]),
                include_script_text_need=True,
            )
            self._merge_model_material_intents(asset_need_plan["scenes"], model_plan["scenes"])
            selections = ScriptAssetSelector(
                _SnapshotBoundAssetRepository(self.maitu_repository, snapshot)
            ).select(
                asset_need_plan["scenes"],
                max_candidates_per_need=int(run["max_candidates_per_need"]),
            )
            self._apply_overrides(selections, overrides, snapshot)
            gap_report = ScriptAssetGapReporter().report(selections["scenes"])
            layout_plan = ScriptLayoutPlanner().plan(
                selections["scenes"],
                build_mode=run["build_mode"],
                canvas_width=int(run["canvas_width"]),
                canvas_height=int(run["canvas_height"]),
            )
            build_plan = ScriptLayoutBuildPlanBuilder().build(
                layout_plan,
                target_live_room_id=run.get("target_live_room_id"),
            )
            persisted_build_plan = self.maitu_repository.create_script_layout_build_plan(
                build_plan,
                plan_name=f"{script_draft['title']} 工作台 BuildPlan",
            )
            requirements = self._materialize_requirements(selections)
            blocked_reasons = self._planning_blocked_reasons(
                script_draft,
                persisted_build_plan,
                gap_report,
                requirements,
            )
            status = "blocked" if blocked_reasons else "ready"
            output = {
                "source": PIPELINE_SOURCE,
                "status": "blocked" if blocked_reasons else "ready_for_draft_build",
                "ready_for_go_live": False,
                "model_plan": model_plan,
                "script_draft": script_draft,
                "scene_plan": scene_plan,
                "asset_need_plan": asset_need_plan,
                "asset_selection_plan": selections,
                "gap_report": gap_report,
                "layout_plan": layout_plan,
                "build_plan": persisted_build_plan,
                "blocked_reasons": blocked_reasons,
                "stage_order": PIPELINE_STAGE_ORDER,
            }
            plan_identity = {
                "run_code": run_code,
                "expected_revision": expected_revision,
                "fact_content_sha256": fact_version["content_sha256"],
                "inventory_fingerprint": snapshot["fingerprint_sha256"],
                "reference_template_projection_fingerprint": run.get(
                    "reference_template_projection_fingerprint"
                ),
                "generation_output_fingerprint": generation.output_fingerprint,
                "grounding_catalog_fingerprint": fingerprint(
                    generation_context["allowed_script_sentences"]
                ),
                "overrides": overrides,
                "pipeline_output": output,
            }
            return self.repository.create_plan_revision(
                run_code,
                expected_revision=expected_revision,
                trigger_type=trigger_type,
                status=status,
                fact_card_version=fact_version,
                inventory_snapshot=snapshot,
                source_build_plan_code=persisted_build_plan.get("build_plan_code"),
                input_fingerprint=fingerprint(plan_identity),
                generation_strategy_revision=generation.strategy_revision,
                generation_invocation_evidence_ref=generation.invocation_evidence_ref,
                generation_prompt_version=generation.prompt_version,
                generation_input_fingerprint=generation.input_fingerprint,
                generation_output_fingerprint=generation.output_fingerprint,
                pipeline_source=PIPELINE_SOURCE,
                pipeline_output=output,
                gap_report=gap_report,
                blocked_reasons=blocked_reasons,
                requirements=requirements,
                reason=reason,
                created_by=requested_by,
            )
        except Exception as exc:
            self.repository.mark_run_failed(
                run_code,
                "PLANNING_FAILED",
                str(exc)[:4000],
                expected_revision=expected_revision,
            )
            raise

    def create_material_decision(
        self,
        run_code: str,
        requirement_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        run = self.repository.get_run(run_code)
        if run is None:
            raise KeyError(run_code)
        if payload["decision"] == "selected" and payload.get("selected_asset_code"):
            asset = self.repository.get_asset_selection(payload["selected_asset_code"])
            if asset is None or str(asset.get("status") or "").lower() in {"failed", "deleted", "archived"}:
                raise MaituWorkbenchConflictError("Selected AssetGraph asset is unavailable")
            snapshot = self.repository.get_inventory_snapshot(
                run["inventory_snapshot_code"],
                include_items=True,
            )
            if snapshot is None or not _snapshot_contains_asset(snapshot, asset):
                raise MaituWorkbenchConflictError(
                    "Selected AssetGraph asset is outside the run inventory snapshot"
                )
        if payload["decision"] == "selected" and payload.get("selected_material_key"):
            item = self.repository.get_inventory_snapshot_item(
                run["inventory_snapshot_code"],
                payload["selected_material_key"],
            )
            if item is None or item.get("availability_status") != "available":
                raise MaituWorkbenchConflictError("Selected inventory material is unavailable")
        return self.repository.create_material_decision(run_code, requirement_code, payload)

    # Preflight and draft-only execution -------------------------------

    def preflight(
        self,
        run_code: str,
        payload: dict[str, Any],
        *,
        room_verifier: FreshBlankRoomVerifier | None = None,
    ) -> dict[str, Any]:
        run = self.repository.get_run(run_code)
        if run is None:
            raise KeyError(run_code)
        expected_revision = int(payload["expected_plan_revision"])
        checks, requirements = self._preflight_checks(
            run_code,
            run,
            expected_revision,
            room_verifier=room_verifier,
        )
        blocked_reasons = [check["code"] for check in checks if not check["passed"]]
        status = "blocked" if blocked_reasons else "passed"
        preflight_identity = self._preflight_identity(
            run_code,
            expected_revision,
            run.get("active_plan") or {},
            requirements,
            checks,
        )
        return self.repository.create_preflight(
            run_code,
            expected_plan_revision=expected_revision,
            status=status,
            input_fingerprint=fingerprint(preflight_identity),
            checks=checks,
            blocked_reasons=blocked_reasons,
            performed_by=payload.get("performed_by"),
        )

    def create_draft_execution_job(
        self,
        run_code: str,
        payload: dict[str, Any],
        *,
        room_verifier: FreshBlankRoomVerifier | None = None,
    ) -> dict[str, Any]:
        run = self.repository.get_run(run_code)
        if run is None:
            raise KeyError(run_code)
        expected_revision = int(payload["expected_plan_revision"])
        plan = run.get("active_plan") or {}
        preflight = run.get("latest_preflight") or {}
        if (
            run.get("status") != "preflight_passed"
            or int(run.get("active_plan_revision") or 0) != expected_revision
            or plan.get("status") != "ready"
            or preflight.get("status") != "passed"
            or int(preflight.get("plan_revision_number") or 0) != expected_revision
        ):
            raise MaituWorkbenchConflictError("A current passed preflight is required")
        checks, requirements = self._preflight_checks(
            run_code,
            run,
            expected_revision,
            room_verifier=room_verifier,
        )
        if any(not check["passed"] for check in checks):
            raise MaituWorkbenchConflictError("The passed preflight is no longer current")
        current_preflight_fingerprint = fingerprint(
            self._preflight_identity(run_code, expected_revision, plan, requirements, checks)
        )
        if current_preflight_fingerprint != preflight.get("input_fingerprint"):
            raise MaituWorkbenchConflictError("The passed preflight fingerprint is stale")
        build_plan = plan.get("pipeline_output", {}).get("build_plan") or {}
        job_payload = {
            "contract_version": "maitu-workbench-draft-execution-v1",
            "execution_scope": "live_room_draft_only",
            "run_code": run_code,
            "plan_revision_code": plan.get("plan_revision_code"),
            "plan_revision_number": expected_revision,
            "preflight_code": preflight.get("preflight_code"),
            "build_plan": build_plan,
            "ready_for_go_live": False,
            "safety_boundary": {
                "go_live_permitted": False,
                "save_draft_permitted": True,
                "worker_must_stop_after_save": True,
            },
        }
        assert_draft_only(job_payload)
        identity = {
            "plan_input_fingerprint": plan.get("input_fingerprint"),
            "preflight_input_fingerprint": preflight.get("input_fingerprint"),
            "payload": job_payload,
        }
        return self.repository.create_draft_execution_job(
            run_code,
            expected_plan_revision=expected_revision,
            input_fingerprint=fingerprint(identity),
            payload=job_payload,
            idempotency_key=payload.get("idempotency_key"),
            queued_by=payload.get("queued_by"),
        )

    def complete_draft_execution_job(
        self,
        execution_job_code: str,
        worker_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        assert_draft_only(payload.get("result") or {})
        if payload.get("ready_for_go_live") is not False:
            raise WorkbenchDraftSafetyError("Workbench execution can only save a draft")
        return self.repository.complete_draft_execution_job(
            execution_job_code,
            worker_id,
            payload["lease_token"],
            payload.get("result") or {},
        )

    # Planning helpers --------------------------------------------------

    def _resolve_reference_template(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        template_code = str(payload.get("reference_template_code") or "").strip()
        requested_revision = payload.get("reference_template_revision_number")
        requested_fingerprint = str(
            payload.get("reference_template_projection_fingerprint") or ""
        ).strip()
        if not template_code:
            if requested_revision is not None or requested_fingerprint:
                raise MaituWorkbenchConflictError(
                    "Reference template revision and fingerprint require a template code"
                )
            return None
        if requested_revision is None or not requested_fingerprint:
            raise MaituWorkbenchConflictError(
                "Reference template code, revision, and fingerprint must be pinned together"
            )

        publication = self.repository.resolve_published_reference_template(template_code)
        if publication is None:
            raise MaituWorkbenchConflictError(
                "Reference template is not a current published projection"
            )
        revision_number = int(publication.get("revision_number") or 0)
        projection_fingerprint = str(publication.get("projection_fingerprint") or "")
        if revision_number < 1 or not re.fullmatch(r"[0-9a-f]{64}", projection_fingerprint):
            raise MaituWorkbenchConflictError("Published reference template pin is invalid")
        if requested_revision is not None and int(requested_revision) != revision_number:
            raise MaituWorkbenchConflictError("Reference template revision pin is stale")
        if requested_fingerprint and requested_fingerprint != projection_fingerprint:
            raise MaituWorkbenchConflictError("Reference template fingerprint pin is stale")

        return {
            "template_code": template_code,
            "revision_number": revision_number,
            "projection_fingerprint": projection_fingerprint,
            "snapshot": sanitize_reference_template(publication),
        }

    @staticmethod
    def _generation_context(
        run: dict[str, Any],
        fact_version: dict[str, Any],
        snapshot: dict[str, Any],
        overrides: list[dict[str, Any]],
        reason: str | None,
    ) -> dict[str, Any]:
        available_items = [
            {
                "item_key": item.get("item_key"),
                "title": item.get("title"),
                "material_type": item.get("material_type"),
                "category": item.get("category"),
                "subtype": item.get("subtype"),
            }
            for item in (snapshot.get("items") or [])
            if item.get("availability_status") == "available"
        ][:200]
        facts = dict(fact_version["content"])
        approved_facts = {
            key: value
            for key, value in facts.items()
            if key != "unverified_promotion_claims"
        }
        fact_sentences, generic_sentences = _approved_script_sentence_catalog(facts)
        inventory_keywords = [
            str(value)
            for item in available_items
            for value in (
                item.get("title"),
                item.get("material_type"),
                item.get("category"),
                item.get("subtype"),
            )
            if value
        ]
        allowed_keywords = _approved_keyword_catalog(facts, inventory_keywords)
        target_seconds = int(run["target_duration_minutes"]) * 60
        context = {
            "run": {
                "title": run["title"],
                "topic": run["topic"],
                "target_duration_minutes": run["target_duration_minutes"],
                "target_duration_seconds": target_seconds,
                "build_mode": run["build_mode"],
            },
            "target_duration_seconds": target_seconds,
            "approved_product_facts": approved_facts,
            "approved_fact_script_sentences": fact_sentences,
            "allowed_script_sentences": _dedupe([*generic_sentences, *fact_sentences]),
            "allowed_keywords": allowed_keywords,
            "inventory": {
                "snapshot_code": snapshot["snapshot_code"],
                "fingerprint_sha256": snapshot["fingerprint_sha256"],
                "item_count": snapshot["item_count"],
                "summary": snapshot.get("summary") or {},
                "available_item_sample": available_items,
            },
            "manual_decisions": overrides,
            "replan_reason": reason,
        }
        reference_template = _reference_template_generation_context(
            run.get("reference_template_snapshot")
        )
        if reference_template is not None:
            context["reference_template"] = reference_template
        return context

    @staticmethod
    def _validate_generated_plan(
        generated: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            plan = _CreativePlan.model_validate(generated)
        except ValidationError as exc:
            raise WorkbenchModelGenerationError(
                "Model strategy returned an invalid scene-plan contract"
            ) from exc
        normalized = plan.model_dump(mode="json")
        scenes = normalized["scenes"]
        duration_seconds = sum(int(scene["duration_seconds"]) for scene in scenes)
        target_seconds = int(context["target_duration_seconds"])
        if duration_seconds != target_seconds:
            raise WorkbenchModelGenerationError(
                f"Model-strategy scene duration must total exactly {target_seconds} seconds"
            )
        scene_names = [scene["scene_name"] for scene in scenes]
        if len(scene_names) != len(set(scene_names)):
            raise WorkbenchModelGenerationError("Model-strategy scene names must be unique")
        if scenes[0]["scene_goal"] != "opening" or not any(
            scene["scene_goal"] in {"product_explanation", "explanation", "conversion"}
            for scene in scenes
        ):
            raise WorkbenchModelGenerationError(
                "Model-strategy scene plan requires an opening and a product explanation"
            )
        if not any(scene["material_intents"] for scene in scenes):
            raise WorkbenchModelGenerationError(
                "Model-strategy scene plan requires material intents"
            )

        allowed_sentences = set(context["allowed_script_sentences"])
        fact_sentences = set(context["approved_fact_script_sentences"])
        used_sentences: list[str] = []
        allowed_keywords = set(context["allowed_keywords"])
        for scene in scenes:
            script_sentences = _split_script_sentences(scene["script"])
            if not script_sentences or any(sentence not in allowed_sentences for sentence in script_sentences):
                raise WorkbenchModelGenerationError(
                    "Model-strategy scene script is not grounded in approved facts: "
                    f"{scene['scene_name']}"
                )
            used_sentences.extend(script_sentences)
            keywords = [*scene["keywords"]]
            keywords.extend(
                keyword
                for intent in scene["material_intents"]
                for keyword in intent["keywords"]
            )
            invalid_keywords = sorted(
                {keyword for keyword in keywords if keyword not in allowed_keywords}
            )
            if invalid_keywords:
                raise WorkbenchModelGenerationError(
                    "Model-strategy scene uses keyword(s) outside the approved catalog: "
                    f"{scene['scene_name']}: {invalid_keywords}"
                )
        if not fact_sentences.intersection(used_sentences):
            raise WorkbenchModelGenerationError(
                "Model-strategy script must use approved product facts"
            )
        if len(used_sentences) != len(set(used_sentences)):
            raise WorkbenchModelGenerationError(
                "Model-strategy script must not repeat grounded sentences"
            )
        unverified_claims = context["approved_product_facts"].get("unverified_promotion_claims") or []
        serialized = _canonical_json(normalized)
        if any(str(claim).strip() and str(claim).strip() in serialized for claim in unverified_claims):
            raise WorkbenchModelGenerationError(
                "Model-strategy output contains an unverified promotion claim"
            )
        return normalized

    @staticmethod
    def _model_script_and_scene_plan(
        model_plan: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        scenes: list[dict[str, Any]] = []
        sections: list[dict[str, Any]] = []
        for scene_index, generated in enumerate(model_plan["scenes"]):
            scene = {
                "scene_index": scene_index,
                "scene_name": generated["scene_name"],
                "scene_goal": generated["scene_goal"],
                "duration_seconds": generated["duration_seconds"],
                "script": generated["script"],
                "keywords": generated["keywords"],
                "composition_intent": generated["composition_intent"],
                "material_intents": generated["material_intents"],
                "manual_review": False,
                "review_reasons": [],
            }
            scenes.append(scene)
            sections.append(
                {
                    "section_index": scene_index,
                    "section_type": generated["scene_goal"],
                    **scene,
                }
            )
        spoken_script = "\n\n".join(scene["script"] for scene in scenes)
        total_seconds = sum(scene["duration_seconds"] for scene in scenes)
        scene_plan = {
            "source": "strategy_workbench_scene_plan_v2",
            "scene_count": len(scenes),
            "target_scene_count": len(scenes),
            "manual_review_required": False,
            "scenes": scenes,
        }
        script_draft = {
            "source": "strategy_grounded_script_v2",
            "title": model_plan["title"],
            "host_persona": model_plan["host_persona"],
            "target_audience": model_plan["target_audience"],
            "selling_angle": model_plan["selling_angle"],
            "spoken_script": spoken_script,
            "section_count": len(sections),
            "sections": sections,
            "scene_plan_payload": scene_plan,
            "manual_review_required": False,
            "review_reasons": [],
            "quality_report": {
                "source": "approved_fact_sentence_grounding_v1",
                "fact_grounded": True,
                "duration_exact": True,
                "estimated_duration_seconds": total_seconds,
                "target_duration_seconds": total_seconds,
                "warnings": [],
            },
        }
        return script_draft, scene_plan

    @staticmethod
    def _merge_model_material_intents(
        planned_scenes: list[dict[str, Any]],
        model_scenes: list[dict[str, Any]],
    ) -> None:
        if len(planned_scenes) != len(model_scenes):
            raise WorkbenchModelGenerationError(
                "Model-strategy scenes changed before material planning"
            )
        for planned, model_scene in zip(planned_scenes, model_scenes, strict=True):
            model_intents = [
                {
                    **intent,
                    "suggested_layer_role": intent["need_type"],
                    "reason": "Material intent generated from the grounded strategy scene plan",
                }
                for intent in model_scene["material_intents"]
            ]
            planned["asset_needs"] = ScriptAssetNeedPlanner._merge_needs(
                [*(planned.get("asset_needs") or []), *model_intents]
            )
            planned["composition_intent"] = model_scene["composition_intent"]
            planned["model_material_intents"] = model_scene["material_intents"]

    def _apply_overrides(
        self,
        selection_plan: dict[str, Any],
        overrides: list[dict[str, Any]],
        snapshot: dict[str, Any],
    ) -> None:
        snapshot_code = str(snapshot["snapshot_code"])
        snapshot_assets = _SnapshotBoundAssetRepository(self.maitu_repository, snapshot)
        ordered_overrides = sorted(
            overrides,
            key=lambda row: (
                int(row.get("requirement_plan_revision_number") or 0),
                int(row.get("revision_number") or 0),
                str(row.get("created_at") or ""),
            ),
            reverse=True,
        )
        overrides_by_key: dict[str, dict[str, Any]] = {}
        overrides_by_scene_need: dict[tuple[int, str, str], dict[str, Any]] = {}
        overrides_by_global_need: dict[tuple[str, str], dict[str, Any]] = {}
        globally_reusable_need_types = {
            "digital_human",
            "product_image",
            "brand_logo_title",
        }
        for row in ordered_overrides:
            requirement_key = str(row.get("requirement_key") or "")
            if requirement_key:
                overrides_by_key.setdefault(requirement_key, row)
            need_type = str(row.get("need_type") or "")
            required_category = str(row.get("required_category") or "")
            scene_index = int(row.get("scene_index") or 0)
            overrides_by_scene_need.setdefault(
                (scene_index, need_type, required_category),
                row,
            )
            if need_type in globally_reusable_need_types:
                overrides_by_global_need.setdefault(
                    (need_type, required_category),
                    row,
                )
        for scene in selection_plan.get("scenes") or []:
            for need_index, selection in enumerate(scene.get("asset_selections") or []):
                if selection.get("need_type") == "script_text":
                    continue
                key = _requirement_key(scene, selection)
                need_type = str(selection.get("need_type") or "")
                required_category = str(selection.get("required_category") or "")
                scene_index = int(scene.get("scene_index") or 0)
                override = (
                    overrides_by_key.get(key)
                    or overrides_by_scene_need.get(
                        (scene_index, need_type, required_category)
                    )
                    or overrides_by_global_need.get((need_type, required_category))
                )
                if override is None:
                    continue
                selection["workbench_decision"] = override
                decision = override.get("decision")
                if decision == "waived":
                    selection.update(
                        status="waived",
                        selection_source="workbench_manual_waiver",
                        selected_asset_code=None,
                    )
                elif decision == "deferred":
                    selection.update(
                        status="missing_asset",
                        selection_source="workbench_manual_defer",
                        selected_asset_code=None,
                    )
                elif override.get("selected_asset_code"):
                    asset = self.repository.get_asset_selection(override["selected_asset_code"])
                    bound_asset = snapshot_assets.bind_candidate(asset) if asset is not None else None
                    if bound_asset is None:
                        selection.update(status="missing_asset", selection_source="stale_manual_asset")
                    else:
                        selection.update(
                            _selection_fields_from_asset(
                                bound_asset,
                                source="workbench_manual_asset",
                            )
                        )
                elif override.get("selected_material_key"):
                    item = self.repository.get_inventory_snapshot_item(
                        snapshot_code,
                        override["selected_material_key"],
                    )
                    if item is None or item.get("availability_status") != "available":
                        selection.update(status="missing_asset", selection_source="stale_manual_material")
                    else:
                        selection.update(_selection_fields_from_material(item))
            self._refresh_scene_selection_summary(scene)
        selection_plan["selected_count"] = sum(
            scene["selected_count"] for scene in selection_plan.get("scenes") or []
        )
        selection_plan["missing_count"] = sum(
            scene["missing_count"] for scene in selection_plan.get("scenes") or []
        )
        selection_plan["manual_review_required"] = any(
            scene["manual_review"] for scene in selection_plan.get("scenes") or []
        )

    @staticmethod
    def _refresh_scene_selection_summary(scene: dict[str, Any]) -> None:
        selections = list(scene.get("asset_selections") or [])
        missing = [selection for selection in selections if selection.get("status") == "missing_asset"]
        scene["selected_count"] = sum(selection.get("status") == "selected" for selection in selections)
        scene["missing_count"] = len(missing)
        scene["missing_asset_needs"] = [dict(selection) for selection in missing]
        reasons = [
            str(reason)
            for reason in (scene.get("review_reasons") or [])
            if not str(reason).startswith("missing_asset:")
        ]
        reasons.extend(f"missing_asset:{selection.get('need_type')}" for selection in missing)
        scene["review_reasons"] = _dedupe(reasons)
        scene["manual_review"] = bool(scene["review_reasons"])

    @staticmethod
    def _materialize_requirements(selection_plan: dict[str, Any]) -> list[dict[str, Any]]:
        requirements: list[dict[str, Any]] = []
        for scene in selection_plan.get("scenes") or []:
            for need_index, selection in enumerate(scene.get("asset_selections") or []):
                if selection.get("need_type") == "script_text":
                    continue
                need_type = str(selection.get("need_type") or "unknown")
                category = str(selection.get("required_category") or need_type)
                is_required = selection.get("priority") == "high" and (
                    need_type in BLOCKING_NEED_TYPES or category in BLOCKING_NEED_TYPES
                )
                decision = selection.get("workbench_decision")
                initial_decision = None
                status = "missing" if selection.get("status") == "missing_asset" else "pending"
                if decision:
                    selected_is_valid = selection.get("status") == "selected"
                    status = decision["decision"] if decision["decision"] != "selected" else (
                        "selected" if selected_is_valid else "missing"
                    )
                    initial_decision = {
                        "decision": decision["decision"],
                        "selected_asset_code": decision.get("selected_asset_code"),
                        "selected_material_key": decision.get("selected_material_key"),
                        "reason": decision.get("reason") or "Carried from prior plan revision",
                        "decision_source": "carried_forward",
                        "decided_by": decision.get("decided_by"),
                    }
                elif selection.get("status") == "selected" and selection.get("selected_asset_code"):
                    status = "selected"
                    initial_decision = {
                        "decision": "selected",
                        "selected_asset_code": selection["selected_asset_code"],
                        "selected_material_key": None,
                        "reason": "Selected by the script-content asset pipeline",
                        "decision_source": "pipeline_auto",
                        "decided_by": None,
                    }
                requirements.append(
                    {
                        "requirement_key": _requirement_key(scene, selection),
                        "scene_index": int(scene.get("scene_index") or 0),
                        "scene_name": str(scene.get("scene_name") or ""),
                        "need_index": need_index,
                        "need_type": need_type,
                        "required_category": category,
                        "accepted_asset_types": selection.get("accepted_asset_types") or [],
                        "description": selection.get("description") or "",
                        "keywords": selection.get("keywords") or [],
                        "priority": selection.get("priority") or "medium",
                        "is_required": is_required,
                        "status": status,
                        "pipeline_selection": selection,
                        "initial_decision": initial_decision,
                    }
                )
        return requirements

    @staticmethod
    def _planning_blocked_reasons(
        script_draft: dict[str, Any],
        build_plan: dict[str, Any],
        gap_report: dict[str, Any],
        requirements: list[dict[str, Any]],
    ) -> list[str]:
        reasons: list[str] = []
        if script_draft.get("manual_review_required"):
            reasons.append("script_quality_review_required")
        if int(gap_report.get("blocking_gap_count") or 0) > 0:
            reasons.append("missing_required_assets")
        if not build_plan.get("can_execute"):
            reasons.extend(build_plan.get("blocked_reasons") or ["build_plan_not_executable"])
        for requirement in requirements:
            if requirement["is_required"] and requirement["status"] != "selected":
                reasons.append(f"required_material_unresolved:{requirement['requirement_key']}")
        return _dedupe(reasons)

    def _preflight_checks(
        self,
        run_code: str,
        run: dict[str, Any],
        expected_revision: int,
        *,
        room_verifier: FreshBlankRoomVerifier | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self._synchronize_selected_video_analyses(run_code)
        plan = run.get("active_plan") or {}
        requirements = self.repository.list_material_requirements(run_code, active_only=True) or []
        checks: list[dict[str, Any]] = []
        self._add_check(
            checks,
            "active_plan",
            int(run["active_plan_revision"]) == expected_revision and plan.get("status") == "ready",
            "The requested revision must be the current ready plan",
        )
        fact_version = run.get("fact_card_version") or {}
        self._add_check(
            checks,
            "approved_facts",
            fact_version.get("status") == "approved",
            "The plan must still reference an approved fact-card version",
        )
        snapshot = self.repository.get_inventory_snapshot(run["inventory_snapshot_code"])
        latest_snapshot = None
        if snapshot:
            latest_snapshot = self.repository.get_latest_inventory_snapshot(
                snapshot["source_system"],
                snapshot.get("project_code"),
            )
        self._add_check(
            checks,
            "current_inventory",
            bool(snapshot)
            and snapshot.get("quality_status") == "complete"
            and bool(latest_snapshot)
            and latest_snapshot.get("snapshot_code") == snapshot.get("snapshot_code"),
            "A complete latest inventory snapshot is required",
        )
        target_live_room_id = str(run.get("target_live_room_id") or "").strip()
        protected_resource = None
        protected_reader = getattr(self.repository, "get_protected_resource", None)
        if target_live_room_id and callable(protected_reader):
            protected_resource = protected_reader("maitu_room", target_live_room_id)
        protection_reason = protected_resource_denial(protected_resource, Capability.WRITE_DRAFT)
        target_room_ok = (
            bool(target_live_room_id)
            and target_live_room_id not in PROTECTED_REFERENCE_ROOM_IDS
            and protection_reason is None
        )
        self._add_check(
            checks,
            "target_room",
            target_room_ok,
            "A fresh target live-room draft is required; protected reference rooms are read-only",
            evidence={
                "resource_type": "maitu_room",
                "resource_id": target_live_room_id,
                "registry_reason": protection_reason,
            }
            if protection_reason
            else None,
        )
        authority_evidence = None
        if target_room_ok and room_verifier is not None:
            authority_evidence = room_verifier(
                target_live_room_id,
                PROTECTED_REFERENCE_ROOM_IDS,
            )
        authority_ok = self._valid_fresh_blank_room_attestation(
            authority_evidence,
            target_live_room_id,
        )
        self._add_check(
            checks,
            "authoritative_blank_draft",
            authority_ok,
            (
                "Backend Maitu authority confirms one untouched default scene in a non-live working draft"
                if authority_ok
                else "Backend Maitu authority must attest one untouched default scene in a non-live working draft"
            ),
            evidence=authority_evidence if authority_ok else None,
        )
        material_ok, material_detail = self._validate_requirement_availability(run, requirements)
        self._add_check(checks, "materials", material_ok, material_detail)
        blocker_reader = getattr(self.repository, "list_selected_analysis_blockers", None)
        analysis_blockers = blocker_reader(run_code) if callable(blocker_reader) else []
        blocker_codes = [str(item.get("conflict_code") or "unknown") for item in analysis_blockers]
        self._add_check(
            checks,
            "selected_video_analysis_conflicts",
            not analysis_blockers,
            (
                "Selected video analyses have no unresolved critical conflicts"
                if not analysis_blockers
                else "Selected video analysis conflicts require review: " + ", ".join(blocker_codes)
            ),
        )
        build_plan = plan.get("pipeline_output", {}).get("build_plan", {})
        operations = build_plan.get("operations") or []
        operation_types = {str(operation.get("operation_type") or "") for operation in operations}
        operations_ok = (
            bool(build_plan.get("can_execute"))
            and bool(operations)
            and not (operation_types & FORBIDDEN_OPERATION_TYPES)
            and operation_types <= ALLOWED_DRAFT_OPERATION_TYPES
        )
        self._add_check(
            checks,
            "draft_only_build_plan",
            operations_ok,
            "BuildPlan must be executable and contain only draft-safe operations",
        )
        return checks, requirements

    def _synchronize_selected_video_analyses(self, run_code: str) -> None:
        synchronizer = getattr(self.repository, "synchronize_selected_video_analyses", None)
        if callable(synchronizer):
            synchronizer(run_code)

    @staticmethod
    def _valid_fresh_blank_room_attestation(
        evidence: dict[str, Any] | None,
        target_live_room_id: str,
    ) -> bool:
        if not isinstance(evidence, dict):
            return False
        material_count = evidence.get("material_count")
        seed_material = evidence.get("seed_material")
        seed_ok = (material_count == 0 and seed_material is None) or (
            material_count == 1
            and isinstance(seed_material, dict)
            and seed_material.get("type") == "digital_human"
            and all(
                seed_material.get(key) is not None
                for key in (
                    "clip_material_id",
                    "material_id",
                    "speaker_id",
                    "digital_human_image_id",
                )
            )
        )
        return (
            evidence.get("contract") == "maitu-fresh-draft-room-attestation.v2"
            and str(evidence.get("target_live_room_id") or "") == target_live_room_id
            and evidence.get("environment") in {"working", "draft"}
            and evidence.get("is_live") is False
            and evidence.get("scene_count") == 1
            and seed_ok
            and evidence.get("default_scene_id") is not None
            and evidence.get("readback_attestation_algorithm") == "hmac-sha256-v1"
            and bool(re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("observation_sha256") or "")))
            and bool(re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("readback_attestation") or "")))
        )

    @staticmethod
    def _preflight_identity(
        run_code: str,
        expected_revision: int,
        plan: dict[str, Any],
        requirements: list[dict[str, Any]],
        checks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "run_code": run_code,
            "revision": expected_revision,
            "plan_input_fingerprint": plan.get("input_fingerprint"),
            "requirements": requirements,
            "checks": checks,
        }

    def _validate_requirement_availability(
        self,
        run: dict[str, Any],
        requirements: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        issues: list[str] = []
        snapshot = self.repository.get_inventory_snapshot(
            run["inventory_snapshot_code"],
            include_items=True,
        )
        for requirement in requirements:
            if requirement.get("is_required") and requirement.get("status") != "selected":
                issues.append(f"{requirement['requirement_code']}:required_not_selected")
                continue
            if requirement.get("status") != "selected":
                continue
            decisions = requirement.get("decisions") or []
            decision = decisions[-1] if decisions else {}
            if decision.get("selected_asset_code"):
                asset = self.repository.get_asset_selection(decision["selected_asset_code"])
                if asset is None or str(asset.get("status") or "").lower() in {"failed", "deleted", "archived"}:
                    issues.append(f"{requirement['requirement_code']}:asset_unavailable")
                elif snapshot is None or not _snapshot_contains_asset(snapshot, asset):
                    issues.append(f"{requirement['requirement_code']}:asset_outside_snapshot")
            elif decision.get("selected_material_key"):
                item = self.repository.get_inventory_snapshot_item(
                    run["inventory_snapshot_code"],
                    decision["selected_material_key"],
                )
                if item is None or item.get("availability_status") != "available":
                    issues.append(f"{requirement['requirement_code']}:material_unavailable")
            else:
                issues.append(f"{requirement['requirement_code']}:selection_missing")
        return not issues, ", ".join(issues) if issues else "All selected materials are available"

    @staticmethod
    def _add_check(
        checks: list[dict[str, Any]],
        code: str,
        passed: bool,
        detail: str,
        *,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        check = {"code": code, "passed": bool(passed), "detail": detail}
        if evidence is not None:
            check["evidence"] = evidence
        checks.append(check)


def assert_draft_only(value: Any, *, path: str = "$payload") -> None:
    if isinstance(value, dict):
        operation_type = str(value.get("operation_type") or "").strip().lower()
        if operation_type in FORBIDDEN_OPERATION_TYPES:
            raise WorkbenchDraftSafetyError(f"Forbidden live operation at {path}: {operation_type}")
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in {"ready_for_go_live", "go_live_permitted"} and item is not False:
                raise WorkbenchDraftSafetyError(f"Workbench execution is draft-only at {path}.{key}")
            if (
                normalized_key in FORBIDDEN_OPERATION_TYPES
                and item is not False
                and item is not None
                and item != ""
            ):
                raise WorkbenchDraftSafetyError(f"Forbidden live command at {path}.{key}")
            assert_draft_only(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_draft_only(item, path=f"{path}[{index}]")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _approved_script_sentence_catalog(
    facts: dict[str, Any],
) -> tuple[list[str], list[str]]:
    generic_sentences = [
        "正在为你介绍已核验的商品信息。",
        "可以先按用途和口味建立选择标准。",
        "具体规格请以商品页当前展示为准。",
        "需要继续比较时，可以把用途和口味告诉主播。",
    ]
    category_text = " ".join(
        str(value or "")
        for value in (facts.get("category"), facts.get("product_name"), facts.get("positioning"))
    )
    if any(keyword in category_text for keyword in ("酒", "wine", "Wine", "WINE")):
        generic_sentences.append("请适量饮酒，未成年人请勿饮酒，饮酒后不要驾车。")
    product_name = str(facts.get("product_name") or "").strip()
    positioning = str(facts.get("positioning") or "").strip()
    fact_sentences = [
        _ensure_sentence(f"现在介绍{product_name}") if product_name else "",
        _ensure_sentence(f"这款产品的定位是：{positioning}") if positioning else "",
    ]
    for field in ("verified_facts", "verified_promotion_claims", "compliance_notes"):
        for value in facts.get(field) or []:
            fact_sentences.extend(_split_or_ensure_sentences(str(value)))
    tasting_notes = [str(value).strip() for value in facts.get("tasting_notes") or [] if str(value).strip()]
    if tasting_notes:
        fact_sentences.append(_ensure_sentence(f"已核验的风味描述包括：{'、'.join(tasting_notes)}"))
    scenarios = [str(value).strip() for value in facts.get("scenarios") or [] if str(value).strip()]
    if scenarios:
        fact_sentences.append(_ensure_sentence(f"已核验的适用场景包括：{'、'.join(scenarios)}"))
    for field in ("selection_guidance", "objection_response"):
        value = str(facts.get(field) or "").strip()
        if value:
            fact_sentences.extend(_split_or_ensure_sentences(value))
    return _dedupe(fact_sentences), generic_sentences


def _approved_keyword_catalog(
    facts: dict[str, Any],
    inventory_keywords: list[str],
) -> list[str]:
    values: list[str] = [
        str(facts.get("product_name") or ""),
        str(facts.get("product_code") or ""),
        str(facts.get("brand") or ""),
        str(facts.get("category") or ""),
        *(str(value) for value in facts.get("asset_keywords") or []),
        *(str(value) for value in facts.get("tasting_notes") or []),
        *(str(value) for value in facts.get("scenarios") or []),
        *(str(value) for value in facts.get("compliance_notes") or []),
        *inventory_keywords,
        "主播",
        "数字人",
        "商品",
        "商品主图",
        "背景",
        "品牌",
        "口味",
        "用途",
        "合规",
    ]
    return _dedupe([_normalize_keyword(value) for value in values])


def _normalize_keyword(value: str) -> str:
    return " ".join(str(value or "").split())


def _split_script_sentences(script: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.findall(r".*?(?:[。！？!?]|$)", str(script).strip(), flags=re.DOTALL)
        if sentence.strip()
    ]


def _split_or_ensure_sentences(value: str) -> list[str]:
    sentences = _split_script_sentences(value)
    if not sentences:
        return []
    return [_ensure_sentence(sentence) for sentence in sentences]


def _ensure_sentence(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized and normalized[-1] not in "。！？!?":
        normalized += "。"
    return normalized


def _allocate_seconds(total_seconds: int, count: int) -> list[int]:
    if count < 1 or total_seconds < count:
        raise ValueError("Scene duration cannot be allocated")
    base, remainder = divmod(total_seconds, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _requirement_key(scene: dict[str, Any], selection: dict[str, Any]) -> str:
    return fingerprint(
        {
            "scene_index": int(scene.get("scene_index") or 0),
            "need_type": selection.get("need_type"),
            "required_category": selection.get("required_category"),
        }
    )


def _selection_fields_from_asset(asset: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "status": "selected",
        "selected_asset_code": asset.get("asset_code"),
        "selected_asset_type": asset.get("asset_type"),
        "selected_asset_title": asset.get("title"),
        "selected_asset_display_code": asset.get("display_code"),
        "selected_asset_local_file_code": asset.get("local_file_code"),
        "selected_asset_original_filename": asset.get("original_filename"),
        "selected_asset_local_relative_path": asset.get("local_relative_path"),
        "selected_asset_browser_use_hint": asset.get("browser_use_hint"),
        "selected_asset_maitu_material_id": asset.get("maitu_material_id"),
        "selected_asset_source_material_type": asset.get("source_material_type"),
        "selected_asset_source_material_url": asset.get("source_material_url"),
        "selected_asset_source_cover_url": asset.get("source_cover_url"),
        "selected_asset_speaker_id": asset.get("speaker_id"),
        "selected_asset_digital_human_image_id": asset.get("digital_human_image_id"),
        "selection_source": source,
        "match_reasons": ["manual workbench decision"],
        "match_score": 1.0,
        "candidate_count": 1,
    }


def _selection_fields_from_material(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "selected",
        "selected_asset_code": item.get("asset_code"),
        "selected_asset_type": None,
        "selected_asset_title": item.get("title"),
        "selected_asset_display_code": item.get("material_id") or item.get("item_key"),
        "selected_asset_local_file_code": None,
        "selected_asset_original_filename": None,
        "selected_asset_local_relative_path": None,
        "selected_asset_browser_use_hint": None,
        "selected_asset_maitu_material_id": item.get("material_id"),
        "selected_asset_source_material_type": item.get("material_type"),
        "selected_asset_source_material_url": item.get("source_material_url"),
        "selected_asset_source_cover_url": item.get("source_cover_url"),
        "selected_asset_speaker_id": item.get("speaker_id"),
        "selected_asset_digital_human_image_id": item.get("digital_human_image_id"),
        "selection_source": "workbench_manual_inventory_material",
        "match_reasons": ["manual workbench inventory decision"],
        "match_score": 1.0,
        "candidate_count": 1,
    }


def _snapshot_contains_asset(snapshot: dict[str, Any], asset: dict[str, Any]) -> bool:
    asset_code = str(asset.get("asset_code") or "")
    material_id = str(asset.get("maitu_material_id") or "")
    return any(
        item.get("availability_status") == "available"
        and (
            bool(asset_code and str(item.get("asset_code") or "") == asset_code)
            or bool(material_id and str(item.get("material_id") or "") == material_id)
        )
        for item in (snapshot.get("items") or [])
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
