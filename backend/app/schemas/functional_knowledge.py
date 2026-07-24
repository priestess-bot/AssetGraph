from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class FactCreate(BaseModel):
    title: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source_url: str | None = None
    related_codes: list[str] = Field(default_factory=list)


class FactRead(FactCreate):
    fact_code: str
    status: str
    created_at: datetime
