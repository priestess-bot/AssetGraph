from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


VideoProductionJobStatus = Literal["queued", "running", "succeeded", "failed"]
VideoProductionStageStatus = Literal["pending", "running", "succeeded", "failed"]
VideoProductionStageName = Literal[
    "brief_generation",
    "script_generation",
    "shot_planning",
    "asset_selection",
    "voice_synthesis",
    "subtitle_generation",
    "rendering",
    "quality_check",
]
VideoProductionArtifactKey = Literal[
    "story_brief",
    "script",
    "shot_list",
    "asset_plan",
    "voice",
    "subtitles",
    "poster",
    "contact_sheet",
    "quality_report",
    "video",
    "render_log",
    "render_manifest",
]

VIDEO_PRODUCTION_STAGES: tuple[str, ...] = (
    "brief_generation",
    "script_generation",
    "shot_planning",
    "asset_selection",
    "voice_synthesis",
    "subtitle_generation",
    "rendering",
    "quality_check",
)
VIDEO_PRODUCTION_ARTIFACT_KEYS: frozenset[str] = frozenset(
    {
        "story_brief",
        "script",
        "shot_list",
        "asset_plan",
        "voice",
        "subtitles",
        "poster",
        "contact_sheet",
        "quality_report",
        "video",
        "render_log",
        "render_manifest",
    }
)


class VideoProductionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: str = Field(..., min_length=1, max_length=255)
    preset_code: Literal["zhangyu_wine_demo_v1"] = "zhangyu_wine_demo_v1"
    target_duration_seconds: int = Field(default=55, ge=30, le=120)


class VideoProductionStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage_name: VideoProductionStageName
    stage_order: int
    status: VideoProductionStageStatus
    attempt: int
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class VideoProductionArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_key: VideoProductionArtifactKey
    stage_name: VideoProductionStageName
    relative_path: str
    mime_type: str | None = None
    file_size: int | None = None
    checksum_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    download_url: str | None = None
    created_at: datetime
    updated_at: datetime


class VideoProductionJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_code: str
    topic: str
    preset_code: str
    target_duration_seconds: int
    status: VideoProductionJobStatus
    current_stage: VideoProductionStageName | None = None
    progress_percent: int
    attempt: int
    final_asset_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class VideoProductionJobRead(VideoProductionJobSummary):
    story_brief: dict[str, Any] = Field(default_factory=dict)
    script: dict[str, Any] = Field(default_factory=dict)
    shot_list: dict[str, Any] = Field(default_factory=dict)
    asset_plan: dict[str, Any] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    stages: list[VideoProductionStageRead] = Field(default_factory=list)
    artifacts: list[VideoProductionArtifactRead] = Field(default_factory=list)


class VideoProductionArtifactRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: VideoProductionArtifactKey
    relative_path: str = Field(..., min_length=1)
    mime_type: str | None = Field(default=None, max_length=128)
    file_size: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        from pathlib import PurePosixPath

        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("relative_path must stay within the video production root")
        if len(path.parts) < 3:
            raise ValueError("relative_path must be scoped to a job attempt")
        attempt_component = path.parts[1]
        attempt_number = attempt_component.removeprefix("attempt-")
        if (
            attempt_component == attempt_number
            or not attempt_number.isdigit()
            or int(attempt_number) < 1
        ):
            raise ValueError("relative_path must be scoped to a numbered job attempt")
        return str(path)
