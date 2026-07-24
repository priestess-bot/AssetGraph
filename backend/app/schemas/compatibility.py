from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LegacyWorkflowStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    projection_step_code: str
    projection_run_code: str
    source_type: str
    source_code: str
    step_type: str
    sort_order: int
    status: str
    attempt: int
    error_code: str | None = None
    error_summary: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    read_only: bool


class LegacyWorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    projection_run_code: str
    source_type: str
    source_code: str
    workflow_type: str
    subject_type: str
    subject_code: str
    subject_revision: int | None = None
    status: str
    priority: int
    progress_completed: int
    progress_total: int
    waiting_reason: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    mapping_quality: str
    read_only: bool
    steps: list[LegacyWorkflowStepRead] = Field(default_factory=list)


class LegacyAssetObservationRead(BaseModel):
    projection_code: str
    asset_code: str
    asset_type: str
    title: str | None = None
    source_system: str | None = None
    maitu_category: str | None = None
    maitu_scene_name: str | None = None
    maitu_scene_index: int | None = None
    maitu_layer_name: str | None = None
    maitu_layer_index: int | None = None
    observed_geometry: dict[str, Any]
    duplicate_group: str | None = None
    duplicate_rank: int | None = None
    duplicate_count: int | None = None
    geometry_semantics: str
    duplicate_group_semantics: str
    is_constraint: bool
    is_user_group: bool
    source_type: str
    source_code: str
    mapping_quality: str
    updated_at: datetime
    read_only: bool


class LegacyContentProjectRead(BaseModel):
    projection_project_code: str
    source_type: str
    source_code: str
    title: str
    generation_goal: str
    target_duration_seconds: int
    source_snapshot: dict[str, Any]
    missing_provenance: list[str]
    mapping_quality: str
    created_at: datetime
    updated_at: datetime
    read_only: bool


class LegacyLiveRoomVariantRead(BaseModel):
    projection_variant_code: str
    source_type: str
    source_code: str
    variant_code: str | None = None
    variant_revision: int | None = None
    configuration_code: str | None = None
    configuration_revision: int | None = None
    carrier_kind: str
    target_live_room_id: str | None = None
    expected_title: str
    legacy_status: str
    mapping_quality: str
    source_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    read_only: bool


class LegacyLayoutHypothesisRead(BaseModel):
    projection_code: str
    template_code: str
    revision_number: int
    status: str
    contract_version: str
    canvas: dict[str, Any]
    scenes: list[dict[str, Any]]
    components: list[dict[str, Any]]
    audio_policy: dict[str, Any]
    provenance: dict[str, Any]
    confidence: float
    review_status: str
    source_session_code: str | None = None
    reference_mode: str
    layout_fidelity: str
    buildability: str
    conversion_allowed: bool
    source_type: str
    source_code: str
    mapping_quality: str
    created_at: datetime
    updated_at: datetime
    read_only: bool


class LegacyDeliveryUnknownRead(BaseModel):
    projection_code: str
    source_type: str
    source_code: str
    possible_carrier_kind: str
    release_code: None = None
    delivery_code: None = None
    possible_target_id: str | None = None
    external_identity: None = None
    readback_evidence: None = None
    delivery_semantics: str
    is_actual_delivery: bool
    is_exposure: bool
    source_snapshot: dict[str, Any]
    observed_at: datetime | None = None
    read_only: bool
