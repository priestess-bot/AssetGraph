from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assets import MaituAssetCategory, MaituReplacementPolicy


class MaituMaterialSlotCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    slot_name: str = Field(..., min_length=1, max_length=128)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    scene_index: int | None = Field(default=None, ge=0)
    layer_name: str | None = Field(default=None, max_length=128)
    layer_index: int | None = Field(default=None, ge=0)
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


class MaituMaterialSlotUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    slot_name: str | None = Field(default=None, min_length=1, max_length=128)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    scene_index: int | None = Field(default=None, ge=0)
    layer_name: str | None = Field(default=None, max_length=128)
    layer_index: int | None = Field(default=None, ge=0)
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


class MaituMaterialSlotRead(MaituMaterialSlotCreate):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    slot_code: str


class MaituCandidateAssetRead(BaseModel):
    asset_code: str
    asset_type: str
    title: str | None = None
    original_filename: str
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
    match_reasons: list[str] = Field(default_factory=list)


class MaituCandidateAssetsResponse(BaseModel):
    slot_code: str
    required_category: str
    accepted_asset_types: list[str]
    assets: list[MaituCandidateAssetRead]


class MaituReplacementPlanCreate(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=255)
    maitu_project_code: str | None = Field(default=None, max_length=64)
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
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MaituRetryQueueItemRead(MaituRetryTaskRead):
    maitu_project_code: str | None = None
    scene_name: str | None = None
    slot_name: str | None = None
    layer_name: str | None = None
    next_operation_type: str
    browser_use_operations_url: str


class MaituRetryQueueClaimNextCreate(BaseModel):
    claimed_by: str = Field(..., min_length=1, max_length=128)
    lock_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    failure_type: str | None = Field(default=None, max_length=64)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    scene_name: str | None = Field(default=None, max_length=128)
    max_attempts: int = Field(default=3, ge=1)


class MaituRetryTaskReleaseCreate(BaseModel):
    status: str = Field(default="pending", max_length=32)
    result_summary: str | None = None


class MaituRetryQueueReclaimExpiredResponse(BaseModel):
    reclaimed_count: int
    retry_task_codes: list[str] = Field(default_factory=list)


class MaituRetryTaskUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    retry_attempt_count: int | None = Field(default=None, ge=0)
    last_retry_execution_code: str | None = Field(default=None, max_length=64)
    result_summary: str | None = None
    retry_instruction: str | None = None


class MaituRetryTaskExecutionResultCreate(BaseModel):
    retry_execution_status: str = Field(..., max_length=32)
    last_retry_execution_code: str | None = Field(default=None, max_length=64)
    result_summary: str | None = None
    error_message: str | None = None
    screenshot_asset_code: str | None = Field(default=None, max_length=64)
    retry_instruction: str | None = None


class MaituRetryBrowserUseOperationRead(BaseModel):
    operation_type: str
    retry_task_code: str
    slot_code: str | None = None
    slot_name: str | None = None
    scene_name: str | None = None
    layer_name: str | None = None
    asset_code: str | None = None
    asset_title: str | None = None
    replacement_policy: str | None = None
    failure_type: str | None = None
    status: str
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
    retry_task: MaituRetryQueueItemRead
    operation_plan: MaituRetryBrowserUseOperationPlanResponse
