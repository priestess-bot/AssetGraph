from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assets import MaituReplacementPolicy


class LiveSessionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    platform: str | None = None
    streamer_name: str | None = None
    status: str = "planned"
    project_id: str | None = None
    digital_human_id: str | None = None
    voice_profile_id: str | None = None
    script_id: str | None = None
    description: str | None = None


class LiveSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    live_code: str
    title: str
    platform: str | None = None
    streamer_name: str | None = None
    status: str
    project_id: str | None = None
    digital_human_id: str | None = None
    voice_profile_id: str | None = None
    script_id: str | None = None
    description: str | None = None


class LiveAssetSummary(BaseModel):
    asset_code: str
    relation_type: str
    sort_order: int = 0
    segment_label: str | None = None
    start_time_seconds: float | None = None
    end_time_seconds: float | None = None
    maitu_scene_name: str | None = None
    maitu_layer_name: str | None = None
    maitu_slot_name: str | None = None
    replacement_policy: str | None = None


class LiveAssetLinkCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    asset_code: str
    relation_type: str = Field(..., min_length=1, max_length=64)
    sort_order: int = 0
    start_time_seconds: float | None = None
    end_time_seconds: float | None = None
    segment_label: str | None = None
    maitu_scene_name: str | None = Field(default=None, max_length=128)
    maitu_layer_name: str | None = Field(default=None, max_length=128)
    maitu_slot_name: str | None = Field(default=None, max_length=128)
    replacement_policy: MaituReplacementPolicy | None = None


class LiveAssetsResponse(BaseModel):
    live_code: str
    assets: list[LiveAssetSummary]
