from pydantic import BaseModel, Field


class AssetUploadPlaceholderRequest(BaseModel):
    asset_type: str = Field(..., examples=["IMG"])
    original_filename: str = Field(..., examples=["campaign-poster.jpg"])
    title: str | None = None


class AssetUploadPlaceholderResponse(BaseModel):
    asset_id: str | None = None
    asset_code: str
    status: str


class LiveCreateRequest(BaseModel):
    title: str
    platform: str | None = None
    streamer_name: str | None = None


class LiveCreateResponse(BaseModel):
    live_id: str | None = None
    live_code: str
    status: str


class LiveAssetSummary(BaseModel):
    asset_code: str
    relation_type: str
    sort_order: int = 0
    segment_label: str | None = None


class LiveAssetsResponse(BaseModel):
    live_code: str
    assets: list[LiveAssetSummary]
