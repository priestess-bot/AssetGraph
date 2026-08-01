from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FactCardVersionStatus = Literal["draft", "approved", "rejected", "superseded"]
InventorySyncJobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
InventorySnapshotQuality = Literal["complete", "partial"]
WorkbenchRunStatus = Literal[
    "draft",
    "planning",
    "ready",
    "blocked",
    "replan_required",
    "preflight_passed",
    "execution_queued",
    "executing",
    "completed",
    "failed",
]
PlanRevisionStatus = Literal["ready", "blocked", "failed", "superseded"]
MaterialRequirementStatus = Literal["pending", "selected", "deferred", "waived", "missing"]
MaterialDecisionValue = Literal["selected", "deferred", "waived"]
PreflightStatus = Literal["passed", "blocked"]
DraftExecutionJobStatus = Literal[
    "queued", "running", "succeeded", "failed", "reconcile_required", "cancelled"
]
RoomInspectionJobStatus = Literal["queued", "running", "succeeded", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductFactCardContent(StrictModel):
    product_name: str = Field(..., min_length=1, max_length=255)
    product_code: str | None = Field(default=None, max_length=64)
    brand: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    positioning: str = Field(..., min_length=1, max_length=1000)
    verified_facts: list[str] = Field(..., min_length=1, max_length=100)
    tasting_notes: list[str] = Field(default_factory=list, max_length=100)
    scenarios: list[str] = Field(default_factory=list, max_length=100)
    selection_guidance: str | None = Field(default=None, max_length=4000)
    objection_response: str | None = Field(default=None, max_length=4000)
    asset_keywords: list[str] = Field(default_factory=list, max_length=100)
    verified_promotion_claims: list[str] = Field(default_factory=list, max_length=100)
    unverified_promotion_claims: list[str] = Field(default_factory=list, max_length=100)
    compliance_notes: list[str] = Field(default_factory=list, max_length=100)
    source_references: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    applicable_platforms: list[str] = Field(default_factory=list, max_length=50)

    @field_validator(
        "verified_facts",
        "tasting_notes",
        "scenarios",
        "asset_keywords",
        "verified_promotion_claims",
        "unverified_promotion_claims",
        "compliance_notes",
        "applicable_platforms",
    )
    @classmethod
    def normalize_string_list(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = " ".join(str(item).split()).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        if not result and value:
            raise ValueError("list must contain at least one non-empty value")
        return result

    @model_validator(mode="after")
    def validate_scope(self) -> "ProductFactCardContent":
        if self.valid_from is not None and self.valid_from.tzinfo is None:
            raise ValueError("valid_from must include a timezone")
        if self.valid_until is not None and self.valid_until.tzinfo is None:
            raise ValueError("valid_until must include a timezone")
        if self.valid_from is not None and self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        return self


class ProductFactCardCreate(StrictModel):
    title: str = Field(..., min_length=1, max_length=255)
    product_code: str | None = Field(default=None, max_length=64)
    content: ProductFactCardContent
    change_reason: str | None = Field(default=None, max_length=4000)
    created_by: str | None = Field(default=None, max_length=128)
    approve: bool = False
    approved_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_approval(self) -> "ProductFactCardCreate":
        if self.approve and not self.approved_by:
            raise ValueError("approved_by is required when approve=true")
        return self


class ProductFactCardVersionCreate(StrictModel):
    content: ProductFactCardContent
    change_reason: str = Field(..., min_length=1, max_length=4000)
    created_by: str | None = Field(default=None, max_length=128)
    approve: bool = False
    approved_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_approval(self) -> "ProductFactCardVersionCreate":
        if self.approve and not self.approved_by:
            raise ValueError("approved_by is required when approve=true")
        return self


class ProductFactCardVersionApprove(StrictModel):
    approved_by: str = Field(..., min_length=1, max_length=128)


class ProductFactCardVersionReject(StrictModel):
    rejected_by: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(..., min_length=1, max_length=4000)


class ProductFactCardVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    fact_card_code: str
    version_code: str
    version_number: int
    status: FactCardVersionStatus
    content: dict[str, Any]
    content_sha256: str
    change_reason: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class ProductFactCardUsageRead(BaseModel):
    relation_type: str
    object_type: str
    object_code: str
    revision_number: int | None = None
    status: str
    created_at: datetime


class ProductFactCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    fact_card_code: str
    product_code: str | None = None
    title: str
    status: Literal["active", "archived"]
    current_approved_version: int | None = None
    created_at: datetime
    updated_at: datetime
    versions: list[ProductFactCardVersionRead] = Field(default_factory=list)


class InventorySyncJobCreate(StrictModel):
    source_system: str = Field(default="maitu", min_length=1, max_length=64)
    project_code: str | None = Field(default=None, max_length=64)
    sync_mode: Literal["full", "incremental"] = "full"
    config: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class InventorySyncClaim(StrictModel):
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class InventorySyncHeartbeat(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class InventorySnapshotItemInput(StrictModel):
    item_key: str = Field(..., min_length=1, max_length=255)
    material_id: str | None = Field(default=None, max_length=128)
    asset_code: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=512)
    material_type: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    subtype: str | None = Field(default=None, max_length=64)
    availability_status: Literal["available", "unavailable", "deleted", "unknown"] = "available"
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_material_url: str | None = Field(default=None, max_length=4096)
    source_cover_url: str | None = Field(default=None, max_length=4096)
    speaker_id: int | None = Field(default=None, ge=1)
    digital_human_image_id: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InventorySyncComplete(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    source_revision: str | None = Field(default=None, max_length=255)
    schema_version: str = Field(default="maitu-inventory-snapshot-v1", min_length=1, max_length=64)
    quality_status: InventorySnapshotQuality = "complete"
    captured_at: datetime | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    items: list[InventorySnapshotItemInput] = Field(default_factory=list, max_length=100000)

    @model_validator(mode="after")
    def validate_unique_items(self) -> "InventorySyncComplete":
        keys = [item.item_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("inventory item_key values must be unique")
        return self


class InventorySyncFail(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)


class InventorySyncRetry(StrictModel):
    requested_by: str | None = Field(default=None, max_length=128)


class InventorySnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    snapshot_code: str
    source_system: str
    project_code: str | None = None
    source_revision: str | None = None
    schema_version: str
    quality_status: InventorySnapshotQuality
    fingerprint_sha256: str
    item_count: int
    summary: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime
    created_at: datetime
    items: list[dict[str, Any]] = Field(default_factory=list)


class InventorySyncJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sync_job_code: str
    source_system: str
    project_code: str | None = None
    sync_mode: Literal["full", "incremental"]
    status: InventorySyncJobStatus
    attempt: int
    request_fingerprint: str
    idempotency_key: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    source_revision: str | None = None
    snapshot_code: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    snapshot: InventorySnapshotRead | None = None


class InventorySyncJobClaimedRead(InventorySyncJobRead):
    lease_token: str


class WorkbenchRunCreate(StrictModel):
    title: str = Field(..., min_length=1, max_length=255)
    topic: str = Field(..., min_length=1, max_length=2000)
    fact_card_code: str = Field(..., min_length=1, max_length=64)
    fact_card_version: int | None = Field(default=None, ge=1)
    inventory_snapshot_code: str = Field(..., min_length=1, max_length=64)
    target_live_room_id: str | None = Field(
        default=None,
        max_length=64,
        description="An existing fresh blank Maitu draft room; AssetGraph does not create the room.",
    )
    target_duration_minutes: int = Field(default=1, ge=1, le=480)
    build_mode: Literal["strict", "draft_with_placeholders"] = "strict"
    include_default_host: bool = True
    max_candidates_per_need: int = Field(default=1, ge=1, le=20)
    canvas_width: int = Field(default=1080, ge=1, le=10000)
    canvas_height: int = Field(default=1920, ge=1, le=10000)
    reference_template_code: str | None = Field(default=None, min_length=1, max_length=64)
    reference_template_revision_number: int | None = Field(default=None, ge=1)
    reference_template_projection_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    created_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_reference_template_pin(self) -> "WorkbenchRunCreate":
        pin_fields = (
            self.reference_template_code,
            self.reference_template_revision_number,
            self.reference_template_projection_fingerprint,
        )
        if any(value is not None for value in pin_fields) and not all(
            value is not None for value in pin_fields
        ):
            raise ValueError("reference template code, revision, and fingerprint must be provided together")
        return self


class WorkbenchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_code: str
    title: str
    topic: str
    status: WorkbenchRunStatus
    fact_card_code: str
    fact_card_version_code: str
    fact_card_version_number: int
    inventory_snapshot_code: str
    target_live_room_id: str | None = None
    target_duration_minutes: int
    build_mode: str
    include_default_host: bool
    max_candidates_per_need: int
    canvas_width: int
    canvas_height: int
    active_plan_revision: int
    reference_template_code: str | None = None
    reference_template_revision_number: int | None = None
    reference_template_projection_fingerprint: str | None = None
    reference_template_snapshot: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    fact_card_version: dict[str, Any] = Field(default_factory=dict)
    inventory_snapshot: dict[str, Any] = Field(default_factory=dict)
    active_plan: dict[str, Any] | None = None
    latest_preflight: dict[str, Any] | None = None


class WorkbenchRunTargetUpdate(StrictModel):
    target_live_room_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="An existing fresh blank Maitu draft room. Changing it invalidates the active plan.",
    )


class WorkbenchPlanCreate(StrictModel):
    reason: str | None = Field(default=None, max_length=4000)
    requested_by: str | None = Field(default=None, max_length=128)


class WorkbenchReplanCreate(StrictModel):
    expected_plan_revision: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=4000)
    inventory_snapshot_code: str | None = Field(default=None, max_length=64)
    fact_card_version: int | None = Field(default=None, ge=1)
    requested_by: str | None = Field(default=None, max_length=128)


class WorkbenchPlanRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_revision_code: str
    run_code: str
    revision_number: int
    trigger_type: Literal["initial", "replan"]
    status: PlanRevisionStatus
    fact_card_version_code: str
    inventory_snapshot_code: str
    source_build_plan_code: str | None = None
    input_fingerprint: str
    generation_strategy_revision: str
    generation_invocation_evidence_ref: str | None = None
    generation_prompt_version: str
    generation_input_fingerprint: str
    generation_output_fingerprint: str
    pipeline_source: str
    pipeline_output: dict[str, Any]
    gap_report: dict[str, Any] = Field(default_factory=dict)
    blocked_reasons: list[str] = Field(default_factory=list)
    reason: str | None = None
    created_by: str | None = None
    created_at: datetime
    superseded_at: datetime | None = None


class MaterialDecisionCreate(StrictModel):
    decision: MaterialDecisionValue
    selected_asset_code: str | None = Field(default=None, max_length=64)
    selected_material_key: str | None = Field(default=None, max_length=255)
    reason: str = Field(..., min_length=1, max_length=4000)
    decided_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_selection(self) -> "MaterialDecisionCreate":
        selected = [self.selected_asset_code, self.selected_material_key]
        selected_count = sum(value is not None for value in selected)
        if self.decision == "selected" and selected_count != 1:
            raise ValueError("selected decision requires exactly one selected asset or material")
        if self.decision != "selected" and selected_count:
            raise ValueError("deferred and waived decisions cannot select a material")
        return self


class MaterialDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_code: str
    requirement_code: str
    revision_number: int
    decision: MaterialDecisionValue
    selected_asset_code: str | None = None
    selected_material_key: str | None = None
    reason: str
    decision_source: Literal["manual", "pipeline_auto", "carried_forward"]
    decided_by: str | None = None
    created_at: datetime


class MaterialRequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    requirement_code: str
    requirement_key: str
    run_code: str
    plan_revision_number: int
    scene_index: int
    scene_name: str
    need_index: int
    need_type: str
    required_category: str
    accepted_asset_types: list[str] = Field(default_factory=list)
    description: str
    keywords: list[str] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"]
    is_required: bool
    status: MaterialRequirementStatus
    current_decision_revision: int
    pipeline_selection: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    decisions: list[MaterialDecisionRead] = Field(default_factory=list)


class WorkbenchPreflightCreate(StrictModel):
    expected_plan_revision: int = Field(..., ge=1)
    performed_by: str | None = Field(default=None, max_length=128)


class WorkbenchPreflightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    preflight_code: str
    run_code: str
    plan_revision_number: int
    preflight_number: int
    status: PreflightStatus
    input_fingerprint: str
    checks: list[dict[str, Any]] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    performed_by: str | None = None
    created_at: datetime


class DraftExecutionJobCreate(StrictModel):
    expected_plan_revision: int = Field(..., ge=1)
    queued_by: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class DraftExecutionClaim(StrictModel):
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class DraftExecutionHeartbeat(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    lease_seconds: int = Field(default=300, ge=30, le=3600)
    stage: str | None = Field(default=None, min_length=1, max_length=64)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_progress(self) -> "DraftExecutionHeartbeat":
        if self.progress_current is not None and self.progress_total is None:
            raise ValueError("progress_total is required with progress_current")
        if self.progress_total is not None and self.progress_current is None:
            raise ValueError("progress_current is required with progress_total")
        if (
            self.progress_current is not None
            and self.progress_total is not None
            and self.progress_current > self.progress_total
        ):
            raise ValueError("progress_current cannot exceed progress_total")
        return self


class FunctionalDraftMaterialReceiptRefresh(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    asset_code: str = Field(..., pattern=r"^[A-Za-z0-9_-]+$", max_length=64)
    maitu_material_id: int | None = Field(default=None, ge=1)
    maitu_source_material_id: int = Field(..., ge=1)
    source_material_type: Literal["image", "video", "decorative_video", "digital_human"]
    source_material_url: str | None = Field(default=None, max_length=4096)
    source_cover_url: str | None = Field(default=None, max_length=4096)
    speaker_id: int | None = Field(default=None, ge=1)
    digital_human_image_id: int | None = Field(default=None, ge=1)
    inventory_item_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_complete_identity(self) -> "FunctionalDraftMaterialReceiptRefresh":
        if self.source_material_type == "digital_human":
            if (
                self.maitu_material_id is not None
                or self.source_material_url is not None
                or self.source_cover_url is None
                or self.speaker_id is None
                or self.digital_human_image_id is None
            ):
                raise ValueError("digital-human receipt requires source, cover, speaker and image identity")
        elif (
            self.maitu_material_id != self.maitu_source_material_id
            or self.source_material_url is None
            or self.speaker_id is not None
            or self.digital_human_image_id is not None
        ):
            raise ValueError("regular-material receipt requires matching material/source identity")
        return self


class DraftExecutionComplete(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    result: dict[str, Any] = Field(default_factory=dict)
    ready_for_go_live: Literal[False] = False


class DraftExecutionFail(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)
    reconcile_required: bool = False


class DraftExecutionRetry(StrictModel):
    requested_by: str | None = Field(default=None, max_length=128)


class DraftExecutionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_job_code: str
    source_kind: Literal["workbench_run", "functional_live_room_plan"] = "workbench_run"
    run_code: str | None = None
    plan_revision_number: int | None = None
    preflight_code: str | None = None
    functional_plan_code: str | None = None
    execution_mode: Literal["fresh_draft", "replace_test_draft"] = "fresh_draft"
    authority_mode: Literal["worker_readback", "independent_backend"] = "independent_backend"
    room_inspection_code: str | None = None
    room_snapshot: dict[str, Any] = Field(default_factory=dict)
    room_fingerprint: str | None = None
    status: DraftExecutionJobStatus
    attempt: int
    input_fingerprint: str
    idempotency_key: str | None = None
    payload: dict[str, Any]
    result: dict[str, Any] = Field(default_factory=dict)
    stage: str = "queued"
    progress_current: int = 0
    progress_total: int = 0
    stage_events: list[dict[str, Any]] = Field(default_factory=list)
    ready_for_go_live: Literal[False] = False
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    queued_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DraftExecutionJobClaimedRead(DraftExecutionJobRead):
    lease_token: str


class RoomInspectionCreate(StrictModel):
    target_live_room_id: str = Field(..., min_length=1, max_length=128)
    expected_title: str | None = Field(default=None, min_length=1, max_length=255)
    authority_mode: Literal["worker_readback", "independent_backend"] = "worker_readback"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    requested_by: str | None = Field(default=None, max_length=128)


class RoomInspectionClaim(StrictModel):
    lease_seconds: int = Field(default=120, ge=30, le=600)


class RoomInspectionHeartbeat(RoomInspectionClaim):
    lease_token: str = Field(..., min_length=1, max_length=64)


class RoomInspectionComplete(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    result: dict[str, Any]


class RoomInspectionFail(StrictModel):
    lease_token: str = Field(..., min_length=1, max_length=64)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)


class RoomInspectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inspection_code: str
    target_live_room_id: str
    expected_title: str | None = None
    authority_mode: Literal["worker_readback", "independent_backend"]
    status: RoomInspectionJobStatus
    attempt: int
    input_fingerprint: str
    idempotency_key: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    room_fingerprint: str | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    requested_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RoomInspectionClaimedRead(RoomInspectionRead):
    lease_token: str
