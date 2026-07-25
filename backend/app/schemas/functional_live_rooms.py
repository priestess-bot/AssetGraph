from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

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


class FunctionalLiveRoomPlanCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    target_live_room_id: str = Field(min_length=1, max_length=128)
    expected_title: str = Field(min_length=1, max_length=255)
    primary_template_code: str | None = Field(default=None, max_length=80)
    secondary_template_codes: list[str] = Field(default_factory=list)
    asset_codes: list[str] = Field(default_factory=list)
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

    @field_validator("asset_codes", "group_codes", "material_pack_codes", "asset_gap_codes")
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


class FunctionalLiveRoomExecutionConfirm(BaseModel):
    confirmed: bool


class FunctionalLiveRoomPlanClone(BaseModel):
    target_live_room_id: str = Field(min_length=1, max_length=128)
    expected_title: str = Field(min_length=1, max_length=255)


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
    release_code: str | None = None
    release_snapshot_artifact_code: str | None = None
    release_manifest_fingerprint: str | None = None
    release: FunctionalLiveRoomReleaseRead | None = None
    created_at: datetime
    updated_at: datetime
