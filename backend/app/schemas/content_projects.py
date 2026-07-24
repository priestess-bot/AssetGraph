from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class FactCardReference(BaseModel):
    fact_card_code: str = Field(min_length=1, max_length=64)
    version_number: int | None = Field(default=None, ge=1)


class ContentProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    generation_goal: str = Field(min_length=1, max_length=4000)
    theme: str | None = Field(default=None, max_length=1000)
    story: str | None = Field(default=None, max_length=4000)
    detailed_design: str | None = Field(default=None, max_length=8000)
    audience: str | None = Field(default=None, max_length=500)
    platform: str | None = Field(default=None, max_length=64)
    persona: str | None = Field(default=None, max_length=500)
    tone: str | None = Field(default=None, max_length=200)
    target_duration_seconds: int | None = Field(default=None, ge=30, le=86_400)
    product_order: list[str] = Field(default_factory=list, max_length=100)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    interaction_requirements: list[str] = Field(default_factory=list)
    conversion_requirements: list[str] = Field(default_factory=list)
    staging_requirements: list[str] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    audio_requirements: list[str] = Field(default_factory=list)
    fact_card_codes: list[str] = Field(default_factory=list)
    fact_card_refs: list[FactCardReference] = Field(default_factory=list)
    primary_template_code: str | None = Field(default=None, max_length=80)
    secondary_template_codes: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("secondary_template_codes")
    @classmethod
    def unique_secondary_templates(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("secondary templates must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_template_and_fact_selection(self) -> "ContentProjectCreate":
        if self.primary_template_code and self.primary_template_code in self.secondary_template_codes:
            raise ValueError("primary template cannot also be a secondary template")
        fact_codes = [ref.fact_card_code for ref in self.fact_card_refs]
        if len(fact_codes) != len(set(fact_codes)):
            raise ValueError("fact card references must be unique")
        return self


class ContentProjectUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    generation_goal: str | None = Field(default=None, min_length=1, max_length=4000)
    theme: str | None = Field(default=None, max_length=1000)
    story: str | None = Field(default=None, max_length=4000)
    detailed_design: str | None = Field(default=None, max_length=8000)
    audience: str | None = Field(default=None, max_length=500)
    platform: str | None = Field(default=None, max_length=64)
    persona: str | None = Field(default=None, max_length=500)
    tone: str | None = Field(default=None, max_length=200)
    target_duration_seconds: int | None = Field(default=None, ge=30, le=86_400)
    product_order: list[str] | None = Field(default=None, max_length=100)
    must_include: list[str] | None = None
    must_avoid: list[str] | None = None
    interaction_requirements: list[str] | None = None
    conversion_requirements: list[str] | None = None
    staging_requirements: list[str] | None = None
    visual_requirements: list[str] | None = None
    audio_requirements: list[str] | None = None
    fact_card_codes: list[str] | None = None
    fact_card_refs: list[FactCardReference] | None = None
    primary_template_code: str | None = Field(default=None, max_length=80)
    secondary_template_codes: list[str] | None = Field(default=None, max_length=3)

    @model_validator(mode="after")
    def validate_template_and_fact_selection(self) -> "ContentProjectUpdate":
        if self.primary_template_code and self.secondary_template_codes and self.primary_template_code in self.secondary_template_codes:
            raise ValueError("primary template cannot also be a secondary template")
        if self.fact_card_refs is not None:
            fact_codes = [ref.fact_card_code for ref in self.fact_card_refs]
            if len(fact_codes) != len(set(fact_codes)):
                raise ValueError("fact card references must be unique")
        return self


class ContentProjectConfirm(BaseModel):
    expected_revision: int = Field(ge=1)


class DesignBriefParse(BaseModel):
    expected_revision: int = Field(ge=1)
    raw_input: str = Field(min_length=1, max_length=8000)


class DesignBriefConfirm(BaseModel):
    expected_revision: int = Field(ge=1)


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
    fact_cards: list[dict[str, Any]] = Field(default_factory=list)
    design_brief: dict[str, Any] | None = None
    generated: bool
    generation_mode: str | None = None
    story_brief: dict[str, Any] | None = None
    script: dict[str, Any] | None = None
    program: dict[str, Any] | None = None
    shot_list: dict[str, Any] | None = None
