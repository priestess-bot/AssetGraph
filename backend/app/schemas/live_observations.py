from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class WatchTargetStatus(StrEnum):
    ENABLED = "enabled"
    PAUSED = "paused"
    BLOCKED = "blocked"
    DELETED = "deleted"


class CaptureSessionStatus(StrEnum):
    STARTING = "starting"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class CaptureChunkStatus(StrEnum):
    WRITING = "writing"
    FINALIZED = "finalized"
    QUARANTINED = "quarantined"
    DELETE_CANDIDATE = "delete_candidate"
    DELETED = "deleted"
    FAILED = "failed"


class WorkStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TemplateRevisionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=True)


class WatchTargetCreate(StrictModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    room_url: HttpUrl
    canonical_room_id: str | None = Field(default=None, min_length=1, max_length=128)
    platform: Literal["douyin"] = "douyin"
    recorder_engine: Literal["streamcap", "external"] = "streamcap"
    preferred_quality: Literal["720p"] = "720p"
    poll_interval_seconds: int = Field(default=180, ge=30, le=86400)
    retention_days: Literal[30] = 30
    metadata: dict[str, Any] = Field(default_factory=dict)


class WatchTargetUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    canonical_room_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: WatchTargetStatus | None = None
    preferred_quality: Literal["720p"] | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    metadata: dict[str, Any] | None = None


class WatchTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_code: str
    platform: str
    room_url: str
    canonical_room_id: str | None = None
    display_name: str
    recorder_engine: str
    preferred_quality: str
    status: WatchTargetStatus
    poll_interval_seconds: int
    retention_days: int
    next_check_at: datetime
    last_observed_at: datetime | None = None
    last_live_at: datetime | None = None
    last_capture_session_code: str | None = None
    consecutive_failures: int
    last_error_code: str | None = None
    last_error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    lease_active: bool = False
    created_at: datetime
    updated_at: datetime


class SchedulerClaimRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_seconds: int = Field(default=120, ge=30, le=900)


class SchedulerClaimRead(WatchTargetRead):
    claim_token: str
    lease_version: int
    lease_expires_at: datetime


class SchedulerHeartbeatRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    lease_seconds: int = Field(default=120, ge=30, le=900)


class SchedulerReleaseRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    outcome: Literal["idle", "captured", "failed", "blocked"]
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=4000)
    next_check_seconds: int = Field(default=180, ge=30, le=86400)


class CaptureSessionCreate(StrictModel):
    target_code: str = Field(..., min_length=1, max_length=64)
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    recorder_engine: Literal["streamcap", "external"] = "streamcap"
    recorder_version: str = Field(..., min_length=1, max_length=64)
    recorder_build_fingerprint: str = Field(..., min_length=7, max_length=128)
    event_adapter: Literal["douyinlive"] = "douyinlive"
    event_adapter_version: Literal["v2.0.24"] = "v2.0.24"
    source_live_session_id: str | None = Field(default=None, max_length=255)
    observed_started_at: datetime
    monotonic_started_ns: int | None = Field(default=None, ge=0)
    capture_boot_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaptureSessionFinish(StrictModel):
    status: Literal["completed", "failed", "abandoned"]
    observed_ended_at: datetime
    monotonic_ended_ns: int | None = Field(default=None, ge=0)
    failure_code: str | None = Field(default=None, max_length=64)
    failure_message: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_failure(self) -> "CaptureSessionFinish":
        if self.status == "completed" and (self.failure_code or self.failure_message):
            raise ValueError("completed capture sessions cannot carry a failure")
        if self.status == "failed" and not self.failure_code:
            raise ValueError("failed capture sessions require failure_code")
        return self


class CaptureChannelCreate(StrictModel):
    channel_key: str = Field(..., min_length=1, max_length=128)
    media_kind: Literal["video", "audio", "data"]
    stream_index: int = Field(..., ge=0)
    codec_name: str | None = Field(default=None, max_length=64)
    time_base: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=32)
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    average_frame_rate: str | None = Field(default=None, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "CaptureChannelCreate":
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be supplied together")
        return self


class CaptureChannelRead(CaptureChannelCreate):
    id: str
    channel_code: str
    session_code: str
    created_at: datetime


class CaptureChunkFinalize(StrictModel):
    part_index: int = Field(..., ge=0)
    relative_path: str = Field(..., min_length=1)
    container_format: Literal["mpegts", "matroska", "mp4"] = "mpegts"
    file_size: int = Field(..., ge=0)
    checksum_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    capture_started_at: datetime
    capture_ended_at: datetime
    source_start_seconds: float | None = Field(default=None, ge=0)
    source_end_seconds: float | None = Field(default=None, gt=0)
    decoded_duration_seconds: float = Field(..., gt=0)
    stream_timing: dict[str, Any] = Field(default_factory=dict)
    media_probe: dict[str, Any] = Field(default_factory=dict)
    discontinuity_kind: Literal["none", "reset", "gap", "overlap", "reconnect", "unknown"] = "none"
    discontinuity_milliseconds: int = 0

    @model_validator(mode="after")
    def validate_ranges(self) -> "CaptureChunkFinalize":
        _validate_relative_path(self.relative_path)
        if self.capture_ended_at < self.capture_started_at:
            raise ValueError("capture_ended_at cannot precede capture_started_at")
        if (
            self.source_start_seconds is not None
            and self.source_end_seconds is not None
            and self.source_end_seconds <= self.source_start_seconds
        ):
            raise ValueError("source_end_seconds must exceed source_start_seconds")
        return self


class CaptureChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_code: str
    session_code: str
    part_index: int
    relative_path: str
    media_url: str | None = None
    container_format: str
    status: CaptureChunkStatus
    file_size: int | None = None
    checksum_sha256: str | None = None
    capture_started_at: datetime | None = None
    capture_ended_at: datetime | None = None
    finalized_at: datetime | None = None
    retention_expires_at: datetime | None = None
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    decoded_duration_seconds: float | None = None
    stream_timing: dict[str, Any] = Field(default_factory=dict)
    media_probe: dict[str, Any] = Field(default_factory=dict)
    discontinuity_kind: str
    discontinuity_milliseconds: int
    timeline_ready: bool
    legal_hold: bool
    pinned_until: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RawEventBatchRegistration(StrictModel):
    batch_index: int = Field(..., ge=0)
    relative_path: str = Field(..., min_length=1)
    schema_version: str = Field(default="douyin-event-jsonl.v1", min_length=1, max_length=32)
    content_encoding: Literal["gzip"] = "gzip"
    file_mode: Literal[384] = 384
    file_size: int = Field(..., ge=0)
    checksum_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    event_count: int = Field(..., ge=0)
    event_types: dict[str, int] = Field(default_factory=dict)
    first_server_at: datetime | None = None
    last_server_at: datetime | None = None
    first_received_at: datetime
    last_received_at: datetime
    finalized_at: datetime

    @model_validator(mode="after")
    def validate_batch(self) -> "RawEventBatchRegistration":
        _validate_relative_path(self.relative_path)
        if self.last_received_at < self.first_received_at:
            raise ValueError("last_received_at cannot precede first_received_at")
        if self.first_server_at and self.last_server_at and self.last_server_at < self.first_server_at:
            raise ValueError("last_server_at cannot precede first_server_at")
        if any(count < 0 for count in self.event_types.values()):
            raise ValueError("event type counts cannot be negative")
        return self


class RawEventBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_code: str
    session_code: str
    batch_index: int
    relative_path: str
    status: str
    schema_version: str
    content_encoding: str
    file_mode: int
    file_size: int
    checksum_sha256: str
    event_count: int
    event_types: dict[str, int] = Field(default_factory=dict)
    first_server_at: datetime | None = None
    last_server_at: datetime | None = None
    first_received_at: datetime
    last_received_at: datetime
    finalized_at: datetime
    retention_expires_at: None = None


class TimelineSpanCreate(StrictModel):
    chunk_code: str = Field(..., min_length=1, max_length=64)
    span_index: int = Field(..., ge=0)
    contract_version: Literal["media-timeline.v1"] = "media-timeline.v1"
    global_start_seconds: float = Field(..., ge=0)
    global_end_seconds: float = Field(..., gt=0)
    chunk_start_seconds: float = Field(default=0, ge=0)
    chunk_end_seconds: float = Field(..., gt=0)
    wall_start_at: datetime | None = None
    wall_end_at: datetime | None = None
    mapping_slope: float = Field(default=1.0, gt=0)
    confidence: float = Field(default=1.0, ge=0, le=1)
    discontinuity_before: Literal["none", "reset", "gap", "overlap", "reconnect", "unknown"] = "none"
    mapping: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> "TimelineSpanCreate":
        if self.global_end_seconds <= self.global_start_seconds:
            raise ValueError("global timeline range is invalid")
        if self.chunk_end_seconds <= self.chunk_start_seconds:
            raise ValueError("chunk timeline range is invalid")
        if self.wall_start_at and self.wall_end_at and self.wall_end_at < self.wall_start_at:
            raise ValueError("wall timeline range is invalid")
        return self


class TimelineSpanRead(TimelineSpanCreate):
    id: str
    session_code: str
    created_at: datetime


class CaptureSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_code: str
    target_code: str
    platform: str
    source_live_session_id: str | None = None
    recorder_engine: str
    recorder_version: str
    recorder_build_fingerprint: str
    event_adapter: str
    event_adapter_version: str
    status: CaptureSessionStatus
    observed_started_at: datetime
    observed_ended_at: datetime | None = None
    timeline_origin_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = 0
    event_count: int = 0
    timeline_duration_seconds: float | None = None
    analysis_status_counts: dict[str, int] = Field(default_factory=dict)
    analysis_blockers: list[dict[str, Any]] = Field(default_factory=list)
    playback_url: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CaptureSessionRead(CaptureSessionSummary):
    channels: list[CaptureChannelRead] = Field(default_factory=list)
    chunks: list[CaptureChunkRead] = Field(default_factory=list)
    raw_event_batches: list[RawEventBatchRead] = Field(default_factory=list)
    timeline: list[TimelineSpanRead] = Field(default_factory=list)


class ClipJobCreate(StrictModel):
    title: str | None = Field(default=None, max_length=255)
    requested_start_seconds: float = Field(..., ge=0)
    requested_end_seconds: float = Field(..., gt=0)
    cut_mode: Literal["exact_reencode", "keyframe_copy"] = "exact_reencode"

    @model_validator(mode="after")
    def validate_range(self) -> "ClipJobCreate":
        if self.requested_end_seconds <= self.requested_start_seconds:
            raise ValueError("requested_end_seconds must exceed requested_start_seconds")
        return self


class ClipJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    clip_job_code: str
    session_code: str
    title: str | None = None
    requested_start_seconds: float
    requested_end_seconds: float
    cut_mode: str
    status: WorkStatus
    source_fingerprint: str | None = None
    actual_start_seconds: float | None = None
    actual_end_seconds: float | None = None
    output_relative_path: str | None = None
    output_file_size: int | None = None
    output_checksum_sha256: str | None = None
    ffmpeg_version: str | None = None
    final_asset_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class AnalysisRunCreate(StrictModel):
    chunk_code: str | None = Field(default=None, max_length=64)
    analysis_type: Literal["asr", "frame_sampling", "ocr", "layout_inference", "template_aggregation"]
    input_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    strategy_revision: str = Field(..., min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_analysis_input(self) -> "AnalysisRunCreate":
        chunk_types = {"asr", "frame_sampling", "ocr", "layout_inference"}
        if self.analysis_type in chunk_types and not self.chunk_code:
            raise ValueError(f"{self.analysis_type} requires chunk_code")
        if self.analysis_type == "template_aggregation":
            observations = self.parameters.get("observations")
            if self.chunk_code is not None:
                raise ValueError("template_aggregation is session-scoped")
            if not isinstance(observations, list) or not observations:
                raise ValueError("template_aggregation requires non-empty upstream observations")
        return self


class AnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_run_code: str
    session_code: str
    chunk_code: str | None = None
    analysis_type: str
    status: WorkStatus
    input_fingerprint: str
    strategy_revision: str
    invocation_evidence_ref: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    output_relative_path: str | None = None
    output_checksum_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    next_attempt_at: datetime
    retry_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class WorkClaimRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class ClaimedClipJob(ClipJobRead):
    claimed_by: str
    lease_token: str
    lease_expires_at: datetime


class ClipJobCompletion(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_token: str = Field(..., min_length=36, max_length=36)
    actual_start_seconds: float = Field(..., ge=0)
    actual_end_seconds: float = Field(..., gt=0)
    output_relative_path: str = Field(..., min_length=1)
    output_file_size: int = Field(..., ge=0)
    output_checksum_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    ffmpeg_version: str = Field(..., min_length=1, max_length=128)
    ffmpeg_arguments: list[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_completion(self) -> "ClipJobCompletion":
        if self.actual_end_seconds <= self.actual_start_seconds:
            raise ValueError("actual_end_seconds must exceed actual_start_seconds")
        _validate_relative_path(self.output_relative_path)
        return self


class ClaimedAnalysisRun(AnalysisRunRead):
    claimed_by: str
    lease_token: str
    lease_expires_at: datetime


class AnalysisRunCompletion(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_token: str = Field(..., min_length=36, max_length=36)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    output_relative_path: str | None = None
    output_checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    invocation_evidence_ref: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_output(self) -> "AnalysisRunCompletion":
        if self.output_relative_path is not None:
            _validate_relative_path(self.output_relative_path)
        if (self.output_relative_path is None) != (self.output_checksum_sha256 is None):
            raise ValueError("analysis output path and checksum must be supplied together")
        forbidden_provider_keys = {
            "provider",
            "model_provider",
            "model_version",
            "requested_model",
            "actual_model",
            "provider_response_id",
            "response_id",
            "usage",
            "latency_ms",
        }

        def contains_provider_metadata(value: Any) -> bool:
            if isinstance(value, dict):
                return bool(forbidden_provider_keys.intersection(value)) or any(
                    contains_provider_metadata(item) for item in value.values()
                )
            if isinstance(value, list):
                return any(contains_provider_metadata(item) for item in value)
            return False

        if contains_provider_metadata(self.output_payload):
            raise ValueError(
                "supplier invocation metadata belongs in provider evidence, not analysis output"
            )
        return self


class ProviderStrategyAuthorizationRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    strategy_revision: str = Field(..., min_length=1, max_length=128)
    analysis_type: Literal["asr", "ocr", "layout_inference", "template_aggregation"]
    input_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class ProviderStrategyAuthorizationRead(StrictModel):
    strategy_revision: str
    processor_call_audit_code: str


class ProviderEvidenceArtifactRead(StrictModel):
    artifact_code: str


class WorkFailure(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_token: str = Field(..., min_length=36, max_length=36)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)
    retryable: bool = False
    retry_delay_seconds: int = Field(default=60, ge=30, le=3600)


class WorkHeartbeatRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_token: str = Field(..., min_length=36, max_length=36)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class AnalysisRetryRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(..., min_length=1, max_length=1000)


class NormalizedBox(StrictModel):
    x: float = Field(..., ge=0, le=1)
    y: float = Field(..., ge=0, le=1)
    width: float = Field(..., gt=0, le=1)
    height: float = Field(..., gt=0, le=1)

    @model_validator(mode="after")
    def validate_canvas_bounds(self) -> "NormalizedBox":
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("normalized box extends outside the canvas")
        return self


class CanvasSpec(StrictModel):
    width: int = Field(..., gt=0, le=16384)
    height: int = Field(..., gt=0, le=16384)
    rotation_degrees: Literal[0, 90, 180, 270] = 0
    pixel_aspect_ratio: str = Field(default="1:1", min_length=3, max_length=32)


class TemplateComponent(StrictModel):
    component_id: str = Field(..., min_length=1, max_length=128)
    scene_key: str = Field(default="default", min_length=1, max_length=128)
    role: str = Field(..., min_length=1, max_length=64)
    start_seconds: float = Field(default=0, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    geometry: NormalizedBox | None = None
    z_index: int | None = None
    observability: Literal["observed", "inferred", "unknown"]
    source_binding_status: Literal["unmatched", "candidate", "verified"] = "unmatched"
    asset_code: str | None = Field(default=None, max_length=64)
    audio_classification: Literal["speech", "bgm", "unknown", "none"] = "unknown"
    muted: bool = True
    confidence: float = Field(..., ge=0, le=1)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_component(self) -> "TemplateComponent":
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("component end_seconds must exceed start_seconds")
        if self.source_binding_status == "verified" and not self.asset_code:
            raise ValueError("verified components require asset_code")
        if self.audio_classification == "unknown" and not self.muted:
            raise ValueError("unknown audio must default to muted")
        return self


class AudioBusPolicy(StrictModel):
    max_active_speech: Literal[1] = 1
    max_active_bgm: Literal[1] = 1
    unknown_audio_default_muted: Literal[True] = True
    allow_overlapping_bgm_crossfade: Literal[False] = False
    speech_ducking_db: float = Field(default=-9.0, ge=-30, le=0)


class RoomTemplateCreate(StrictModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source_target_code: str | None = Field(default=None, max_length=64)


class RoomTemplateRevisionCreate(StrictModel):
    source_session_code: str | None = Field(default=None, max_length=64)
    contract_version: Literal["layout-hypothesis.v1"] = "layout-hypothesis.v1"
    canvas: CanvasSpec
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    components: list[TemplateComponent] = Field(default_factory=list)
    audio_policy: AudioBusPolicy = Field(default_factory=AudioBusPolicy)
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(..., ge=0, le=1)
    created_by: str | None = Field(default=None, max_length=128)


class RoomTemplateRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_code: str
    revision_number: int
    status: TemplateRevisionStatus
    source_session_code: str | None = None
    contract_version: str
    canvas: dict[str, Any]
    scenes: list[dict[str, Any]]
    components: list[dict[str, Any]]
    audio_policy: dict[str, Any]
    provenance: dict[str, Any]
    confidence: float
    review_status: Literal["pending", "accepted", "rejected"]
    review_notes: str | None = None
    content_fingerprint: str
    created_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RoomTemplateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_code: str
    name: str
    description: str | None = None
    source_target_code: str | None = None
    status: TemplateStatus
    published_revision_number: int | None = None
    latest_revision_number: int | None = None
    projection_ready: bool = False
    manual_review_required: bool = True
    created_at: datetime
    updated_at: datetime


class RoomTemplateRead(RoomTemplateSummary):
    revisions: list[RoomTemplateRevisionRead] = Field(default_factory=list)


class RoomTemplatePublicationRequest(StrictModel):
    reviewed_by: str = Field(..., min_length=1, max_length=128)
    review_notes: str = Field(..., min_length=1, max_length=4000)
    published_by: str = Field(..., min_length=1, max_length=128)
    publication_reason: str | None = Field(default=None, max_length=4000)


class RoomTemplateProjectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_code: str
    template_name: str
    revision_number: int
    publication_code: str | None = None
    projection_contract: Literal["maitu-layout-projection.v1"] = "maitu-layout-projection.v1"
    projection_fingerprint: str
    layout_fidelity: Literal["approximate"] = "approximate"
    buildability: Literal["reference_only"] = "reference_only"
    projection_ready: bool
    manual_review_required: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    canvas: dict[str, Any]
    scenes: list[dict[str, Any]]
    components: list[dict[str, Any]]
    audio_policy: dict[str, Any]
    provenance: dict[str, Any]
    published_at: datetime | None = None


class LiveResearchOverview(BaseModel):
    watch_targets_total: int = 0
    watch_targets_enabled: int = 0
    watch_targets_blocked: int = 0
    active_capture_sessions: int = 0
    completed_capture_sessions: int = 0
    finalized_chunks: int = 0
    raw_event_batches: int = 0
    queued_clip_jobs: int = 0
    queued_analysis_runs: int = 0
    running_analysis_runs: int = 0
    failed_analysis_runs: int = 0
    analysis_blocked_sessions: int = 0
    published_templates: int = 0
    draft_templates: int = 0
    expiring_capture_chunks: int = 0
    projection_ready_templates: int = 0


class InteractionBucket(BaseModel):
    bucket_start_at: datetime
    bucket_end_at: datetime
    event_count: int = Field(..., ge=0)
    event_types: dict[str, int] = Field(default_factory=dict)


class InteractionSummary(BaseModel):
    session_code: str
    bucket_seconds: int
    precision: Literal["batch_metadata"] = "batch_metadata"
    total_event_count: int = Field(..., ge=0)
    buckets: list[InteractionBucket] = Field(default_factory=list)


class RetentionCandidate(BaseModel):
    entity_type: Literal["capture_chunk"]
    entity_id: str
    entity_code: str
    relative_path: str
    checksum_sha256: str | None = None
    delete_marked_at: datetime
    claimed_by: str
    claim_token: str
    claim_expires_at: datetime


class RetentionClaimRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_seconds: int = Field(default=300, ge=30, le=3600)
    limit: int = Field(default=100, ge=1, le=1000)


class RetentionCompleteRequest(StrictModel):
    entity_type: Literal["capture_chunk"]
    entity_id: str = Field(..., min_length=36, max_length=36)
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    deletion_attempt_id: str = Field(..., min_length=36, max_length=36)
    deletion_reason: str = Field(default="retention_30_days", min_length=1, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)


def _validate_relative_path(value: str) -> None:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative_path must stay within the configured live-research root")
