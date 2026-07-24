from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FunctionalVideoPlanCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    target_duration_seconds: int = Field(default=55, ge=30, le=120)


class FunctionalVideoTimelineClipUpdate(BaseModel):
    clip_code: str = Field(min_length=1, max_length=80)
    duration_ms: int = Field(ge=250, le=120_000)
    transition: str = Field(default="cut", pattern="^(cut|fade|fade_out)$")


class FunctionalVideoTimelineUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    video_clips: list[FunctionalVideoTimelineClipUpdate] = Field(min_length=1, max_length=100)

    @field_validator("video_clips")
    @classmethod
    def unique_clip_codes(cls, value: list[FunctionalVideoTimelineClipUpdate]) -> list[FunctionalVideoTimelineClipUpdate]:
        codes = [clip.clip_code for clip in value]
        if len(codes) != len(set(codes)):
            raise ValueError("video clip codes must be unique")
        return value


class FunctionalVideoTimelineRestore(BaseModel):
    expected_revision: int = Field(ge=1)


class FunctionalVideoTimelineRevisionRead(BaseModel):
    revision_number: int
    production_timeline: dict[str, Any]
    actor_id: str
    created_at: datetime


class FunctionalVideoPlanRead(BaseModel):
    plan_code: str
    project_code: str
    variant_code: str
    video_job_code: str
    title: str
    production_timeline: dict[str, Any]
    timeline_revision: int
    render_profile: dict[str, Any]
    job_status: str
    current_stage: str | None = None
    progress_percent: int
    error_message: str | None = None
    final_asset_id: str | None = None
    quality_report: dict[str, Any] = Field(default_factory=dict)
    workflow_stages: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
