from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VideoSegmentCreate(BaseModel):
    live_id: str
    asset_id: str | None = None
    asset_code: str | None = None
    live_code: str
    title: str | None = None
    start_time_seconds: Decimal
    end_time_seconds: Decimal
    transcript: str | None = None
    product_id: str | None = None
    digital_human_id: str | None = None
    voice_profile_id: str | None = None
    script_block_id: str | None = None
    quality_score: Decimal | None = Field(default=None, ge=0, le=1)
    reuse_score: Decimal | None = Field(default=None, ge=0, le=1)
    status: str = "created"

    @model_validator(mode="after")
    def validate_time_range(self) -> "VideoSegmentCreate":
        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError("end_time_seconds must be greater than start_time_seconds")
        return self


class VideoSegmentRead(VideoSegmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    segment_code: str
