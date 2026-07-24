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
