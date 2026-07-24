from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FunctionalVideoPlanCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    target_duration_seconds: int = Field(default=55, ge=30, le=120)


class FunctionalVideoPlanRead(BaseModel):
    plan_code: str
    project_code: str
    variant_code: str
    video_job_code: str
    title: str
    production_timeline: dict[str, Any]
    render_profile: dict[str, Any]
    job_status: str
    current_stage: str | None = None
    progress_percent: int
    error_message: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
