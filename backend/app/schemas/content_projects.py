from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _valid_branch_applicability(value: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if len(normalized) != len(value):
        raise ValueError("branch applicability values must be unique and non-empty")
    if normalized and not set(normalized).issubset({"live_room", "rendered_video"}):
        raise ValueError("branch applicability contains an unsupported branch")
    return normalized


class FactCardReference(BaseModel):
    fact_card_code: str = Field(min_length=1, max_length=64)
    version_number: int | None = Field(default=None, ge=1)


class TemplateContributionDecisionInput(BaseModel):
    template_code: str = Field(min_length=1, max_length=80)
    accepted_modules: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("accepted_modules")
    @classmethod
    def unique_accepted_modules(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("accepted template modules must be unique and non-empty")
        return normalized


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
    # Secondary templates are narrowed by the context compiler, not by a UI
    # cardinality cap. The project must retain the complete selected set.
    secondary_template_codes: list[str] = Field(default_factory=list)
    template_contribution_decisions: list[TemplateContributionDecisionInput] = Field(default_factory=list, max_length=50)

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
        contribution_codes = [decision.template_code for decision in self.template_contribution_decisions]
        if len(contribution_codes) != len(set(contribution_codes)):
            raise ValueError("template contribution decisions must be unique")
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
    secondary_template_codes: list[str] | None = None
    template_contribution_decisions: list[TemplateContributionDecisionInput] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_template_and_fact_selection(self) -> "ContentProjectUpdate":
        if self.primary_template_code and self.secondary_template_codes and self.primary_template_code in self.secondary_template_codes:
            raise ValueError("primary template cannot also be a secondary template")
        if self.template_contribution_decisions is not None:
            contribution_codes = [decision.template_code for decision in self.template_contribution_decisions]
            if len(contribution_codes) != len(set(contribution_codes)):
                raise ValueError("template contribution decisions must be unique")
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


class DesignBriefUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    overrides: dict[str, Any] = Field(min_length=1, max_length=16)

    @field_validator("overrides")
    @classmethod
    def validate_overrides(cls, value: dict[str, Any]) -> dict[str, Any]:
        text_limits = {
            "objective": 4000, "theme": 1000, "story": 4000, "audience": 500,
            "persona": 500, "tone": 200, "platform": 64,
        }
        list_fields = {"priorities", "must_include", "must_avoid", "staging", "interaction", "conversion", "visual", "audio"}
        allowed = set(text_limits) | list_fields | {"duration_seconds"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown DesignBrief override fields: {', '.join(unknown)}")
        for key, item in value.items():
            if key in text_limits:
                if not isinstance(item, str) or not item.strip() or len(item) > text_limits[key]:
                    raise ValueError(f"invalid DesignBrief text override: {key}")
            elif key in list_fields:
                if not isinstance(item, list) or len(item) > 100 or not all(isinstance(entry, str) and entry.strip() and len(entry) <= 1000 for entry in item):
                    raise ValueError(f"invalid DesignBrief list override: {key}")
            elif key == "duration_seconds" and (isinstance(item, bool) or not isinstance(item, int) or not 30 <= item <= 86_400):
                raise ValueError("invalid DesignBrief duration_seconds override")
        return value


class DesignBriefConfirm(BaseModel):
    expected_revision: int = Field(ge=1)


class ScriptBlockRevisionInput(BaseModel):
    module_type: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=8000)
    estimated_duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    fact_citations: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    template_sources: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    interaction_intent: dict[str, Any] = Field(default_factory=dict)
    cta_intent: dict[str, Any] = Field(default_factory=dict)


class ScriptRevisionCreate(BaseModel):
    expected_revision: int = Field(ge=1)
    blocks: list[ScriptBlockRevisionInput] = Field(min_length=1, max_length=50)


class ProgramSegmentRevisionInput(BaseModel):
    semantic_goal: str = Field(min_length=1, max_length=2000)
    program_phase: str = Field(default="body", min_length=1, max_length=64)
    estimated_duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    entry_condition: str | None = Field(default=None, max_length=2000)
    exit_condition: str | None = Field(default=None, max_length=2000)
    product_refs: list[str] = Field(default_factory=list, max_length=100)
    interaction_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    cta_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    branch_applicability: list[str] = Field(default_factory=list, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)
    script_block_codes: list[str] = Field(min_length=1, max_length=50)

    @field_validator("script_block_codes")
    @classmethod
    def unique_script_block_codes(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(set(normalized)) != len(normalized):
            raise ValueError("script block codes must be unique and non-empty")
        return normalized

    @field_validator("branch_applicability")
    @classmethod
    def valid_branch_applicability(cls, value: list[str]) -> list[str]:
        return _valid_branch_applicability(value)


class ShotRevisionInput(BaseModel):
    program_segment_index: int = Field(ge=0)
    shot_goal: str = Field(min_length=1, max_length=2000)
    estimated_duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    composition_intent: dict[str, Any] = Field(default_factory=dict)
    material_role_requirements: list[str] = Field(default_factory=list, max_length=32)
    audio_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    continuity: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
    branch_applicability: list[str] = Field(default_factory=list, max_length=32)
    must_include: list[str] = Field(default_factory=list, max_length=100)
    must_avoid: list[str] = Field(default_factory=list, max_length=100)
    script_block_codes: list[str] = Field(min_length=1, max_length=50)

    @field_validator("script_block_codes")
    @classmethod
    def unique_script_block_codes(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(set(normalized)) != len(normalized):
            raise ValueError("script block codes must be unique and non-empty")
        return normalized

    @field_validator("branch_applicability")
    @classmethod
    def valid_branch_applicability(cls, value: list[str]) -> list[str]:
        return _valid_branch_applicability(value)


class ProgramShotRevisionCreate(BaseModel):
    expected_revision: int = Field(ge=1)
    segments: list[ProgramSegmentRevisionInput] = Field(min_length=1, max_length=50)
    shots: list[ShotRevisionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def shot_segments_must_exist(self) -> "ProgramShotRevisionCreate":
        if any(shot.program_segment_index >= len(self.segments) for shot in self.shots):
            raise ValueError("shot program segment index is outside submitted segments")
        referenced = {shot.program_segment_index for shot in self.shots}
        missing = [index for index in range(len(self.segments)) if index not in referenced]
        if missing:
            raise ValueError("every submitted ProgramSegment requires at least one Shot")
        return self


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


class ContentChainRevisionRead(BaseModel):
    object_type: str
    object_code: str
    revision_number: int
    status: str
    created_at: datetime
    created_by: str | None = None
    confirmed_at: datetime | None = None
    fingerprint_sha256: str | None = None
    sources: list[str] = Field(default_factory=list)
