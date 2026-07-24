from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class OperationSessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=64)
    external_session_id: str | None = Field(default=None, min_length=1, max_length=128)
    account_id: str | None = Field(default=None, min_length=1, max_length=128)
    target_resource_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_timezone: str = Field(default="UTC", min_length=1, max_length=64)
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    content_project_code: str | None = Field(default=None, max_length=64)
    live_room_plan_code: str | None = Field(default=None, max_length=64)
    started_at: datetime
    ended_at: datetime
    metrics: dict[str, float] = Field(default_factory=dict)


class OperationSessionRead(OperationSessionCreate):
    session_code: str
    source_kind: str
    import_version: int
    created_at: datetime


class ContentExposureCreate(BaseModel):
    session_code: str = Field(min_length=1, max_length=64)
    plan_code: str = Field(min_length=1, max_length=64)
    scene_code: str = Field(min_length=1, max_length=64)
    started_at: datetime
    ended_at: datetime
    source_kind: str = Field(
        pattern="^(manual_observation|served_log|recording_match)$"
    )
    evidence_note: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ContentExposureRead(ContentExposureCreate):
    exposure_code: str
    variant_code: str
    release_code: str | None = None
    status: str
    supersedes_exposure_code: str | None = None
    superseded_by_exposure_code: str | None = None
    correction_reason: str | None = None
    created_at: datetime


class ContentExposureCorrection(BaseModel):
    source_exposure_code: str = Field(min_length=1, max_length=64)
    correction_kind: str = Field(pattern="^(supersede|retract)$")
    reason: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)
    replacement: ContentExposureCreate | None = None

    @model_validator(mode="after")
    def validate_replacement(self) -> "ContentExposureCorrection":
        if self.correction_kind == "supersede" and self.replacement is None:
            raise ValueError("a supersede correction requires replacement exposure evidence")
        if self.correction_kind == "retract" and self.replacement is not None:
            raise ValueError("a retract correction cannot include replacement exposure evidence")
        return self


class ContentTimelineSpanRead(BaseModel):
    exposure_code: str
    plan_code: str
    variant_code: str
    release_code: str | None = None
    scene_code: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    source_kind: str
    confidence: float
    scene: dict[str, Any]
    content: dict[str, Any]
    layers: list[dict[str, Any]]


class ContentTimelineRead(BaseModel):
    session_code: str
    started_at: datetime
    ended_at: datetime
    total_seconds: float
    observed_seconds: float
    coverage_ratio: float
    unobserved_seconds: float
    status: str
    missing_plan_codes: list[str]
    spans: list[ContentTimelineSpanRead]


class AttributionReportCreate(BaseModel):
    metric_key: str = Field(min_length=1, max_length=80)
    session_codes: list[str] = Field(min_length=1)


class AttributionReportRead(BaseModel):
    report_code: str
    metric_key: str
    evidence_level: str
    session_codes: list[str]
    results: dict[str, Any]
    created_at: datetime


class SchedulePlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    target_live_room_id: str = Field(min_length=1, max_length=128)
    starts_at: datetime
    duration_minutes: int = Field(ge=1, le=1440)


class SchedulePlanRead(SchedulePlanCreate):
    schedule_code: str
    status: str
    conflict_codes: list[str]
    created_at: datetime
