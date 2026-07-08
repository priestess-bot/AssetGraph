from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MaituAssetCategory(StrEnum):
    DIGITAL_HUMAN_VIDEO = "digital_human_video"
    BACKGROUND_VIDEO = "background_video"
    BACKGROUND_IMAGE = "background_image"
    PRODUCT_IMAGE = "product_image"
    PRODUCT_VIDEO = "product_video"
    BANNER_IMAGE = "banner_image"
    PRICE_CARD = "price_card"
    FLOATING_STICKER = "floating_sticker"
    SUBTITLE_FILE = "subtitle_file"
    VOICE_AUDIO = "voice_audio"
    BGM_AUDIO = "bgm_audio"
    SOUND_EFFECT = "sound_effect"
    SCRIPT_TEXT = "script_text"
    COMMENT_EXPORT = "comment_export"
    REPLAY_RECORDING = "replay_recording"
    HIGHLIGHT_CLIP = "highlight_clip"
    ANALYSIS_DOC = "analysis_doc"


class MaituReplacementPolicy(StrEnum):
    KEEP_LAYOUT = "keep_layout"
    FIT_COVER = "fit_cover"
    FIT_CONTAIN = "fit_contain"
    CROP_CENTER = "crop_center"
    STRETCH = "stretch"
    MANUAL_ONLY = "manual_only"


class AssetCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    asset_type: str = Field(..., examples=["VID"])
    title: str | None = Field(default=None, max_length=255)
    original_filename: str = Field(..., min_length=1, max_length=512)
    file_ext: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    checksum_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    status: str = "created"
    project_id: str | None = None
    description: str | None = None

    # Source-side identity mapping. AssetGraph keeps a stable global
    # asset_code, while preserving Maitu / local Browser-use-friendly codes
    # such as MT-VID-0001 or DH-MDL-0001-F022 for operators and agents.
    display_code: str | None = Field(default=None, max_length=64)
    local_file_code: str | None = Field(default=None, max_length=64)
    entity_code: str | None = Field(default=None, max_length=64)
    source_system: str | None = Field(default=None, max_length=64)

    # Maitu-specific material taxonomy and replacement metadata.  AssetGraph
    # keeps these separate from asset_type: asset_type says what the file is,
    # maitu_category says what the material is used for inside Maitu.
    source_type: str | None = Field(default=None, max_length=64)
    maitu_category: MaituAssetCategory | None = None
    maitu_type: str | None = Field(default=None, max_length=64)
    maitu_subtype: str | None = Field(default=None, max_length=64)
    usage: str | None = Field(default=None, max_length=128)
    subject: str | None = Field(default=None, max_length=255)
    file_role: str | None = Field(default=None, max_length=128)
    browser_use_hint: str | None = None
    local_relative_path: str | None = None
    duplicate_group: str | None = Field(default=None, max_length=64)
    duplicate_rank: int | None = Field(default=None, ge=1)
    duplicate_count: int | None = Field(default=None, ge=1)
    duplicate_primary_local_file_code: str | None = Field(default=None, max_length=64)
    duplicate_primary_asset_code: str | None = Field(default=None, max_length=64)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    maitu_scene_name: str | None = Field(default=None, max_length=128)
    maitu_scene_index: int | None = Field(default=None, ge=0)
    maitu_layer_name: str | None = Field(default=None, max_length=128)
    maitu_layer_index: int | None = Field(default=None, ge=0)
    maitu_slot_name: str | None = Field(default=None, max_length=128)
    maitu_slot_code: str | None = Field(default=None, max_length=64)
    layer_left: float | None = Field(default=None, ge=0)
    layer_top: float | None = Field(default=None, ge=0)
    layer_width: float | None = Field(default=None, gt=0)
    layer_height: float | None = Field(default=None, gt=0)
    layer_z_index: int | None = None
    replacement_policy: MaituReplacementPolicy | None = MaituReplacementPolicy.KEEP_LAYOUT


class AssetRead(AssetCreate):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    asset_code: str
