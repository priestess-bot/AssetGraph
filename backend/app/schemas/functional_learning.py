from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DecisionCreate(BaseModel):
    project_code: str | None = None
    attribution_report_code: str | None = Field(default=None, min_length=1, max_length=64)
    observation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    decision_type: str = Field(default="manual_recommendation", min_length=1, max_length=64)
    decision_payload: dict[str, object] = Field(default_factory=dict)
    source_revision_refs: list[dict[str, object]] = Field(default_factory=list)


class DecisionRead(DecisionCreate):
    decision_code: str
    fingerprint_sha256: str | None = None
    created_at: datetime


class ExperimentRegistration(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=4000)
    treatment_mechanism: str = Field(min_length=1, max_length=4000)
    estimand: str = Field(min_length=1, max_length=4000)
    inclusion_rules: str = Field(min_length=1, max_length=4000)
    observation_window: str = Field(min_length=1, max_length=1000)
    covariates: list[str] = Field(default_factory=list, max_length=50)
    identification_assumptions: str = Field(min_length=1, max_length=4000)
    analysis_plan: str = Field(min_length=1, max_length=4000)


class ExperimentCreate(BaseModel):
    title: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    variants: list[str] = Field(min_length=2, max_length=2)
    registration: ExperimentRegistration


class ExperimentRead(ExperimentCreate):
    experiment_code: str
    created_at: datetime
    registration: dict[str, object] = Field(default_factory=dict)
    assignment_strategy: str = "stable_hash_sha256_v1"
    registration_fingerprint_sha256: str | None = None
    results: dict[str, dict[str, float | int]]


class OutcomeCreate(BaseModel):
    subject_key: str = Field(min_length=1)
    metric_value: float


class ExperimentAssignmentCreate(BaseModel):
    subject_key: str = Field(min_length=1, max_length=255)


class ExperimentAssignmentRead(BaseModel):
    assignment_code: str
    experiment_code: str
    subject_key: str
    variant_key: str
    assignment_strategy: str
    registration_fingerprint_sha256: str | None = None
    assigned_at: datetime


class EffectEstimateCreate(BaseModel):
    attribution_report_code: str = Field(min_length=1, max_length=64)
    subject_type: str = Field(min_length=1, max_length=64)
    subject_code: str = Field(min_length=1, max_length=128)
    context: dict[str, object] = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=4000)
    evidence_level: Literal["descriptive", "associational"] = "descriptive"


class EffectEstimateApprove(BaseModel):
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)


class EffectEstimateRevoke(BaseModel):
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=4000)


class EffectTemplateChoice(BaseModel):
    source_template_code: str = Field(min_length=1, max_length=128)
    action: Literal["preserve", "replace"]
    replacement_template_code: str | None = Field(default=None, min_length=1, max_length=128)
    replacement_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_replacement(self) -> "EffectTemplateChoice":
        if self.action == "replace" and not self.replacement_template_code:
            raise ValueError("replacement_template_code is required for replace")
        return self


class EffectParagraphChoice(BaseModel):
    field_key: Literal["theme", "story", "detailed_design"] | None = None
    source_block_code: str | None = Field(default=None, min_length=1, max_length=128)
    action: Literal["preserve", "replace"]
    replacement_text: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode="after")
    def validate_replacement(self) -> "EffectParagraphChoice":
        if bool(self.field_key) == bool(self.source_block_code):
            raise ValueError("choose exactly one field_key or source_block_code")
        if self.action == "replace" and not self.replacement_text:
            raise ValueError("replacement_text is required for replace")
        return self


class EffectMaterialChoice(BaseModel):
    source_asset_code: str = Field(min_length=1, max_length=128)
    action: Literal["preserve", "replace"]
    replacement_asset_code: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_replacement(self) -> "EffectMaterialChoice":
        if self.action == "replace" and not self.replacement_asset_code:
            raise ValueError("replacement_asset_code is required for replace")
        return self


class EffectReproductionCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    generation_goal: str | None = Field(default=None, min_length=1, max_length=4000)
    change_hypothesis: str = Field(min_length=1, max_length=4000)
    template_choices: list[EffectTemplateChoice] = Field(default_factory=list, max_length=50)
    paragraph_choices: list[EffectParagraphChoice] = Field(default_factory=list, max_length=200)
    material_choices: list[EffectMaterialChoice] = Field(default_factory=list, max_length=200)
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)


class EffectReproductionRead(BaseModel):
    effect_code: str
    decision_code: str
    source_project_code: str
    source_project_revision_number: int
    reproduced_project_code: str
    reproduced_project_revision_number: int
    production_variant_code: str
    production_variant_revision_number: int
    applied_choices: dict[str, object] = Field(default_factory=dict)


class RecommendationEffectEvidenceRead(BaseModel):
    effect_code: str
    revision_number: int
    evidence_level: str
    status: str
    selected_session_count: int
    eligible: bool
    blockers: list[str] = Field(default_factory=list)
    contribution: float = 0


class LearningRecommendationCandidateRead(BaseModel):
    candidate_type: Literal["template", "material"]
    candidate_code: str
    revision_number: int | None = None
    title: str
    constraint_score: float
    content_score: float
    effect_score: float
    total_score: float
    constraint_reasons: list[str] = Field(default_factory=list)
    content_reasons: list[str] = Field(default_factory=list)
    effect_reasons: list[str] = Field(default_factory=list)
    effect_evidence: list[RecommendationEffectEvidenceRead] = Field(default_factory=list)
    constraint_eligible: bool
    effect_signal_used: bool
    recommendation_mode: Literal["advisory_only"] = "advisory_only"


class LearningRecommendationRead(BaseModel):
    project_code: str
    project_revision_number: int
    project_fingerprint_sha256: str
    strategy_version: str
    recommendation_mode: Literal["advisory_only"] = "advisory_only"
    candidates: list[LearningRecommendationCandidateRead] = Field(default_factory=list)
    project_effect_hints: list[RecommendationEffectEvidenceRead] = Field(default_factory=list)


class EffectEstimateRead(BaseModel):
    effect_code: str
    revision_number: int
    attribution_report_code: str
    subject_type: str
    subject_code: str
    metric_key: str
    evidence_level: str
    status: str
    context: dict[str, object]
    effect_payload: dict[str, object]
    eligibility_snapshot: dict[str, object]
    note: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    fingerprint_sha256: str
    created_at: datetime
