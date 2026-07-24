from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FunctionalLiveRoomPlanCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    target_live_room_id: str = Field(min_length=1, max_length=128)
    expected_title: str = Field(min_length=1, max_length=255)
    primary_template_code: str | None = Field(default=None, max_length=80)
    secondary_template_codes: list[str] = Field(default_factory=list)
    asset_codes: list[str] = Field(default_factory=list)
    group_codes: list[str] = Field(default_factory=list)

    @field_validator("secondary_template_codes")
    @classmethod
    def unique_templates(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("secondary template codes must be unique and non-empty")
        return normalized


class FunctionalLiveRoomExecutionConfirm(BaseModel):
    confirmed: bool


class FunctionalLiveRoomReleaseRead(BaseModel):
    release_code: str
    status: str
    manifest_code: str
    manifest_fingerprint: str
    snapshot_artifact_code: str


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
    blueprint: dict[str, Any]
    build_plan: dict[str, Any]
    gate_results: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    status: str
    blocked_reasons: list[str]
    execution_status: str
    execution_evidence: dict[str, Any]
    release_code: str | None = None
    release_snapshot_artifact_code: str | None = None
    release_manifest_fingerprint: str | None = None
    release: FunctionalLiveRoomReleaseRead | None = None
    created_at: datetime
    updated_at: datetime
