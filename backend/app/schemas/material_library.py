from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class AssetClassificationBatchUpdate(AssetClassificationUpdate):
    asset_codes: list[str] = Field(min_length=1, max_length=100)

    @field_validator("asset_codes")
    @classmethod
    def normalize_asset_codes(cls, values: list[str]) -> list[str]:
        codes = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not codes:
            raise ValueError("asset_codes must contain at least one nonblank code")
        return codes


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


class AssetConstraintProfileRevisionRead(AssetConstraintProfileRead):
    """An immutable constraint-profile revision projection."""

    created_by: str | None = None
    change_reason: str | None = None
    source_plan_code: str | None = None
    source_profile_revision: int | None = None
    source_room_override: dict[str, Any] | None = None


class AssetConstraintProfilePromoteRoomOverride(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_nonblank_values(self) -> "AssetConstraintProfilePromoteRoomOverride":
        if not self.plan_code.strip() or not self.actor.strip() or not self.reason.strip():
            raise ValueError("plan_code, actor and reason must not be blank")
        return self


class MaterialPackEntryMode(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    ALTERNATIVE = "alternative"


class MaterialPackEntryKind(StrEnum):
    ASSET = "asset"
    GROUP = "group"
    CATEGORY_PACK = "category_pack"


class MaterialPackKind(StrEnum):
    TOTAL = "total"
    CLASSIFICATION = "classification"


class MaterialPackScopeKind(StrEnum):
    WHOLE_ROOM = "whole_room"
    SCENE_TYPES = "scene_types"
    SCENE_CODES = "scene_codes"


class MaterialPackScope(BaseModel):
    kind: MaterialPackScopeKind = MaterialPackScopeKind.WHOLE_ROOM
    scene_types: list[str] = Field(default_factory=list)
    scene_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self) -> "MaterialPackScope":
        self.scene_types = list(dict.fromkeys(item.strip() for item in self.scene_types if item.strip()))
        self.scene_codes = list(dict.fromkeys(item.strip() for item in self.scene_codes if item.strip()))
        if self.kind == MaterialPackScopeKind.SCENE_TYPES and not self.scene_types:
            raise ValueError("scene_types scope requires at least one scene type")
        if self.kind == MaterialPackScopeKind.SCENE_CODES and not self.scene_codes:
            raise ValueError("scene_codes scope requires at least one scene code")
        if self.kind == MaterialPackScopeKind.WHOLE_ROOM and (self.scene_types or self.scene_codes):
            raise ValueError("whole_room scope cannot declare scene types or scene codes")
        return self


class MaterialPackEntry(BaseModel):
    selection_kind: MaterialPackEntryKind
    selection_code: str = Field(min_length=1, max_length=64)
    material_role: MaterialRole | None = None
    mode: MaterialPackEntryMode = MaterialPackEntryMode.OPTIONAL
    min_occurrences: int = Field(default=0, ge=0)
    max_occurrences: int | None = Field(default=None, ge=1)
    applicable_scope: MaterialPackScope = Field(default_factory=MaterialPackScope)
    pack_constraints: list[dict[str, Any]] = Field(default_factory=list)
    alternative_set_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_occurrences(self) -> "MaterialPackEntry":
        if self.max_occurrences is not None and self.max_occurrences < self.min_occurrences:
            raise ValueError("max_occurrences must be greater than or equal to min_occurrences")
        if self.mode in {MaterialPackEntryMode.REQUIRED, MaterialPackEntryMode.ALTERNATIVE} and self.min_occurrences < 1:
            raise ValueError("required and alternative entries need min_occurrences of at least one")
        if self.mode == MaterialPackEntryMode.ALTERNATIVE and not self.alternative_set_key:
            raise ValueError("alternative entries require alternative_set_key")
        if self.mode != MaterialPackEntryMode.ALTERNATIVE and self.alternative_set_key:
            raise ValueError("alternative_set_key is only valid for alternative entries")
        return self


class MaterialPackCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    pack_kind: MaterialPackKind = MaterialPackKind.CLASSIFICATION
    role: MaterialRole | None = None
    description: str | None = None
    entries: list[MaterialPackEntry] = Field(default_factory=list)
    exclusive_roles: list[MaterialRole] = Field(default_factory=list)
    pack_constraints: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pack_shape(self) -> "MaterialPackCreate":
        self.exclusive_roles = list(dict.fromkeys(self.exclusive_roles))
        if self.pack_kind == MaterialPackKind.CLASSIFICATION and self.role is None:
            raise ValueError("classification packs require one material role")
        if self.pack_kind == MaterialPackKind.CLASSIFICATION and any(
            entry.material_role is not None and entry.material_role != self.role for entry in self.entries
        ):
            raise ValueError("classification pack entries must use the pack material role")
        if self.pack_kind == MaterialPackKind.TOTAL and any(entry.material_role is None for entry in self.entries):
            raise ValueError("total pack entries require material_role")
        return self


class MaterialPackRevisionCreate(BaseModel):
    expected_revision: int = Field(ge=1)
    entries: list[MaterialPackEntry] = Field(min_length=1)
    exclusive_roles: list[MaterialRole] | None = None
    pack_constraints: list[dict[str, Any]] | None = None


class MaterialPackRead(BaseModel):
    pack_code: str
    title: str
    pack_kind: MaterialPackKind = MaterialPackKind.TOTAL
    role: str | None = None
    description: str | None = None
    revision_number: int
    status: str
    revision_status: str = "draft"
    published_revision_number: int | None = None
    fingerprint_sha256: str
    entries: list[MaterialPackEntry]
    exclusive_roles: list[str] = Field(default_factory=list)
    pack_constraints: list[dict[str, Any]] = Field(default_factory=list)
    resolved_asset_codes: list[str] = Field(default_factory=list)
    resolved_entries: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MaterialPackRevisionRead(BaseModel):
    revision_number: int
    entries: list[MaterialPackEntry]
    fingerprint_sha256: str
    status: str = "draft"
    exclusive_roles: list[str] = Field(default_factory=list)
    pack_constraints: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class MaterialPackResolveRequest(BaseModel):
    pack_codes: list[str] = Field(min_length=1, max_length=20)

    @field_validator("pack_codes")
    @classmethod
    def normalize_pack_codes(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("pack_codes must be unique and non-empty")
        return normalized


class MaterialPackResolutionRead(BaseModel):
    schema_version: str
    pack_refs: list[dict[str, Any]]
    resolved_asset_codes: list[str]
    entry_requirements: list[dict[str, Any]]
    material_rules: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    fingerprint_sha256: str


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
