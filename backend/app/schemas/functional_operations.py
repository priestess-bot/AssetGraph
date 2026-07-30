from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class OperationMetricDefinitionPin(BaseModel):
    """The immutable catalog revision an operator selected for one session metric."""

    metric_key: str = Field(min_length=1, max_length=80)
    metric_code: str = Field(min_length=1, max_length=80)
    revision_number: int = Field(ge=1)


class OperationMetricDefinitionRef(OperationMetricDefinitionPin):
    """A resolved catalog pin, including the minimum displayable historical snapshot."""

    name: str | None = None
    grain: str | None = None
    unit: str | None = None
    currency: str | None = None
    value_type: str | None = None
    aggregation: str | None = None
    event_time_field: str | None = None
    timezone: str | None = None
    business_day_boundary: str | None = None
    fingerprint_sha256: str | None = None


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
    metric_definition_refs: list[OperationMetricDefinitionPin] = Field(default_factory=list)

    @field_validator("metrics")
    @classmethod
    def validate_metric_values(cls, metrics: dict[str, float]) -> dict[str, float]:
        for key, value in metrics.items():
            if not key.strip() or len(key) > 80:
                raise ValueError("metric keys must be non-empty and at most 80 characters")
            if not math.isfinite(value):
                raise ValueError(f"metric {key} must be finite")
        return metrics

    @model_validator(mode="after")
    def validate_metric_definition_refs(self) -> "OperationSessionCreate":
        seen: set[str] = set()
        for reference in self.metric_definition_refs:
            if reference.metric_key in seen:
                raise ValueError(
                    f"metric definition reference for {reference.metric_key} is duplicated"
                )
            if reference.metric_key not in self.metrics:
                raise ValueError(
                    f"metric definition reference for {reference.metric_key} has no metric value"
                )
            seen.add(reference.metric_key)
        return self


class OperationSessionRead(OperationSessionCreate):
    session_code: str
    source_kind: str
    import_version: int
    video_plan_code: str | None = None
    bound_content_kind: str | None = None
    bound_content_code: str | None = None
    bound_content_revision: int | None = None
    binding_status: str = "pending"
    created_at: datetime
    metric_definition_refs: list[OperationMetricDefinitionRef] = Field(default_factory=list)


class OperationImportConfirm(BaseModel):
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)


class OperationImportFinding(BaseModel):
    field: str
    code: str
    message: str


class OperationBindingCandidate(BaseModel):
    content_kind: str
    content_code: str
    content_revision: int | None = None
    title: str | None = None


class OperationImportRowRead(BaseModel):
    row_number: int
    row_fingerprint_sha256: str
    raw_values: dict[str, str]
    normalized_payload: dict[str, Any]
    validation_errors: list[OperationImportFinding] = Field(default_factory=list)
    validation_warnings: list[OperationImportFinding] = Field(default_factory=list)
    duplicate_kind: str | None = None
    duplicate_of_session_code: str | None = None
    binding_status: str
    binding_candidates: list[OperationBindingCandidate] = Field(default_factory=list)
    import_status: str
    imported_session_code: str | None = None
    created_at: datetime


class OperationImportBatchRead(BaseModel):
    batch_code: str
    original_filename: str
    file_kind: str
    source_checksum_sha256: str
    field_mapping: dict[str, str]
    preview_summary: dict[str, Any]
    status: str
    created_by: str
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    rows: list[OperationImportRowRead] = Field(default_factory=list)


class OperationSessionBindingResolve(BaseModel):
    expected_revision: int = Field(ge=0)
    content_kind: str = Field(
        pattern="^(live_room_plan|rendered_video_plan|content_project_revision)$"
    )
    content_code: str = Field(min_length=1, max_length=128)
    content_revision: int | None = Field(default=None, ge=1)
    evidence_note: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_exact_revision(self) -> "OperationSessionBindingResolve":
        if self.content_kind == "content_project_revision" and self.content_revision is None:
            raise ValueError("content_project_revision requires content_revision")
        return self


class OperationSessionBindingRead(BaseModel):
    binding_code: str
    session_code: str
    revision_number: int
    status: str
    resolution_status: str
    content_kind: str | None = None
    content_code: str | None = None
    content_revision: int | None = None
    candidates: list[OperationBindingCandidate] = Field(default_factory=list)
    source_import_batch_code: str | None = None
    evidence_note: str
    actor: str
    created_at: datetime


class PendingOperationBindingRead(BaseModel):
    session_code: str
    title: str
    platform: str
    external_session_id: str | None = None
    started_at: datetime
    ended_at: datetime
    binding_code: str
    revision_number: int
    content_kind: str | None = None
    content_code: str | None = None
    content_revision: int | None = None
    candidates: list[OperationBindingCandidate] = Field(default_factory=list)
    evidence_note: str
    created_at: datetime


class SessionMetricSnapshotCreate(BaseModel):
    """A reproducible event-derived metric for one operation session.

    JSON Pointer selectors intentionally keep the first local implementation
    declarative. Arbitrary catalog expressions are not evaluated in the
    request path.
    """

    metric_key: str = Field(min_length=1, max_length=80)
    metric_code: str = Field(min_length=1, max_length=80)
    revision_number: int = Field(ge=1)
    event_time_clock: str = Field(default="session_utc", min_length=1, max_length=128)
    value_json_pointer: str | None = Field(default=None, max_length=512)
    numerator_json_pointer: str | None = Field(default=None, max_length=512)
    denominator_json_pointer: str | None = Field(default=None, max_length=512)

    @field_validator(
        "value_json_pointer", "numerator_json_pointer", "denominator_json_pointer"
    )
    @classmethod
    def validate_json_pointer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("/"):
            raise ValueError("JSON Pointer selectors must start with '/'")
        return value

    @field_validator("event_time_clock")
    @classmethod
    def validate_event_time_clock(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event time clock must be non-empty")
        return normalized


class SessionMetricSnapshotRead(BaseModel):
    snapshot_code: str
    session_code: str
    metric_key: str
    metric_code: str
    metric_revision: int
    aggregation: str
    status: str
    value: float | None = None
    source_event_count: int
    event_time_clock: str = "session_utc"
    value_json_pointer: str | None = None
    numerator_json_pointer: str | None = None
    denominator_json_pointer: str | None = None
    source_batches: list[dict[str, Any]] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    fingerprint_sha256: str
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
    content_kind: str = "live_room_plan"
    content_code: str | None = None
    content_revision: int | None = None
    scope_type: str = "maitu_scene"
    scope_code: str | None = None
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


class TimeMappingCreate(BaseModel):
    expected_revision: int = Field(ge=0)
    source_clock: str = Field(min_length=1, max_length=128)
    source_kind: str = Field(
        pattern="^(manual_calibration|recording_anchor|platform_anchor)$"
    )
    source_offset_ms: int
    drift_ppm: float = Field(default=0, ge=-100_000, le=100_000)
    coverage_start_ms: int = Field(ge=0)
    coverage_end_ms: int = Field(ge=1)
    evidence_note: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_coverage(self) -> "TimeMappingCreate":
        if self.coverage_end_ms <= self.coverage_start_ms:
            raise ValueError("time mapping coverage_end_ms must be after coverage_start_ms")
        return self


class TimeMappingRead(BaseModel):
    mapping_code: str
    session_code: str
    revision_number: int
    status: str
    source_clock: str
    source_kind: str
    source_offset_ms: int
    drift_ppm: float
    coverage_start_ms: int
    coverage_end_ms: int
    evidence_note: str
    actor: str
    created_at: datetime


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
    source_start_ms: int | None = None
    source_end_ms: int | None = None
    alignment_status: str = "unmapped"


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
    time_mapping: TimeMappingRead | None = None
    alignment_coverage_ratio: float = 0


class AttributionReportCreate(BaseModel):
    metric_key: str = Field(min_length=1, max_length=80)
    session_codes: list[str] = Field(min_length=1)


class AttributionReportPublish(BaseModel):
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)


class AttributionReportRead(BaseModel):
    report_code: str
    metric_key: str
    evidence_level: str
    session_codes: list[str]
    results: dict[str, Any]
    metric_definition_ref: OperationMetricDefinitionRef | None = None
    status: str = "legacy"
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    quality_snapshot: dict[str, Any] = Field(default_factory=dict)
    fingerprint_sha256: str | None = None
    supersedes_report_code: str | None = None
    published_by: str | None = None
    published_at: datetime | None = None
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
