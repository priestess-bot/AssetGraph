from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class FunctionalLiveRoomConstraintOverride(BaseModel):
    """A plan-local placement adjustment that cannot erase an asset Profile."""

    reason: str = Field(min_length=1, max_length=500)
    geometry: dict[str, float] | None = None
    z_order: int | None = Field(default=None, ge=-999, le=999)

    @model_validator(mode="after")
    def validate_override(self) -> "FunctionalLiveRoomConstraintOverride":
        if self.geometry is None and self.z_order is None:
            raise ValueError("a room constraint override must set geometry or z_order")
        if self.geometry is None:
            return self
        expected = {"x", "y", "width", "height"}
        if set(self.geometry) != expected:
            raise ValueError("room override geometry must contain x, y, width and height")
        x, y, width, height = (float(self.geometry[key]) for key in ("x", "y", "width", "height"))
        if not all(isfinite(value) for value in (x, y, width, height)) or x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("room override geometry must stay within the normalized canvas")
        return self


class FunctionalLayoutReferenceHandoff(BaseModel):
    template_code: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)
    projection_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")


class FunctionalLiveRoomPlanCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    target_live_room_id: str = Field(min_length=1, max_length=128)
    expected_title: str = Field(min_length=1, max_length=255)
    layout_reference_handoff: FunctionalLayoutReferenceHandoff | None = None
    primary_template_code: str | None = Field(default=None, max_length=80)
    secondary_template_codes: list[str] = Field(default_factory=list)
    asset_codes: list[str] = Field(default_factory=list)
    required_loose_asset_codes: list[str] = Field(default_factory=list)
    group_codes: list[str] = Field(default_factory=list)
    material_pack_codes: list[str] = Field(default_factory=list)
    material_role_modes: dict[str, str] = Field(default_factory=dict)
    asset_gap_codes: list[str] = Field(default_factory=list)
    asset_gap_waivers: dict[str, str] = Field(default_factory=dict)
    material_role_overrides: dict[str, str] = Field(default_factory=dict)
    room_constraint_overrides: dict[str, FunctionalLiveRoomConstraintOverride] = Field(default_factory=dict)

    @field_validator("secondary_template_codes")
    @classmethod
    def unique_templates(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("secondary template codes must be unique and non-empty")
        return normalized

    @field_validator("asset_codes", "required_loose_asset_codes", "group_codes", "material_pack_codes", "asset_gap_codes")
    @classmethod
    def unique_selection_codes(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("selection codes must be unique and non-empty")
        return normalized

    @field_validator("material_role_overrides")
    @classmethod
    def normalize_material_role_overrides(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for role, asset_code in value.items():
            normalized_role = str(role).strip()
            normalized_asset_code = str(asset_code).strip()
            if not normalized_role or not normalized_asset_code:
                raise ValueError("material role overrides must use non-empty role and asset codes")
            if len(normalized_role) > 64 or len(normalized_asset_code) > 64:
                raise ValueError("material role override keys and asset codes must be at most 64 characters")
            normalized[normalized_role] = normalized_asset_code
        return normalized

    @field_validator("material_role_modes")
    @classmethod
    def normalize_material_role_modes(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_role, raw_mode in value.items():
            role = str(raw_role).strip()
            mode = str(raw_mode).strip()
            if not role or mode not in {"inherit", "append", "replace"}:
                raise ValueError("material role modes must map a non-empty role to inherit, append or replace")
            normalized[role] = mode
        return normalized

    @field_validator("asset_gap_waivers")
    @classmethod
    def normalize_asset_gap_waivers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_gap_code, raw_reason in value.items():
            gap_code = str(raw_gap_code).strip()
            reason = str(raw_reason).strip()
            if not gap_code or not reason or len(gap_code) > 64 or len(reason) > 2_000:
                raise ValueError("asset gap waivers require a gap code and a non-empty reason")
            normalized[gap_code] = reason
        return normalized

    @field_validator("room_constraint_overrides")
    @classmethod
    def normalize_room_constraint_overrides(
        cls, value: dict[str, FunctionalLiveRoomConstraintOverride]
    ) -> dict[str, FunctionalLiveRoomConstraintOverride]:
        normalized: dict[str, FunctionalLiveRoomConstraintOverride] = {}
        for asset_code, override in value.items():
            code = str(asset_code).strip()
            if not code or len(code) > 64:
                raise ValueError("room constraint override asset codes must be non-empty and at most 64 characters")
            normalized[code] = override
        return normalized


class FunctionalLiveRoomMaterialGapPreviewRequest(BaseModel):
    """The material-selection inputs needed for a non-mutating gap diagnosis."""

    project_code: str = Field(min_length=1, max_length=64)
    asset_codes: list[str] = Field(default_factory=list)
    group_codes: list[str] = Field(default_factory=list)
    material_pack_codes: list[str] = Field(default_factory=list)
    material_role_modes: dict[str, str] = Field(default_factory=dict)

    @field_validator("asset_codes", "group_codes", "material_pack_codes")
    @classmethod
    def unique_selection_codes(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("selection codes must be unique and non-empty")
        return normalized

    @field_validator("material_role_modes")
    @classmethod
    def normalize_material_role_modes(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_role, raw_mode in value.items():
            role = str(raw_role).strip()
            mode = str(raw_mode).strip()
            if not role or mode not in {"inherit", "append", "replace"}:
                raise ValueError("material role modes must map a non-empty role to inherit, append or replace")
            normalized[role] = mode
        return normalized


class FunctionalLiveRoomMaterialGapPreviewItemRead(BaseModel):
    diagnostic_key: str
    role: str
    title: str
    severity: str
    gap_type: str
    required_shot_codes: list[str]
    missing_occurrences: int
    selection_mode: str
    alternative_asset_codes: list[str]
    create_payload: dict[str, Any]


class FunctionalLiveRoomMaterialGapPreviewRead(BaseModel):
    project_code: str
    project_revision_number: int
    shot_list_revision_number: int
    checked_asset_codes: list[str]
    gaps: list[FunctionalLiveRoomMaterialGapPreviewItemRead]


class FunctionalLiveRoomExecutionConfirm(BaseModel):
    confirmed: bool


class MaituCapabilityRead(BaseModel):
    key: str
    title: str
    status: Literal["verified", "manual_only", "unsupported"]
    required_for_draft: bool
    last_verified_at: datetime | None = None
    evidence_level: str
    evidence_refs: list[str]
    customer_message: str


class MaituCapabilityMatrixRead(BaseModel):
    schema_version: Literal["maitu-capability-matrix.v1"]
    adapter_contract: str
    contract_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    source: str
    can_execute_draft: bool
    manual_handoff_available: bool
    unverified_required_capabilities: list[str]
    capabilities: list[MaituCapabilityRead]


class FunctionalLiveRoomExecutionHandoffRead(BaseModel):
    plan_code: str
    build_plan_code: str
    target_live_room_id: str
    expected_title: str
    checkpoint_contract: str
    source_plan_fingerprint: str
    operation_count: int
    operation_types: list[str]
    operations: list[dict[str, Any]] = Field(default_factory=list)


class FunctionalLiveRoomPlanClone(BaseModel):
    target_live_room_id: str = Field(min_length=1, max_length=128)
    expected_title: str = Field(min_length=1, max_length=255)


class FunctionalLiveRoomLayerRevisionInput(BaseModel):
    role: str = Field(min_length=1, max_length=64)
    asset_code: str = Field(min_length=1, max_length=64)
    geometry: dict[str, float]
    z_order: int = Field(ge=-1000, le=1000)

    @field_validator("geometry")
    @classmethod
    def normalized_geometry(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != {"x", "y", "width", "height"}:
            raise ValueError("layer geometry must contain x, y, width and height")
        x, y, width, height = (float(value[key]) for key in ("x", "y", "width", "height"))
        if not all(isfinite(item) for item in (x, y, width, height)) or x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("layer geometry must stay within the normalized canvas")
        return {"x": x, "y": y, "width": width, "height": height}


class FunctionalLiveRoomSceneRevisionInput(BaseModel):
    shot_code: str = Field(min_length=1, max_length=64)
    sort_order: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=255)
    script: str = Field(min_length=1, max_length=20_000)
    layers: list[FunctionalLiveRoomLayerRevisionInput] = Field(min_length=1)

    @field_validator("layers")
    @classmethod
    def unique_layer_roles(
        cls, value: list[FunctionalLiveRoomLayerRevisionInput]
    ) -> list[FunctionalLiveRoomLayerRevisionInput]:
        roles = [item.role for item in value]
        if len(roles) != len(set(roles)):
            raise ValueError("a scene revision can contain each material role once")
        return value


class FunctionalLiveRoomBlueprintRevision(BaseModel):
    scenes: list[FunctionalLiveRoomSceneRevisionInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_scenes_and_order(self) -> "FunctionalLiveRoomBlueprintRevision":
        shots = [scene.shot_code for scene in self.scenes]
        orders = [scene.sort_order for scene in self.scenes]
        if len(shots) != len(set(shots)):
            raise ValueError("a blueprint revision can contain each source shot once")
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("scene sort_order must be a contiguous zero-based sequence")
        return self


class FunctionalLiveRoomReleaseRead(BaseModel):
    release_code: str
    status: str
    manifest_code: str
    manifest_fingerprint: str
    snapshot_artifact_code: str


class FunctionalLiveRoomTraceRead(BaseModel):
    plan_code: str
    content_chain: dict[str, Any]
    operations: list[dict[str, Any]]


class FunctionalLiveRoomPlanRead(BaseModel):
    plan_code: str
    project_code: str
    variant_code: str
    configuration_code: str
    target_live_room_id: str
    expected_title: str
    primary_template_code: str | None = None
    secondary_template_codes: list[str]
    selected_asset_codes: list[str]
    selected_group_codes: list[str]
    selected_material_pack_codes: list[str]
    selected_asset_gap_codes: list[str] = Field(default_factory=list)
    blueprint: dict[str, Any]
    build_plan: dict[str, Any]
    gate_results: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: str
    blocked_reasons: list[str]
    execution_status: str
    execution_evidence: dict[str, Any]
    cloned_from_plan_code: str | None = None
    clone_context: dict[str, Any] = Field(default_factory=dict)
    revised_from_plan_code: str | None = None
    revision_context: dict[str, Any] = Field(default_factory=dict)
    release_code: str | None = None
    release_snapshot_artifact_code: str | None = None
    release_manifest_fingerprint: str | None = None
    release: FunctionalLiveRoomReleaseRead | None = None
    created_at: datetime
    updated_at: datetime
