from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ContentProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    generation_goal: str = Field(min_length=1, max_length=4000)
    theme: str | None = Field(default=None, max_length=1000)
    story: str | None = Field(default=None, max_length=4000)
    detailed_design: str | None = Field(default=None, max_length=8000)
    audience: str | None = Field(default=None, max_length=500)
    tone: str | None = Field(default=None, max_length=200)
    target_duration_seconds: int | None = Field(default=None, ge=30, le=86_400)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    fact_card_codes: list[str] = Field(default_factory=list)
    primary_template_code: str | None = Field(default=None, max_length=80)
    secondary_template_codes: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("secondary_template_codes")
    @classmethod
    def unique_secondary_templates(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("secondary templates must be unique and non-empty")
        return normalized


class ContentProjectSummary(BaseModel):
    project_code: str
    title: str
    revision_number: int
    status: str
    generation_goal: str
    created_at: datetime
    updated_at: datetime


class ContentProjectDetail(ContentProjectSummary):
    content: dict[str, Any]
    generated: bool
    generation_mode: str | None = None
    story_brief: dict[str, Any] | None = None
    script: dict[str, Any] | None = None
    program: dict[str, Any] | None = None
    shot_list: dict[str, Any] | None = None
