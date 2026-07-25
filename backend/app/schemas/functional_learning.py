from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class DecisionCreate(BaseModel):
    project_code: str | None = None
    attribution_report_code: str | None = Field(default=None, min_length=1, max_length=64)
    observation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)


class DecisionRead(DecisionCreate):
    decision_code: str
    created_at: datetime


class ExperimentCreate(BaseModel):
    title: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    variants: list[str] = Field(min_length=2, max_length=2)


class ExperimentRead(ExperimentCreate):
    experiment_code: str
    created_at: datetime
    results: dict[str, dict[str, float | int]]


class OutcomeCreate(BaseModel):
    subject_key: str = Field(min_length=1)
    metric_value: float


class EffectEstimateCreate(BaseModel):
    attribution_report_code: str = Field(min_length=1, max_length=64)
    subject_type: str = Field(min_length=1, max_length=64)
    subject_code: str = Field(min_length=1, max_length=128)
    context: dict[str, object] = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=4000)


class EffectEstimateApprove(BaseModel):
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)


class EffectEstimateRevoke(BaseModel):
    actor: str = Field(default="functional-operator", min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=4000)


class EffectReproductionCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    generation_goal: str | None = Field(default=None, min_length=1, max_length=4000)


class EffectReproductionRead(BaseModel):
    effect_code: str
    source_project_code: str
    source_project_revision_number: int
    reproduced_project_code: str
    reproduced_project_revision_number: int


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
