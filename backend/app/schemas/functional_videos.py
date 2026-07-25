from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class FunctionalVideoPlanCreate(BaseModel):
    project_code: str | None = Field(default=None, min_length=1, max_length=64)
    live_room_plan_code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    target_duration_seconds: int = Field(default=55, ge=30, le=120)
    visual_asset_codes: list[str] = Field(default_factory=list, max_length=6)
    visual_group_codes: list[str] = Field(default_factory=list, max_length=6)
    visual_material_pack_codes: list[str] = Field(default_factory=list, max_length=6)

    @field_validator(
        "visual_asset_codes",
        "visual_group_codes",
        "visual_material_pack_codes",
    )
    @classmethod
    def unique_visual_selection_codes(cls, value: list[str]) -> list[str]:
        codes = [code.strip() for code in value if code.strip()]
        if len(codes) != len(set(codes)):
            raise ValueError("visual selection codes must be unique")
        return codes

    @model_validator(mode="after")
    def exactly_one_content_source(self) -> "FunctionalVideoPlanCreate":
        if bool(self.project_code) == bool(self.live_room_plan_code):
            raise ValueError("supply exactly one of project_code or live_room_plan_code")
        return self


class FunctionalVideoPlanBranch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)


class FunctionalVideoTimelineClipUpdate(BaseModel):
    clip_code: str = Field(min_length=1, max_length=80)
    duration_ms: int = Field(ge=250, le=120_000)
    transition: str = Field(default="cut", pattern="^(cut|fade|fade_out)$")
    source_start_seconds: float | None = Field(default=None, ge=0)
    source_end_seconds: float | None = Field(default=None, gt=0)
    fit: str | None = Field(default=None, pattern="^(cover|contain)$")
    crop_x: float | None = Field(default=None, ge=0, le=1)
    crop_y: float | None = Field(default=None, ge=0, le=1)
    playback_rate: float | None = Field(default=None, ge=0.5, le=2)
    show_product_sticker: bool | None = None

    @model_validator(mode="after")
    def source_range_is_complete_and_ordered(self) -> "FunctionalVideoTimelineClipUpdate":
        if (self.source_start_seconds is None) != (self.source_end_seconds is None):
            raise ValueError("source start and end must be supplied together")
        if (
            self.source_start_seconds is not None
            and self.source_end_seconds is not None
            and self.source_end_seconds <= self.source_start_seconds
        ):
            raise ValueError("source end must be after source start")
        if (self.crop_x is None) != (self.crop_y is None):
            raise ValueError("crop x and y must be supplied together")
        return self


class FunctionalVideoSubtitleClipUpdate(BaseModel):
    clip_code: str = Field(min_length=1, max_length=100)
    subtitle_text: str = Field(min_length=1, max_length=500)
    headline_text: str = Field(default="", max_length=160)
    caption_position: str = Field(default="bottom", pattern="^(bottom|center)$")


class FunctionalVideoAudioClipUpdate(BaseModel):
    clip_code: str = Field(min_length=1, max_length=100)
    gain_db: float = Field(default=0.0, ge=-24, le=12)


class FunctionalVideoTimelineUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    poster_time_ms: int | None = Field(default=None, ge=0)
    video_clips: list[FunctionalVideoTimelineClipUpdate] = Field(min_length=1, max_length=100)
    subtitle_clips: list[FunctionalVideoSubtitleClipUpdate] = Field(default_factory=list, max_length=100)
    audio_clips: list[FunctionalVideoAudioClipUpdate] = Field(default_factory=list, max_length=100)

    @field_validator("video_clips")
    @classmethod
    def unique_clip_codes(cls, value: list[FunctionalVideoTimelineClipUpdate]) -> list[FunctionalVideoTimelineClipUpdate]:
        codes = [clip.clip_code for clip in value]
        if len(codes) != len(set(codes)):
            raise ValueError("video clip codes must be unique")
        return value

    @field_validator("subtitle_clips")
    @classmethod
    def unique_subtitle_clip_codes(
        cls, value: list[FunctionalVideoSubtitleClipUpdate]
    ) -> list[FunctionalVideoSubtitleClipUpdate]:
        codes = [clip.clip_code for clip in value]
        if len(codes) != len(set(codes)):
            raise ValueError("subtitle clip codes must be unique")
        return value

    @field_validator("audio_clips")
    @classmethod
    def unique_audio_clip_codes(
        cls, value: list[FunctionalVideoAudioClipUpdate]
    ) -> list[FunctionalVideoAudioClipUpdate]:
        codes = [clip.clip_code for clip in value]
        if len(codes) != len(set(codes)):
            raise ValueError("audio clip codes must be unique")
        return value


class FunctionalVideoTimelineRestore(BaseModel):
    expected_revision: int = Field(ge=1)


class FunctionalVideoTimelineRevisionRead(BaseModel):
    revision_number: int
    production_timeline: dict[str, Any]
    actor_id: str
    created_at: datetime


class FunctionalVideoReleaseRead(BaseModel):
    release_code: str
    status: str
    manifest_code: str
    manifest_fingerprint: str
    snapshot_artifact_code: str


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
    release_code: str | None = None
    release_snapshot_artifact_code: str | None = None
    release_manifest_fingerprint: str | None = None
    release: FunctionalVideoReleaseRead | None = None
    created_at: datetime
    updated_at: datetime
