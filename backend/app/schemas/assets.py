from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.material_library import (
    ClassificationReviewStatus,
    ExecutionCapability,
    MaterialRole,
    MediaKind,
    RightsStatus,
)


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

    # Functional material-library classification.  Old asset_type and
    # maitu_category remain compatibility/source fields and are not inferred.
    media_kind: MediaKind | None = None
    material_roles: list[MaterialRole] = Field(default_factory=list)
    execution_capability: ExecutionCapability = ExecutionCapability.UNCLASSIFIED
    rights_status: RightsStatus = RightsStatus.PENDING
    rights_note: str | None = Field(default=None, max_length=1_000)
    classification_review_status: ClassificationReviewStatus = ClassificationReviewStatus.REVIEW_REQUIRED
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_evidence: dict = Field(default_factory=dict)
    classification_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)

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
    tags: list[str] = Field(default_factory=list)
    local_relative_path: str | None = None
    duplicate_group: str | None = Field(default=None, max_length=64)
    duplicate_rank: int | None = Field(default=None, ge=1)
    duplicate_count: int | None = Field(default=None, ge=1)
    duplicate_primary_local_file_code: str | None = Field(default=None, max_length=64)
    duplicate_primary_asset_code: str | None = Field(default=None, max_length=64)
    maitu_project_code: str | None = Field(default=None, max_length=64)
    maitu_material_id: int | None = Field(default=None, ge=1)
    source_material_type: str | None = Field(default=None, max_length=64)
    source_material_url: str | None = None
    source_cover_url: str | None = None
    speaker_id: int | None = Field(default=None, ge=1)
    digital_human_image_id: int | None = Field(default=None, ge=1)
    maitu_source_material_id: int | None = Field(default=None, ge=1)
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

class AssetFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_id: str
    asset_code: str
    file_role: str
    bucket_name: str
    object_key: str
    mime_type: str | None = None
    file_size: int | None = None
    checksum_sha256: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    source_relative_path: str | None = None
    local_file_code: str | None = None
    storage_status: str = "stored"


class AssetMaituMaterialBindingUpdate(BaseModel):
    maitu_material_id: int | None = Field(default=None, ge=1)
    source_material_type: str | None = Field(default=None, max_length=64)
    source_material_url: str | None = Field(default=None, max_length=2048)
    source_cover_url: str | None = Field(default=None, max_length=2048)
    speaker_id: int | None = Field(default=None, ge=1)
    digital_human_image_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_complete_replacement(self) -> "AssetMaituMaterialBindingUpdate":
        expected_fields = {
            "maitu_material_id",
            "source_material_type",
            "source_material_url",
            "source_cover_url",
            "speaker_id",
            "digital_human_image_id",
        }
        if self.model_fields_set != expected_fields:
            raise ValueError("Maitu material binding must replace every identity field")
        if self.source_material_type == "digital_human":
            if (
                self.maitu_material_id is not None
                or self.source_material_url is not None
                or self.speaker_id is None
                or self.digital_human_image_id is None
            ):
                raise ValueError("digital-human binding requires speaker/image ids and no regular material identity")
            return self
        if (
            self.source_material_type not in {"image", "video", "decorative_video"}
            or self.maitu_material_id is None
            or not str(self.source_material_url or "").startswith("https://")
            or self.speaker_id is not None
            or self.digital_human_image_id is not None
        ):
            raise ValueError("regular binding requires complete HTTPS material identity and no digital-human ids")
        return self


class AssetRead(AssetCreate):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    asset_code: str
    # Source-side compatibility rows can contain historical Maitu categories.
    # Keep writes canonical without making one legacy row break the whole list.
    maitu_category: str | None = None
    maitu_binding_verification_source: str | None = None
    maitu_binding_verified_at: datetime | None = None
    maitu_binding_scope: str | None = None
    maitu_binding_evidence: dict = Field(default_factory=dict)
    rights_updated_at: datetime | None = None
    rights_updated_by: str | None = None
