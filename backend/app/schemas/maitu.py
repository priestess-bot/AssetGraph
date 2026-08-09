import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.core.maitu_retry_intent import is_canonical_retry_before_state
from app.core.secret_hygiene import (
    PUBLIC_SHA256_PROTOCOL_FIELDS,
    contains_durable_secret,
    find_invalid_public_sha256_field,
)
from app.schemas.assets import MaituAssetCategory, MaituReplacementPolicy


def _without_public_protocol_fields(value: Any) -> Any:
    invalid_sha256_field = find_invalid_public_sha256_field(value)
    if invalid_sha256_field is not None:
        raise ValueError(f"{invalid_sha256_field} must be a SHA-256 digest")

    def sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: sanitize(nested)
                for key, nested in item.items()
                if key
                not in PUBLIC_SHA256_PROTOCOL_FIELDS
                | {"source_material_url", "source_cover_url"}
            }
        if isinstance(item, list):
            return [sanitize(nested) for nested in item]
        return item

    return sanitize(value)


def _validate_secret_free_worker_identity(value: str) -> str:
    operator_token = settings.maitu_reconciliation_operator_token
    forbidden_values = (
        (operator_token.get_secret_value(),)
        if operator_token is not None and operator_token.get_secret_value()
        else ()
    )
    if contains_durable_secret(value, forbidden_values=forbidden_values):
        raise ValueError("worker identity must not contain credentials")
    return value


def _require_canonical_json_value(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_canonical_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _require_canonical_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains a non-JSON value")


class MaituLivestreamScriptProductBrief(BaseModel):
    product_name: str = Field(..., min_length=1, max_length=255)
    product_code: str | None = Field(default=None, max_length=64)
    positioning: str = Field(..., min_length=1)
    verified_facts: list[str] = Field(..., min_length=1)
    tasting_notes: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    selection_guidance: str | None = None
    objection_response: str | None = None
    asset_keywords: list[str] = Field(default_factory=list)
    verified_promotion_claims: list[str] = Field(default_factory=list)
    unverified_promotion_claims: list[str] = Field(default_factory=list)


class MaituLivestreamScriptDraftCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    platform: str = Field(default="京东", min_length=1, max_length=64)
    target_duration_minutes: int = Field(default=30, ge=1, le=480)
    words_per_minute: int = Field(default=165, ge=80, le=400)
    always_on_24h: bool = True
    catalog_total_verified: bool = False
    catalog_total: int | None = Field(default=None, ge=1)
    host_persona: str = Field(default="懂产品但不卖弄，替观众缩小选择", min_length=1)
    include_compliance_notice: bool = True
    products: list[MaituLivestreamScriptProductBrief] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_catalog_total(self) -> "MaituLivestreamScriptDraftCreate":
        if self.catalog_total_verified and self.catalog_total is None:
            raise ValueError("catalog_total is required when catalog_total_verified=true")
        return self


class MaituLivestreamScriptSectionRead(BaseModel):
    section_index: int
    section_type: str
    scene_name: str
    scene_goal: str
    product_name: str | None = None
    product_code: str | None = None
    duration_seconds: int
    script: str
    keywords: list[str] = Field(default_factory=list)
    information_owner: str
    manual_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class MaituLivestreamScriptQualityReportRead(BaseModel):
    catalog_scope_safe: bool
    time_neutral: bool
    padding_free: bool
    fresh_draft_from_structured_sources: bool
    duplicate_paragraph_count: int
    forbidden_hits: list[str] = Field(default_factory=list)
    dropped_unverified_claims: list[str] = Field(default_factory=list)
    removed_unverified_claim_sentences: list[str] = Field(default_factory=list)
    removed_duplicate_sentences: list[str] = Field(default_factory=list)
    chinese_character_count: int
    estimated_duration_seconds: int
    target_duration_seconds: int
    material_sufficiency_status: str
    warnings: list[str] = Field(default_factory=list)


class MaituLivestreamScriptDraftRead(BaseModel):
    source: str
    title: str
    platform: str
    target_duration_minutes: int
    always_on_24h: bool
    catalog_total_verified: bool
    spoken_script: str
    section_count: int
    sections: list[MaituLivestreamScriptSectionRead] = Field(default_factory=list)
    quality_report: MaituLivestreamScriptQualityReportRead
    scene_plan_payload: dict[str, Any]
    manual_review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class MaituScriptScenePlanCreate(BaseModel):
    script_text: str = Field(..., min_length=1)
    target_scene_count: int | None = Field(default=None, ge=1, le=50)
    default_scene_duration_seconds: int = Field(default=60, ge=5, le=3600)


class MaituScriptSceneRead(BaseModel):
    scene_index: int
    scene_name: str
    scene_goal: str
    duration_seconds: int
    script: str
    keywords: list[str] = Field(default_factory=list)
    manual_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class MaituScriptScenePlanRead(BaseModel):
    source: str
    scene_count: int
    target_scene_count: int | None = None
    manual_review_required: bool = False
    scenes: list[MaituScriptSceneRead] = Field(default_factory=list)


class MaituScriptAssetNeedCreate(BaseModel):
    scenes: list[MaituScriptSceneRead] = Field(..., min_length=1)
    include_default_host: bool = True
    include_script_text_need: bool = True


class MaituScriptAssetNeedRead(BaseModel):
    need_type: str
    required_category: str
    accepted_asset_types: list[str] = Field(default_factory=list)
    description: str
    keywords: list[str] = Field(default_factory=list)
    priority: str
    suggested_layer_role: str | None = None
    reason: str | None = None


class MaituScriptAssetNeedSceneRead(BaseModel):
    scene_index: int
    scene_name: str
    scene_goal: str
    duration_seconds: int
    script: str
    keywords: list[str] = Field(default_factory=list)
    asset_needs: list[MaituScriptAssetNeedRead] = Field(default_factory=list)
    manual_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class MaituScriptAssetNeedPlanRead(BaseModel):
    source: str
    scene_count: int
    manual_review_required: bool = False
    scenes: list[MaituScriptAssetNeedSceneRead] = Field(default_factory=list)


class MaituScriptAssetSelectionCreate(BaseModel):
    scenes: list[MaituScriptAssetNeedSceneRead] = Field(..., min_length=1)
    max_candidates_per_need: int = Field(default=1, ge=1, le=20)


class MaituScriptAssetSelectionRead(BaseModel):
    need_type: str
    required_category: str
    accepted_asset_types: list[str] = Field(default_factory=list)
    description: str
    keywords: list[str] = Field(default_factory=list)
    priority: str
    status: str
    selected_asset_code: str | None = None
    selected_asset_type: str | None = None
    selected_asset_title: str | None = None
    selected_asset_display_code: str | None = None
    selected_asset_local_file_code: str | None = None
    selected_asset_original_filename: str | None = None
    selected_asset_local_relative_path: str | None = None
    selected_asset_browser_use_hint: str | None = None
    selected_asset_maitu_material_id: int | None = None
    selected_asset_source_material_type: str | None = None
    selected_asset_source_material_url: str | None = None
    selected_asset_source_cover_url: str | None = None
    selected_asset_speaker_id: int | None = None
    selected_asset_digital_human_image_id: int | None = None
    selected_asset_sound_enabled: bool | None = None
    selected_asset_audio_role: str | None = None
    selected_asset_audio_classification_status: str | None = None
    selected_asset_audio_class: str | None = None
    selected_asset_material_roles: list[str] = Field(default_factory=list)
    selected_asset_constraint_rules: list[dict[str, Any]] = Field(default_factory=list)
    match_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    selection_source: str | None = None
    candidate_count: int = 0


class MaituScriptAssetSelectionSceneRead(BaseModel):
    scene_index: int
    scene_name: str
    scene_goal: str
    duration_seconds: int
    script: str
    keywords: list[str] = Field(default_factory=list)
    asset_selections: list[MaituScriptAssetSelectionRead] = Field(default_factory=list)
    selected_count: int = 0
    missing_count: int = 0
    missing_asset_needs: list[MaituScriptAssetNeedRead] = Field(default_factory=list)
    manual_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


class MaituScriptAssetSelectionPlanRead(BaseModel):
    source: str
    scene_count: int
    selected_count: int = 0
    missing_count: int = 0
    manual_review_required: bool = False
    scenes: list[MaituScriptAssetSelectionSceneRead] = Field(default_factory=list)


class MaituScriptAssetGapReportCreate(BaseModel):
    scenes: list[MaituScriptAssetSelectionSceneRead] = Field(..., min_length=1)


class MaituScriptAssetGapRead(BaseModel):
    need_type: str
    required_category: str
    accepted_asset_types: list[str] = Field(default_factory=list)
    priority: str
    missing_occurrences: int
    affected_scene_indexes: list[int] = Field(default_factory=list)
    affected_scene_names: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    blocks_auto_build: bool = False
    fallback_strategy: str
    recommended_asset_specs: list[dict[str, Any]] = Field(default_factory=list)


class MaituScriptAssetGapReportRead(BaseModel):
    source: str
    scene_count: int
    gap_count: int
    total_missing_occurrences: int
    blocking_gap_count: int
    can_build_with_fallback: bool
    readiness_status: str
    gaps: list[MaituScriptAssetGapRead] = Field(default_factory=list)


class MaituScriptLayoutPlanCreate(BaseModel):
    scenes: list[MaituScriptAssetSelectionSceneRead] = Field(..., min_length=1)
    build_mode: str = Field(default="strict", max_length=64)
    canvas_width: int = Field(default=1080, ge=1, le=10000)
    canvas_height: int = Field(default=1920, ge=1, le=10000)


class MaituScriptLayoutLayerRead(BaseModel):
    layer_id: str
    layer_type: str
    need_type: str
    role: str = ""
    material_roles: list[str] = Field(default_factory=list)
    status: str
    required_category: str | None = None
    asset_code: str | None = None
    asset_display_code: str | None = None
    asset_local_file_code: str | None = None
    asset_original_filename: str | None = None
    asset_local_relative_path: str | None = None
    asset_browser_use_hint: str | None = None
    maitu_material_id: int | None = None
    source_material_type: str | None = None
    source_material_url: str | None = None
    source_cover_url: str | None = None
    speaker_id: int | None = None
    digital_human_image_id: int | None = None
    sound_enabled: bool = False
    audio_role: str = "muted"
    audio_classification_status: str = "unknown"
    audio_class: str = "unknown"
    audio_start_seconds: float = Field(default=0, ge=0)
    audio_end_seconds: float = Field(default=1, gt=0)
    asset_title: str | None = None
    x: int
    y: int
    width: int
    height: int
    z_index: int
    fit: str = "contain"
    source_selection_status: str | None = None
    constraint_rules: list[dict[str, Any]] = Field(default_factory=list)
    constraint_evidence: dict[str, Any] = Field(default_factory=dict)


class MaituScriptLayoutSceneRead(BaseModel):
    scene_index: int
    scene_name: str
    scene_goal: str
    duration_seconds: int = Field(default=1, ge=1)
    status: str
    canvas: dict[str, int]
    layers: list[MaituScriptLayoutLayerRead] = Field(default_factory=list)
    script_block: dict[str, Any] = Field(default_factory=dict)
    missing_placeholders: list[dict[str, Any]] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    stacking_failures: list[str] = Field(default_factory=list)


class MaituScriptLayoutPlanRead(BaseModel):
    source: str
    build_mode: str
    status: str
    scene_count: int
    blocking_gap_count: int = 0
    can_generate_layout: bool
    can_generate_executable_build_plan: bool
    manual_review_required: bool = False
    scenes: list[MaituScriptLayoutSceneRead] = Field(default_factory=list)


class MaituScriptLayoutBuildPlanCreate(BaseModel):
    layout_plan: MaituScriptLayoutPlanRead
    target_live_room_id: str | None = Field(default=None, max_length=64)
    expected_title: str | None = Field(default=None, min_length=1, max_length=255)


class MaituScriptLayoutBuildPlanRead(BaseModel):
    source: str
    status: str
    target_live_room_id: str | None = None
    expected_title: str | None = None
    build_mode: str
    can_execute: bool
    manual_review_required: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    operation_count: int = 0
    operations: list[dict[str, Any]] = Field(default_factory=list)
    build_plan_code: str | None = None
    plan_name: str | None = None
    browser_use_operations_url: str | None = None


class MaituScriptDrivenBuildPipelineCreate(BaseModel):
    script_request: MaituLivestreamScriptDraftCreate
    build_mode: str = Field(default="strict", max_length=64)
    target_live_room_id: str | None = Field(default=None, max_length=64)
    include_default_host: bool = True
    max_candidates_per_need: int = Field(default=1, ge=1, le=20)
    canvas_width: int = Field(default=1080, ge=1, le=10000)
    canvas_height: int = Field(default=1920, ge=1, le=10000)


class MaituScriptDrivenBuildPipelineRead(BaseModel):
    source: str
    status: str
    ready_for_go_live: bool = False
    script_draft: MaituLivestreamScriptDraftRead
    scene_plan: MaituScriptScenePlanRead
    asset_need_plan: MaituScriptAssetNeedPlanRead
    asset_selection_plan: MaituScriptAssetSelectionPlanRead
    gap_report: MaituScriptAssetGapReportRead
    layout_plan: MaituScriptLayoutPlanRead
    build_plan: MaituScriptLayoutBuildPlanRead
    stage_order: list[str] = Field(default_factory=list)


class MaituScriptSceneTemplateMatchCreate(BaseModel):
    scenes: list[MaituScriptSceneRead] = Field(..., min_length=1)
    blueprint_code: str | None = Field(default=None, max_length=64)
    reference_room_id: str | None = Field(default=None, max_length=64)
    template_library_code: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    auto_select_assets: bool = True
    min_confidence_for_auto_match: float = Field(default=0.3, ge=0.0, le=1.0)
    candidate_scene_limit: int = Field(default=200, ge=1, le=1000)


class MaituScriptSceneComponentSelectionRead(BaseModel):
    component_template_code: str | None = None
    layer_name: str | None = None
    layer_role: str | None = None
    required_category: str | None = None
    accepted_asset_types: list[str] = Field(default_factory=list)
    replacement_policy: str | None = None
    status: str
    selected_asset_code: str | None = None
    selected_asset_title: str | None = None
    selected_asset_display_code: str | None = None
    selected_asset_local_file_code: str | None = None
    selected_asset_original_filename: str | None = None
    selected_asset_local_relative_path: str | None = None
    selected_asset_browser_use_hint: str | None = None
    match_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    selection_source: str | None = None


class MaituScriptSceneTemplateMatchItemRead(BaseModel):
    scene_index: int
    scene_name: str
    scene_goal: str
    duration_seconds: int
    script: str
    keywords: list[str] = Field(default_factory=list)
    matched_blueprint_code: str | None = None
    matched_template_library_code: str | None = None
    matched_template_scene_code: str | None = None
    matched_template_scene_name: str | None = None
    matched_template_scene_type: str | None = None
    matched_reference_clip_id: str | int | None = None
    matched_script_block_code: str | None = None
    matched_script_content: str | None = None
    component_count: int = 0
    confidence: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    manual_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    component_selections: list[MaituScriptSceneComponentSelectionRead] = Field(default_factory=list)


class MaituScriptSceneTemplateMatchRead(BaseModel):
    source: str
    scene_count: int
    matched_scene_count: int
    manual_review_required: bool = False
    matches: list[MaituScriptSceneTemplateMatchItemRead] = Field(default_factory=list)


class MaituLiveRoomBlueprintImportCreate(BaseModel):
    reference_profile: dict[str, Any]
    blueprint: dict[str, Any]


class MaituLiveRoomBlueprintRead(BaseModel):
    id: str
    blueprint_code: str
    reference_profile_code: str
    title: str
    platform: str | None = None
    room_type: str
    reference_room_id: str | None = None
    reference_room_name: str | None = None
    status: str
    description: str | None = None
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    script_blocks: list[dict[str, Any]] = Field(default_factory=list)
    material_tabs: list[dict[str, Any]] = Field(default_factory=list)
    workbench_tabs: list[dict[str, Any]] = Field(default_factory=list)
    safety_rules: list[str] = Field(default_factory=list)
    reference_profile: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituLiveRoomScriptMatchRead(BaseModel):
    script_block_code: str | None = None
    scene_name: str | None = None
    sort_order: int | None = None
    content: str


class MaituLiveRoomComponentRead(BaseModel):
    component_name: str | None = None
    component_type: str | None = None
    component_role: str | None = None
    material_id: int | None = None
    required_category: str | None = None
    material_tab: str | None = None
    source_material_type: str | None = None
    source_material_url: str | None = None
    source_cover_url: str | None = None
    placements: int = 0
    scene_names: list[str] = Field(default_factory=list)
    geometry_examples: list[dict[str, Any]] = Field(default_factory=list)


class MaituLiveRoomComponentPlacementRead(BaseModel):
    scene_template_code: str | None = None
    component_template_code: str | None = None
    scene_name: str | None = None
    scene_type: str | None = None
    reference_product_name: str | None = None
    reference_item_id: str | int | None = None
    reference_clip_id: str | int | None = None
    layer_code: str | None = None
    layer_name: str | None = None
    layer_role: str | None = None
    material_id: int | None = None
    material_tab: str | None = None
    source_material_type: str | None = None
    required_category: str | None = None
    accepted_asset_types: list[str] = Field(default_factory=list)
    replacement_policy: str | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    z_index: int | None = None
    speaker_id: int | None = None
    digital_human_image_id: int | None = None
    source_material_url: str | None = None
    source_cover_url: str | None = None


class MaituLiveRoomComponentSearchResultRead(BaseModel):
    blueprint_code: str
    title: str
    reference_room_id: str | None = None
    reference_room_name: str | None = None
    platform: str | None = None
    status: str
    room_type: str
    template_library_code: str | None = None
    component_index_source: str | None = None
    matched_script_blocks: list[MaituLiveRoomScriptMatchRead] = Field(default_factory=list)
    matched_scene_names: list[str] = Field(default_factory=list)
    matched_scene_count: int = 0
    scene_count: int = 0
    script_block_count: int = 0
    unique_component_count: int = 0
    component_placement_count: int = 0
    components: list[MaituLiveRoomComponentRead] = Field(default_factory=list)
    component_placements: list[MaituLiveRoomComponentPlacementRead] = Field(default_factory=list)


class MaituLiveRoomTemplateSceneRead(BaseModel):
    id: str | None = None
    blueprint_code: str
    template_library_code: str | None = None
    scene_template_code: str
    scene_code: str | None = None
    scene_name: str
    scene_type: str | None = None
    sort_order: int | None = None
    reference_product_name: str | None = None
    reference_item_id: str | int | None = None
    reference_clip_id: str | int | None = None
    script_block_code: str | None = None
    script_sort_order: int | None = None
    script_content: str | None = None
    component_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituLiveRoomTemplateComponentRead(BaseModel):
    id: str | None = None
    blueprint_code: str
    template_library_code: str | None = None
    scene_template_code: str
    component_template_code: str
    scene_code: str | None = None
    scene_name: str
    scene_type: str | None = None
    reference_product_name: str | None = None
    reference_item_id: str | int | None = None
    reference_clip_id: str | int | None = None
    component_name: str | None = None
    component_type: str | None = None
    component_role: str | None = None
    layer_code: str | None = None
    layer_name: str | None = None
    layer_role: str | None = None
    material_id: int | None = None
    material_tab: str | None = None
    source_material_type: str | None = None
    required_category: str | None = None
    accepted_asset_types: list[str] = Field(default_factory=list)
    replacement_policy: str | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    z_index: int | None = None
    speaker_id: int | None = None
    digital_human_image_id: int | None = None
    source_material_url: str | None = None
    source_cover_url: str | None = None
    sort_order: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituLiveRoomBuildPlanCreate(BaseModel):
    blueprint_code: str = Field(..., min_length=1, max_length=64)
    plan_name: str | None = Field(default=None, max_length=255)
    strategy: str = Field(default="reference_rebuild_dry_run", max_length=64)
    description: str | None = None
    auto_select_assets: bool = False
    selection_query: str | None = None


class MaituLiveRoomSceneBuildPlanCreate(BaseModel):
    blueprint_code: str | None = Field(default=None, max_length=64)
    reference_room_id: str | None = Field(default=None, max_length=64)
    template_library_code: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    script_query: str = Field(..., min_length=1)
    target_script_content: str | None = Field(default=None, min_length=1)
    target_live_room_id: str | None = Field(default=None, min_length=1, max_length=64)
    plan_name: str | None = Field(default=None, max_length=255)
    strategy: str = Field(default="template_scene_dry_run", max_length=64)
    description: str | None = None


class MaituLiveRoomBuildPlanOperationRead(BaseModel):
    model_config = ConfigDict(extra="allow")

    operation_type: str
    operation_name: str
    sort_order: int
    status: str
    scene_name: str | None = None
    layer_name: str | None = None
    layer_role: str | None = None
    required_category: str | None = None
    accepted_asset_types: list[str] = Field(default_factory=list)
    replacement_policy: str | None = None
    selected_asset_code: str | None = None
    selected_asset_title: str | None = None
    selected_asset_display_code: str | None = None
    selected_asset_local_file_code: str | None = None
    selected_asset_original_filename: str | None = None
    selected_asset_local_relative_path: str | None = None
    selected_asset_browser_use_hint: str | None = None
    match_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    selection_source: str | None = None
    script_block_code: str | None = None
    script_block_content: str | None = None
    target_live_room_id: str | None = None
    scene_index: int | None = None
    layer_id: str | None = None
    layer_type: str | None = None
    need_type: str | None = None
    asset_code: str | None = None
    asset_display_code: str | None = None
    asset_local_file_code: str | None = None
    asset_original_filename: str | None = None
    asset_local_relative_path: str | None = None
    asset_browser_use_hint: str | None = None
    material_id: int | None = None
    maitu_material_id: int | None = None
    source_material_type: str | None = None
    source_material_url: str | None = None
    source_cover_url: str | None = None
    speaker_id: int | None = None
    digital_human_image_id: int | None = None
    x: int | float | None = None
    y: int | float | None = None
    width: int | float | None = None
    height: int | float | None = None
    z_index: int | None = None
    script_text: str | None = None
    blocked_reason: str | None = None
    blocks_execution: bool | None = None
    instruction: str
    details: dict[str, Any] = Field(default_factory=dict)


class MaituLiveRoomBuildPlanRead(BaseModel):
    id: str
    build_plan_code: str
    blueprint_code: str | None = None
    plan_name: str
    target_app: str = "maitu"
    executor: str = "browser_use"
    status: str
    strategy: str
    description: str | None = None
    operations: list[MaituLiveRoomBuildPlanOperationRead] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituLiveRoomBuildPlanOperationPlanResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    build_plan_code: str
    blueprint_code: str | None = None
    reference_room_id: str | None = None
    reference_room_name: str | None = None
    target_live_room_id: str | None = None
    executor: str = "browser_use"
    target_app: str = "maitu"
    source: str | None = None
    status: str | None = None
    build_mode: str | None = None
    can_execute: bool | None = None
    manual_review_required: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    checkpoint_source_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    operations: list[MaituLiveRoomBuildPlanOperationRead] = Field(default_factory=list)


class MaituLiveRoomBuildPlanOperationResultCreate(BaseModel):
    operation_index: int = Field(..., ge=0)
    operation_type: str = Field(..., max_length=64)
    operation_name: str | None = Field(default=None, max_length=255)
    scene_name: str | None = Field(default=None, max_length=128)
    layer_name: str | None = Field(default=None, max_length=128)
    scene_index: int | None = Field(default=None, ge=0)
    clip_id: int | None = None
    layer_id: str | int | None = None
    layer_type: str | None = Field(default=None, max_length=64)
    asset_code: str | None = Field(default=None, max_length=64)
    action_type: str | None = Field(default=None, max_length=64)
    status: str = Field(..., max_length=32)
    failure_type: str | None = Field(default=None, max_length=64)
    retryable: bool = False
    retry_instruction: str | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    dom_snapshot_asset_code: str | None = Field(default=None, max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)


class MaituLiveRoomBuildPlanOperationResultRead(MaituLiveRoomBuildPlanOperationResultCreate):
    id: str | None = None
    sort_order: int = 0
    operation_fingerprint: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    effect_class: Literal["mutating", "read_only", "manual_noop"] | None = None
    intent_snapshot: dict[str, Any] | None = None
    checkpoint_state: Literal[
        "not_started",
        "prepared",
        "dispatched",
        "reconcile_required",
        "retry_authorized",
        "completed",
        "observed",
        "manual_required",
    ] | None = None
    decision: Literal["execute", "skip", "reconcile"] | None = None
    attempt_id: UUID | None = None
    completion_id: UUID | None = None
    completion_evidence: dict[str, Any] = Field(default_factory=dict)
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
    reconciled_attempt_id: UUID | None = None
    reconciliation_resolution: Literal["confirmed_completed", "confirmed_not_applied"] | None = None
    reconciliation_evidence: dict[str, Any] = Field(default_factory=dict)
    reconciled_at: datetime | None = None


class MaituLiveRoomBuildPlanExecutionResultCreate(BaseModel):
    executor: str = Field(default="browser_use", max_length=64)
    execution_status: str = Field(..., max_length=32)
    mode: str = Field(default="non_destructive", max_length=64)
    failure_type: str | None = Field(default=None, max_length=64)
    retryable: bool = False
    retry_instruction: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    dom_snapshot_asset_code: str | None = Field(default=None, max_length=64)
    result_summary: str | None = None
    ready_for_go_live: bool = False
    manual_review_required: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    operation_results: list[MaituLiveRoomBuildPlanOperationResultCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_operation_indexes(self) -> "MaituLiveRoomBuildPlanExecutionResultCreate":
        indexes = [item.operation_index for item in self.operation_results]
        if len(indexes) != len(set(indexes)):
            raise ValueError("operation_results must not contain duplicate operation_index values")
        return self


class MaituLiveRoomBuildPlanExecutionResultRead(BaseModel):
    id: str
    execution_code: str
    build_plan_code: str
    blueprint_code: str | None = None
    execution_attempt_id: UUID | None = None
    plan_fingerprint: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    manifest_fingerprint: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    expected_operation_count: int | None = Field(default=None, ge=0)
    checkpoint_contract: str | None = Field(default=None, max_length=64)
    lease_version: int = Field(default=0, ge=0)
    lease_acquired_at: datetime | None = None
    lease_expires_at: datetime | None = None
    lease_reconcile_not_before: datetime | None = None
    finalization_id: UUID | None = None
    finalization_fingerprint: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    finalized_at: datetime | None = None
    executor: str
    execution_status: str
    mode: str
    failure_type: str | None = None
    retryable: bool = False
    retry_instruction: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = None
    dom_snapshot_asset_code: str | None = None
    result_summary: str | None = None
    ready_for_go_live: bool = False
    manual_review_required: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    operation_results: list[MaituLiveRoomBuildPlanOperationResultRead] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituScriptLayoutExecutionLeaseRead(MaituLiveRoomBuildPlanExecutionResultRead):
    start_request_id: UUID
    run_attempt_id: UUID
    lease_owner: str = Field(max_length=128)
    lease_token: UUID


class MaituScriptLayoutExecutionManifestOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_index: int = Field(ge=0)
    intent: dict[str, Any]

    @model_validator(mode="after")
    def require_canonical_secret_free_intent(self) -> "MaituScriptLayoutExecutionManifestOperation":
        _require_canonical_json_value(self.intent)
        if contains_durable_secret(_without_public_protocol_fields(self.intent)):
            raise ValueError("operation intent must not contain credentials")
        return self


class MaituScriptLayoutExecutionStartCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_request_id: UUID
    run_attempt_id: UUID
    source_plan_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    target_live_room_id: str = Field(min_length=1, max_length=64)
    operations: list[MaituScriptLayoutExecutionManifestOperation] = Field(min_length=1)
    mode: Literal["script_layout_draft"] = "script_layout_draft"
    checkpoint_contract: Literal["script_layout_checkpoint_v1"] = "script_layout_checkpoint_v1"

    @model_validator(mode="after")
    def require_distinct_identities_and_exact_manifest_indexes(self) -> "MaituScriptLayoutExecutionStartCreate":
        if self.start_request_id == self.run_attempt_id:
            raise ValueError("start_request_id and run_attempt_id must differ")
        indexes = [item.operation_index for item in self.operations]
        if indexes != list(range(len(indexes))):
            raise ValueError("operations must contain each contiguous operation_index exactly once")
        first_intent = self.operations[0].intent
        if (
            first_intent.get("operation_type") != "preflight_content_build_plan"
            or first_intent.get("status") != "ready"
            or str(first_intent.get("target_live_room_id") or self.target_live_room_id) != self.target_live_room_id
        ):
            raise ValueError("operations must start with target-bound ready preflight")
        return self


class MaituScriptLayoutExecutionCheckpointBeginCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    attempt_id: UUID
    lease_token: UUID
    lease_version: int = Field(ge=1)


class MaituScriptLayoutExecutionCheckpointDispatchCreate(MaituScriptLayoutExecutionCheckpointBeginCreate):
    pass


class MaituScriptLayoutExecutionRenewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_attempt_id: UUID
    lease_token: UUID
    lease_version: int = Field(ge=1)


class MaituScriptLayoutExecutionCheckpointInvalidateCreate(MaituScriptLayoutExecutionCheckpointBeginCreate):
    evidence: dict[str, Any]

    @model_validator(mode="after")
    def require_verified_invalidation_evidence(self) -> "MaituScriptLayoutExecutionCheckpointInvalidateCreate":
        if self.evidence.get("verified") is not True or self.evidence.get("checkpoint_invalid") is not True:
            raise ValueError("checkpoint invalidation requires verified checkpoint_invalid evidence")
        if "readback_attestation" in self.evidence or "readback_attestation_algorithm" in self.evidence:
            raise ValueError("checkpoint invalidation must not contain a client-supplied attestation")
        public_evidence_fields = {
            "operation_fingerprint",
        }
        secret_evidence = {key: value for key, value in self.evidence.items() if key not in public_evidence_fields}
        if contains_durable_secret(_without_public_protocol_fields(secret_evidence)):
            raise ValueError("checkpoint invalidation evidence must not contain credentials")
        return self


class MaituScriptLayoutExecutionCheckpointCompleteCreate(MaituScriptLayoutExecutionCheckpointBeginCreate):
    completion_id: UUID
    result_summary: str | None = None
    evidence: dict[str, Any]
    operation_result: MaituLiveRoomBuildPlanOperationResultCreate

    @model_validator(mode="after")
    def require_verified_matching_evidence(self) -> "MaituScriptLayoutExecutionCheckpointCompleteCreate":
        if self.completion_id == self.attempt_id:
            raise ValueError("completion_id must differ from attempt_id")
        if self.evidence.get("verified") is not True:
            raise ValueError("checkpoint evidence must contain verified=true")
        for field_name in ("operation_index", "operation_type"):
            evidence_value = self.evidence.get(field_name)
            result_value = getattr(self.operation_result, field_name)
            if evidence_value is not None and evidence_value != result_value:
                raise ValueError(f"checkpoint evidence {field_name} must match operation_result")
        if "readback_attestation" in self.evidence or "readback_attestation_algorithm" in self.evidence:
            raise ValueError("checkpoint completion must not contain a client-supplied attestation")
        public_evidence_fields = {
            "operation_fingerprint",
        }
        secret_evidence = {key: value for key, value in self.evidence.items() if key not in public_evidence_fields}
        durable_payload = {
            "result_summary": self.result_summary,
            "evidence": secret_evidence,
            "operation_result": self.operation_result.model_dump(exclude_none=True),
        }
        if contains_durable_secret(_without_public_protocol_fields(durable_payload)):
            raise ValueError("checkpoint durable fields must not contain credentials")
        return self


class MaituScriptLayoutExecutionCheckpointReconcileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    reconciliation_id: UUID
    reconciled_attempt_id: UUID
    resolution: Literal["confirmed_completed", "confirmed_not_applied"]
    resolution_summary: str = Field(min_length=1)
    evidence: dict[str, Any]
    operation_result: MaituLiveRoomBuildPlanOperationResultCreate | None = None

    @model_validator(mode="after")
    def require_verified_resolution_evidence(self) -> "MaituScriptLayoutExecutionCheckpointReconcileCreate":
        if self.evidence.get("verified") is not True:
            raise ValueError("reconciliation evidence must contain verified=true")
        expected_applied = self.resolution == "confirmed_completed"
        if self.evidence.get("operation_applied") is not expected_applied:
            raise ValueError("reconciliation evidence operation_applied must match resolution")
        if expected_applied and self.operation_result is None:
            raise ValueError("confirmed_completed reconciliation requires operation_result")
        if not expected_applied and self.operation_result is not None:
            raise ValueError("confirmed_not_applied reconciliation must not include operation_result")
        if self.operation_result is not None:
            for field_name in ("operation_index", "operation_type"):
                evidence_value = self.evidence.get(field_name)
                result_value = getattr(self.operation_result, field_name)
                if evidence_value != result_value:
                    raise ValueError(f"reconciliation evidence {field_name} must match operation_result")
        if "readback_attestation" in self.evidence or "readback_attestation_algorithm" in self.evidence:
            raise ValueError("checkpoint reconciliation must not contain a client-supplied attestation")
        public_evidence_fields = {
            "operation_fingerprint",
        }
        secret_evidence = {key: value for key, value in self.evidence.items() if key not in public_evidence_fields}
        durable_payload = {
            "resolution_summary": self.resolution_summary,
            "evidence": secret_evidence,
            "operation_result": self.operation_result.model_dump(exclude_none=True) if self.operation_result else None,
        }
        if contains_durable_secret(_without_public_protocol_fields(durable_payload)):
            raise ValueError("reconciliation durable fields must not contain credentials")
        return self


class MaituScriptLayoutExecutionFinalizeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finalization_id: UUID
    run_attempt_id: UUID
    lease_token: UUID
    lease_version: int = Field(ge=1)
    executor: Literal["browser_use"] = "browser_use"
    execution_status: Literal["completed", "completed_with_manual_review", "failed", "blocked"]
    mode: Literal["script_layout_draft"] = "script_layout_draft"
    failure_type: str | None = Field(default=None, max_length=64)
    retryable: bool = False
    retry_instruction: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    dom_snapshot_asset_code: str | None = Field(default=None, max_length=64)
    result_summary: str | None = None
    ready_for_go_live: bool = False
    manual_review_required: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_safe_draft_finalization_flags(self) -> "MaituScriptLayoutExecutionFinalizeCreate":
        if self.ready_for_go_live:
            raise ValueError("script-layout draft execution can never declare ready_for_go_live")
        if self.execution_status == "completed" and self.manual_review_required:
            raise ValueError("completed execution cannot require manual review")
        if self.execution_status == "completed_with_manual_review" and not self.manual_review_required:
            raise ValueError("completed_with_manual_review requires manual_review_required=true")
        return self


JD_LIVE_CORE_METRIC_NAMES = [
    "online_viewers",
    "average_stay_seconds",
    "product_click_rate",
    "product_conversion_rate",
    "gmv",
    "uv_value",
    "product_exposures",
    "product_clicks",
    "transaction_count",
    "transaction_amount",
    "traffic_sources",
    "interaction_data",
]


class MaituJdLiveMetricSessionCreate(BaseModel):
    build_plan_code: str | None = Field(default=None, max_length=64)
    frontend_execution_code: str | None = Field(default=None, max_length=64)
    live_room_id: str | None = Field(default=None, max_length=64)
    jd_live_id: str | None = Field(default=None, max_length=128)
    jd_shop_name: str | None = Field(default=None, max_length=255)
    dashboard_url: str | None = None
    status: str = Field(default="planned", max_length=32)
    capture_interval_seconds: int = Field(default=30, ge=5, le=3600)
    sync_start_mode: str = Field(default="with_frontend_agent", max_length=64)
    current_scene_name: str | None = Field(default=None, max_length=128)
    current_scene_index: int | None = Field(default=None, ge=0)
    metric_names: list[str] = Field(default_factory=lambda: list(JD_LIVE_CORE_METRIC_NAMES))
    scene_schedule: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    result_summary: str | None = None


class MaituJdLiveMetricSessionUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    current_scene_name: str | None = Field(default=None, max_length=128)
    current_scene_index: int | None = Field(default=None, ge=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: str | None = None
    error_message: str | None = None


class MaituJdLiveMetricSessionRead(MaituJdLiveMetricSessionCreate):
    id: str
    capture_session_code: str
    finished_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituJdLiveMetricSampleCreate(BaseModel):
    sampled_at: datetime | None = None
    scene_name: str | None = Field(default=None, max_length=128)
    scene_index: int | None = Field(default=None, ge=0)
    frontend_event_code: str | None = Field(default=None, max_length=64)
    live_elapsed_seconds: int | None = Field(default=None, ge=0)
    online_viewers: int | None = Field(default=None, ge=0)
    average_stay_seconds: float | None = Field(default=None, ge=0)
    product_click_rate: float | None = Field(default=None, ge=0)
    product_conversion_rate: float | None = Field(default=None, ge=0)
    gmv: float | None = Field(default=None, ge=0)
    uv_value: float | None = Field(default=None, ge=0)
    product_exposures: int | None = Field(default=None, ge=0)
    product_clicks: int | None = Field(default=None, ge=0)
    transaction_count: int | None = Field(default=None, ge=0)
    transaction_amount: float | None = Field(default=None, ge=0)
    traffic_sources: dict[str, Any] = Field(default_factory=dict)
    interaction_data: dict[str, Any] = Field(default_factory=dict)
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    dom_snapshot_asset_code: str | None = Field(default=None, max_length=64)
    status: str = Field(default="captured", max_length=32)


class MaituJdLiveMetricSampleRead(MaituJdLiveMetricSampleCreate):
    id: str
    capture_session_code: str
    sample_index: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituLayerGeometry(BaseModel):
    x: float = Field(..., ge=0)
    y: float = Field(..., ge=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)
    rotation: float = 0.0
    z_index: int | None = None


class MaituLayoutAdjustmentCreate(BaseModel):
    build_plan_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    layer_name: str | None = Field(default=None, max_length=128)
    user_instruction: str = Field(..., min_length=1)
    before_geometry: MaituLayerGeometry
    canvas_width: float = Field(..., gt=0)
    canvas_height: float = Field(..., gt=0)
    safe_margin: float = Field(default=20, ge=0)


class MaituLayoutAdjustmentRead(BaseModel):
    id: str
    adjustment_code: str
    build_plan_code: str | None = None
    scene_name: str | None = None
    layer_name: str | None = None
    user_instruction: str
    status: str
    before_geometry: dict[str, Any]
    target_geometry: dict[str, Any]
    operation: dict[str, Any]
    checks: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituMaterialSlotCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    slot_name: str = Field(..., min_length=1, max_length=128)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    scene_index: int | None = Field(default=None, ge=0)
    layer_name: str | None = Field(default=None, max_length=128)
    layer_index: int | None = Field(default=None, ge=0)
    target_live_room_id: str | None = Field(default=None, min_length=1, max_length=64)
    target_clip_id: int | None = Field(default=None, gt=0)
    target_layer_id: int | None = Field(default=None, gt=0)
    expected_before_state: dict[str, Any] = Field(default_factory=dict)
    required_category: MaituAssetCategory
    accepted_asset_types: list[str] = Field(default_factory=list)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    left_position: float | None = Field(default=None, ge=0)
    top_position: float | None = Field(default=None, ge=0)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    z_index: int | None = None
    replacement_policy: MaituReplacementPolicy = MaituReplacementPolicy.KEEP_LAYOUT
    description: str | None = None

    @model_validator(mode="after")
    def validate_expected_before_state(self) -> "MaituMaterialSlotCreate":
        if self.expected_before_state and not is_canonical_retry_before_state(
            self.expected_before_state,
            target_layer_id=self.target_layer_id,
        ):
            raise ValueError("expected_before_state must be an exact canonical layer snapshot")
        return self


class MaituMaterialSlotUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    slot_name: str | None = Field(default=None, min_length=1, max_length=128)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    scene_index: int | None = Field(default=None, ge=0)
    layer_name: str | None = Field(default=None, max_length=128)
    layer_index: int | None = Field(default=None, ge=0)
    target_live_room_id: str | None = Field(default=None, min_length=1, max_length=64)
    target_clip_id: int | None = Field(default=None, gt=0)
    target_layer_id: int | None = Field(default=None, gt=0)
    expected_before_state: dict[str, Any] = Field(default_factory=dict)
    required_category: MaituAssetCategory | None = None
    accepted_asset_types: list[str] | None = None
    aspect_ratio: str | None = Field(default=None, max_length=32)
    left_position: float | None = Field(default=None, ge=0)
    top_position: float | None = Field(default=None, ge=0)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    z_index: int | None = None
    replacement_policy: MaituReplacementPolicy | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_expected_before_state(self) -> "MaituMaterialSlotUpdate":
        target_layer_updated = "target_layer_id" in self.model_fields_set
        before_state_updated = "expected_before_state" in self.model_fields_set
        if target_layer_updated and not before_state_updated:
            raise ValueError("target_layer_id and expected_before_state must be updated together")
        if self.expected_before_state and not target_layer_updated:
            raise ValueError("target_layer_id and expected_before_state must be updated together")
        if self.expected_before_state and not is_canonical_retry_before_state(
            self.expected_before_state,
            target_layer_id=self.target_layer_id,
        ):
            raise ValueError("expected_before_state must be an exact canonical layer snapshot")
        return self


class MaituMaterialSlotRead(MaituMaterialSlotCreate):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    slot_code: str


class MaituCandidateAssetRead(BaseModel):
    asset_code: str
    asset_type: str
    title: str | None = None
    original_filename: str | None = None
    display_code: str | None = None
    local_file_code: str | None = None
    maitu_category: str | None = None
    maitu_project_code: str | None = None
    maitu_scene_name: str | None = None
    maitu_layer_name: str | None = None
    maitu_slot_name: str | None = None
    maitu_slot_code: str | None = None
    layer_width: float | None = None
    layer_height: float | None = None
    replacement_policy: str | None = None
    match_score: float
    retrieval_score: float | None = None
    content_excerpt: str | None = None
    match_reasons: list[str] = Field(default_factory=list)


class MaituCandidateAssetsResponse(BaseModel):
    slot_code: str
    required_category: str
    accepted_asset_types: list[str]
    source: str = "rule_filter"
    semantic_query: str | None = None
    embedding_model: str | None = None
    rerank_model: str | None = None
    assets: list[MaituCandidateAssetRead]


class MaituReplacementPlanCreate(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=255)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    target_live_room_id: str | None = Field(default=None, min_length=1, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    slot_codes: list[str] = Field(default_factory=list)
    strategy: str = Field(default="best_match", max_length=64)
    description: str | None = None


class MaituReplacementPlanItemRead(BaseModel):
    slot_code: str
    slot_name: str | None = None
    required_category: str | None = None
    selected_asset_code: str | None = None
    selected_asset_title: str | None = None
    match_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    replacement_policy: str | None = None
    sort_order: int = 0
    status: str


class MaituReplacementPlanRead(BaseModel):
    id: str
    plan_code: str
    plan_name: str
    maitu_project_code: str | None = None
    target_live_room_id: str | None = None
    scene_name: str | None = None
    status: str
    strategy: str
    description: str | None = None
    items: list[MaituReplacementPlanItemRead] = Field(default_factory=list)


class MaituBrowserUseOperationRead(BaseModel):
    operation_type: str
    slot_code: str
    slot_name: str | None = None
    scene_name: str | None = None
    layer_name: str | None = None
    asset_code: str | None = None
    asset_title: str | None = None
    asset_display_code: str | None = None
    asset_local_file_code: str | None = None
    asset_original_filename: str | None = None
    asset_local_relative_path: str | None = None
    asset_browser_use_hint: str | None = None
    replacement_policy: str | None = None
    status: str
    instruction: str


class MaituBrowserUseOperationPlanResponse(BaseModel):
    plan_code: str
    executor: str = "browser_use"
    target_app: str = "maitu"
    maitu_project_code: str | None = None
    scene_name: str | None = None
    operations: list[MaituBrowserUseOperationRead] = Field(default_factory=list)


class MaituBrowserUseOperationResultCreate(BaseModel):
    slot_code: str = Field(..., max_length=64)
    operation_type: str = Field(default="replace_layer_asset", max_length=64)
    asset_code: str | None = Field(default=None, max_length=64)
    status: str = Field(..., max_length=32)
    failure_type: str | None = Field(default=None, max_length=64)
    retryable: bool = False
    retry_instruction: str | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)


class MaituBrowserUseOperationResultRead(MaituBrowserUseOperationResultCreate):
    id: str | None = None
    sort_order: int = 0


class MaituReplacementPlanExecutionResultCreate(BaseModel):
    executor: str = Field(default="browser_use", max_length=64)
    execution_status: str = Field(..., max_length=32)
    failure_type: str | None = Field(default=None, max_length=64)
    retryable: bool = False
    retry_instruction: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    result_summary: str | None = None
    operation_results: list[MaituBrowserUseOperationResultCreate] = Field(default_factory=list)


class MaituReplacementPlanExecutionResultRead(BaseModel):
    id: str
    execution_code: str
    plan_code: str
    executor: str
    execution_status: str
    failure_type: str | None = None
    retryable: bool = False
    retry_instruction: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = None
    result_summary: str | None = None
    operation_results: list[MaituBrowserUseOperationResultRead] = Field(default_factory=list)
    created_at: datetime | None = None


class MaituRetryTaskRead(BaseModel):
    id: str
    retry_task_code: str
    plan_code: str
    execution_code: str
    slot_code: str | None = None
    asset_code: str | None = None
    executor: str
    failure_type: str | None = None
    retryable: bool = True
    retry_instruction: str | None = None
    status: str
    error_message: str | None = None
    screenshot_asset_code: str | None = None
    retry_attempt_count: int = 0
    last_retry_execution_code: str | None = None
    result_summary: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
    lease_version: int = 0
    last_retry_execution_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituRetryQueueItemRead(MaituRetryTaskRead):
    maitu_project_code: str | None = None
    scene_name: str | None = None
    slot_name: str | None = None
    layer_name: str | None = None
    next_operation_type: str
    browser_use_operations_url: str


class MaituRetryClaimedQueueItemRead(MaituRetryQueueItemRead):
    claim_token: UUID
    lease_version: int = Field(..., ge=1)


class MaituRetryQueueClaimNextCreate(BaseModel):
    claimed_by: str = Field(..., min_length=1, max_length=128)
    lock_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    failure_type: str | None = Field(default=None, max_length=64)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    max_attempts: int = Field(default=3, ge=1)

    validate_claimed_by = field_validator("claimed_by")(_validate_secret_free_worker_identity)


class MaituRetryLeaseIdentity(BaseModel):
    claimed_by: str = Field(..., min_length=1, max_length=128)
    claim_token: UUID
    lease_version: int = Field(..., ge=1)

    validate_claimed_by = field_validator("claimed_by")(_validate_secret_free_worker_identity)


class MaituRetryOperationCheckpointBeginCreate(MaituRetryLeaseIdentity):
    attempt_id: UUID
    operation_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def reject_claim_token_as_attempt_id(self) -> "MaituRetryOperationCheckpointBeginCreate":
        if self.attempt_id == self.claim_token:
            raise ValueError("checkpoint attempt_id must not equal the active claim token")
        return self


class MaituRetryOperationCheckpointCompleteCreate(MaituRetryOperationCheckpointBeginCreate):
    completion_id: UUID
    result_summary: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_verified_secret_free_evidence(self) -> "MaituRetryOperationCheckpointCompleteCreate":
        if self.completion_id == self.claim_token:
            raise ValueError("checkpoint completion_id must not equal the active claim token")
        if self.evidence.get("verified") is not True:
            raise ValueError("checkpoint evidence must contain verified=true")

        operator_token = settings.maitu_reconciliation_operator_token
        forbidden_values = (
            (operator_token.get_secret_value(),)
            if operator_token is not None and operator_token.get_secret_value()
            else ()
        )
        if contains_durable_secret(
            {
                "result_summary": self.result_summary,
                "evidence": self.evidence,
            },
            forbidden_values=forbidden_values,
        ):
            raise ValueError("checkpoint durable fields must not contain credentials or the active claim token")
        return self


class MaituRetryOperationReconciliationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_id: UUID
    expected_attempt_id: UUID
    operation_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    resolution: Literal["confirmed_completed", "confirmed_not_applied"]
    resolution_summary: str = Field(min_length=1, max_length=2000)
    evidence: dict[str, Any]

    @model_validator(mode="after")
    def require_authoritative_secret_free_evidence(self) -> "MaituRetryOperationReconciliationCreate":
        expected_applied = self.resolution == "confirmed_completed"
        if self.evidence.get("verified") is not True:
            raise ValueError("reconciliation evidence must contain verified=true")
        if self.evidence.get("operation_applied") is not expected_applied:
            raise ValueError("reconciliation evidence operation_applied must match resolution")

        if contains_durable_secret(
            {
                "resolution_summary": self.resolution_summary,
                "evidence": self.evidence,
            }
        ):
            raise ValueError("reconciliation durable fields must not contain credentials")
        return self


class MaituRetryOperationReconciliationRead(BaseModel):
    reconciliation_id: UUID
    retry_task_code: str
    operation_key: str
    reconciled_attempt_id: UUID
    operation_fingerprint: str
    resolution: Literal["confirmed_completed", "confirmed_not_applied"]
    resulting_state: Literal["completed", "retry_authorized"]
    resolved_by: str
    resolution_summary: str
    evidence: dict[str, Any]
    result_fingerprint: str
    created_at: datetime | None = None


class MaituRetryOperationCheckpointRead(BaseModel):
    retry_task_code: str
    operation_key: str
    operation_fingerprint: str
    state: Literal["begun", "reconcile_required", "retry_authorized", "completed"]
    decision: Literal["execute", "skip", "reconcile"] | None = None
    attempt_id: UUID
    begun_by: str
    begun_lease_version: int
    completion_id: UUID | None = None
    completion_fingerprint: str | None = None
    result_summary: str | None = None
    completed_by: str | None = None
    completed_lease_version: int | None = None
    completion_source: Literal["worker", "reconciliation"] | None = None
    completion_reconciliation_id: UUID | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    begun_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituRetryTaskHeartbeatCreate(MaituRetryLeaseIdentity):
    lock_ttl_seconds: int = Field(default=900, ge=60, le=86400)


class MaituRetryTaskReleaseCreate(MaituRetryLeaseIdentity):
    status: Literal["pending"] = "pending"
    result_summary: str | None = None


class MaituRetryQueueReclaimExpiredResponse(BaseModel):
    reclaimed_count: int
    retry_task_codes: list[str] = Field(default_factory=list)


class MaituRetryTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_summary: str | None = None
    retry_instruction: str | None = None


class MaituRetryTaskExecutionResultCreate(MaituRetryLeaseIdentity):
    retry_execution_id: UUID
    retry_execution_status: Literal["succeeded", "failed", "manual_required", "released"]
    last_retry_execution_code: str | None = Field(default=None, max_length=64)
    result_summary: str | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    retry_instruction: str | None = None

    @model_validator(mode="after")
    def reject_credentials_in_durable_fields(self) -> "MaituRetryTaskExecutionResultCreate":
        operator_token = settings.maitu_reconciliation_operator_token
        forbidden_values = (
            (operator_token.get_secret_value(),)
            if operator_token is not None and operator_token.get_secret_value()
            else ()
        )
        if contains_durable_secret(
            {
                "last_retry_execution_code": self.last_retry_execution_code,
                "result_summary": self.result_summary,
                "error_message": self.error_message,
                "screenshot_asset_code": self.screenshot_asset_code,
                "retry_instruction": self.retry_instruction,
            },
            forbidden_values=forbidden_values,
        ):
            raise ValueError(
                "retry execution result durable fields must not contain credentials or the active claim token"
            )
        return self


class MaituRetryBrowserUseOperationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    target_app: str
    operation_key: str
    operation_fingerprint: str
    operation_type: str
    retry_task_code: str
    authoritative_intent: dict[str, Any]
    target_live_room_id: str | None = None
    target_clip_id: str | int | None = None
    target_scene_name: str | None = None
    target_layer_id: str | int | None = None
    expected_before_state: dict[str, Any] | None = None
    desired_after_state: dict[str, Any] | None = None
    slot_code: str | None = None
    slot_name: str | None = None
    scene_name: str | None = None
    layer_name: str | None = None
    asset_code: str | None = None
    asset_title: str | None = None
    selected_asset_type: str | None = None
    selected_asset_status: str | None = None
    accepted_asset_types: list[str] = Field(default_factory=list)
    maitu_material_id: int | None = None
    source_material_type: str | None = None
    binding_verification_source: str | None = None
    binding_verified_at: str | None = None
    binding_scope: str | None = None
    replacement_policy: str | None = None
    failure_type: str | None = None
    status: str
    blocked_reasons: list[str] = Field(default_factory=list)
    instruction: str


class MaituRetryBrowserUseOperationPlanResponse(BaseModel):
    retry_task_code: str
    plan_code: str
    execution_code: str
    executor: str = "browser_use"
    target_app: str = "maitu"
    maitu_project_code: str | None = None
    scene_name: str | None = None
    operations: list[MaituRetryBrowserUseOperationRead] = Field(default_factory=list)


class MaituRetryWorkerNextResponse(BaseModel):
    reclaimed_count: int
    reclaimed_retry_task_codes: list[str] = Field(default_factory=list)
    retry_task: MaituRetryClaimedQueueItemRead
    operation_plan: MaituRetryBrowserUseOperationPlanResponse
