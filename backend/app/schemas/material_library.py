from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DIGITAL_HUMAN = "digital_human"
    TEXT = "text"
    TEMPLATE_PREVIEW = "template_preview"
    DOCUMENT = "document"


class MaterialRole(StrEnum):
    BACKGROUND = "background"
    PRODUCT_DISPLAY = "product_display"
    DIGITAL_HUMAN = "digital_human"
    BRAND_TITLE = "brand_title"
    PROMOTION_TEXT = "promotion_text"
    DECORATION_FOREGROUND = "decoration_foreground"
    SUPPORTING_VIDEO = "supporting_video"
    VOICE = "voice"
    BACKGROUND_MUSIC = "background_music"
    SOUND_EFFECT = "sound_effect"


class ExecutionCapability(StrEnum):
    MAITU_BOUND = "maitu_bound"
    LOCAL_ONLY = "local_only"
    REFERENCE_ONLY = "reference_only"
    UNAVAILABLE = "unavailable"
    UNCLASSIFIED = "unclassified"


class ConstraintKind(StrEnum):
    ALLOWED_REGION = "allowed_region"
    FORBIDDEN_REGION = "forbidden_region"
    PROVIDE_NAMED_REGION = "provide_named_region"
    REQUIRE_NAMED_REGION = "require_named_region"
    PRESERVE_ASPECT_RATIO = "preserve_aspect_ratio"
    SIZE_RANGE = "size_range"
    SCALE_RANGE = "scale_range"
    CROP_POLICY = "crop_policy"
    ROTATION_POLICY = "rotation_policy"
    PIN_LAYER_TOP = "pin_layer_top"
    PIN_LAYER_BOTTOM = "pin_layer_bottom"
    ABOVE_ROLE = "above_role"
    BELOW_ROLE = "below_role"
    AVOID_OVERLAP = "avoid_overlap"
    ALIGN_ANCHOR = "align_anchor"
    DISTANCE_RANGE = "distance_range"
    LOOP_POLICY = "loop_policy"
    MUTE_POLICY = "mute_policy"
    VOLUME_RANGE = "volume_range"
    TABLE_SURFACE = "table_surface"


class ConstraintRule(BaseModel):
    kind: ConstraintKind
    hard: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class AssetClassificationUpdate(BaseModel):
    media_kind: MediaKind | None = None
    material_roles: list[MaterialRole] = Field(default_factory=list)
    execution_capability: ExecutionCapability = ExecutionCapability.UNCLASSIFIED


class AssetGroupCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    asset_codes: list[str] = Field(default_factory=list)


class AssetGroupMembersReplace(BaseModel):
    asset_codes: list[str] = Field(default_factory=list)


class AssetGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_code: str
    title: str
    description: str | None = None
    asset_codes: list[str] = Field(default_factory=list)
    asset_count: int = 0
    created_at: datetime
    updated_at: datetime


class AssetConstraintProfileWrite(BaseModel):
    constraints: list[ConstraintRule] = Field(default_factory=list)


class AssetConstraintProfileRead(BaseModel):
    profile_code: str
    asset_code: str
    revision_number: int
    constraints: list[ConstraintRule]
    fingerprint_sha256: str
    created_at: datetime


class MaterialPackEntryMode(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    ALTERNATIVE = "alternative"


class MaterialPackEntryKind(StrEnum):
    ASSET = "asset"
    GROUP = "group"


class MaterialPackEntry(BaseModel):
    selection_kind: MaterialPackEntryKind
    selection_code: str = Field(min_length=1, max_length=64)
    mode: MaterialPackEntryMode = MaterialPackEntryMode.OPTIONAL
    min_occurrences: int = Field(default=0, ge=0)
    max_occurrences: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_occurrences(self) -> "MaterialPackEntry":
        if self.max_occurrences is not None and self.max_occurrences < self.min_occurrences:
            raise ValueError("max_occurrences must be greater than or equal to min_occurrences")
        return self


class MaterialPackCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    role: MaterialRole
    description: str | None = None
    entries: list[MaterialPackEntry] = Field(default_factory=list)


class MaterialPackRead(BaseModel):
    pack_code: str
    title: str
    role: str
    description: str | None = None
    revision_number: int
    status: str
    fingerprint_sha256: str
    entries: list[MaterialPackEntry]
    resolved_asset_codes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AssetGapCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    role: MaterialRole
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    gap_type: str = Field(default="material_missing", pattern="^(material_missing|role_coverage|constraint_conflict|rights_pending|quality_improvement)$")
    specification: dict[str, Any] = Field(default_factory=dict)
    source_context: dict[str, Any] = Field(default_factory=dict)
    impact_summary: str | None = Field(default=None, max_length=2000)
    alternative_asset_codes: list[str] = Field(default_factory=list)


class AssetGapUpdate(BaseModel):
    status: str = Field(pattern="^(open|candidate_found|resolved|waived|obsolete)$")
    resolution_asset_code: str | None = Field(default=None, max_length=64)
    actor: str = Field(default="library_user", min_length=1, max_length=128)
    waiver_reason: str | None = Field(default=None, max_length=2000)
    resolution_evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_resolution_details(self) -> "AssetGapUpdate":
        if self.status in {"candidate_found", "resolved"} and not self.resolution_asset_code:
            raise ValueError("resolution_asset_code is required for candidate_found and resolved")
        if self.status == "waived" and not self.waiver_reason:
            raise ValueError("waiver_reason is required for waived")
        return self


class AssetGapRead(BaseModel):
    gap_code: str
    title: str
    role: str
    severity: str
    status: str
    gap_type: str
    specification: dict[str, Any]
    source_context: dict[str, Any]
    impact_summary: str | None = None
    alternative_asset_codes: list[str] = Field(default_factory=list)
    resolution_asset_code: str | None = None
    resolution_snapshot: dict[str, Any] = Field(default_factory=dict)
    resolution_evidence: dict[str, Any] = Field(default_factory=dict)
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    waived_reason: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MaterialSelectionPreviewRequest(BaseModel):
    role: MaterialRole
    carrier_kind: str = Field(default="live_room", pattern="^(live_room|rendered_video)$")
