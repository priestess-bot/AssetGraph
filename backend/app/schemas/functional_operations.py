from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OperationSessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=64)
    content_project_code: str | None = Field(default=None, max_length=64)
    started_at: datetime
    ended_at: datetime
    metrics: dict[str, float] = Field(default_factory=dict)


class OperationSessionRead(OperationSessionCreate):
    session_code: str
    source_kind: str
    import_version: int
    created_at: datetime


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
