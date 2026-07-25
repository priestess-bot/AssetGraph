from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class BroadcastScheduleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    release_code: str = Field(min_length=1, max_length=80)
    target_account_id: str = Field(min_length=1, max_length=128)
    target_room_id: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    owner: str = Field(min_length=1, max_length=128)
    promotion_dependencies: list[str] = Field(default_factory=list, max_length=50)
    inventory_dependencies: list[str] = Field(default_factory=list, max_length=50)
    conflict_strategy: str = Field(default="manual_reschedule", min_length=1, max_length=64)
    stop_conditions: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_window(self) -> "BroadcastScheduleCreate":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Schedule window must include a timezone offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("Schedule end must be after its start")
        return self


class BroadcastScheduleRead(BroadcastScheduleCreate):
    schedule_code: str
    revision_number: int
    status: str
    release_fingerprint_sha256: str | None = None
    validation_result: dict[str, object] = Field(default_factory=dict)
    fingerprint_sha256: str
    created_at: datetime

