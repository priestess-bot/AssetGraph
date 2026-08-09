from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class GuidedContentProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    target_live_room_id: str = Field(min_length=1, max_length=128)


class GuidedKnowledgeReferenceInput(BaseModel):
    kind: Literal["fact_card", "fact_claim", "content_rule"]
    code: str = Field(min_length=1, max_length=128)
    version_number: int | None = Field(default=None, ge=1)


class GuidedProjectSetupUpdate(BaseModel):
    expected_project_revision: int = Field(ge=1)
    expected_material_pool_revision: int = Field(ge=1)
    theme: str = Field(min_length=1, max_length=4000)
    selected_asset_codes: list[str] = Field(default_factory=list, max_length=500)
    selected_knowledge_refs: list[GuidedKnowledgeReferenceInput] = Field(
        default_factory=list, max_length=200
    )
    selected_knowledge_codes: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("selected_asset_codes")
    @classmethod
    def unique_asset_codes(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(normalized) != len(set(normalized)):
            raise ValueError("selected asset codes must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def unique_knowledge_references(self) -> "GuidedProjectSetupUpdate":
        keys = [(item.kind, item.code.strip(), item.version_number) for item in self.selected_knowledge_refs]
        if len(keys) != len(set(keys)):
            raise ValueError("selected knowledge references must be unique")
        codes = [item.strip() for item in self.selected_knowledge_codes if item.strip()]
        if len(codes) != len(self.selected_knowledge_codes) or len(codes) != len(set(codes)):
            raise ValueError("selected knowledge codes must be unique and non-empty")
        return self


class GuidedThemeOptimizeRequest(BaseModel):
    theme: str = Field(min_length=1, max_length=4000)


class GuidedRecommendationRequest(BaseModel):
    kind: Literal["knowledge", "materials"] = "knowledge"
    theme: str | None = Field(default=None, min_length=1, max_length=4000)
    selected_asset_codes: list[str] = Field(default_factory=list, max_length=500)
    selected_knowledge_codes: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("selected_asset_codes", "selected_knowledge_codes")
    @classmethod
    def unique_codes(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(normalized) != len(set(normalized)):
            raise ValueError("selection codes must be unique and non-empty")
        return normalized


class GuidedMaterialPoolUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    selected_asset_codes: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("selected_asset_codes")
    @classmethod
    def unique_asset_codes(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(normalized) != len(set(normalized)):
            raise ValueError("selected asset codes must be unique and non-empty")
        return normalized


class GuidedOutlineKeyPointInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    citation_source_ids: list[str] = Field(default_factory=list, max_length=20)
    citations: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

    @field_validator("citation_source_ids")
    @classmethod
    def unique_citations(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(value) or len(normalized) != len(set(normalized)):
            raise ValueError("citation source ids must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def citation_codes_to_source_ids(self) -> "GuidedOutlineKeyPointInput":
        if not self.citations:
            return self
        extracted = [
            str(
                item.get("citation_source_id")
                or item.get("citation_code")
                or item.get("source_id")
                or item.get("reference_code")
                or ""
            ).strip()
            for item in self.citations
            if isinstance(item, dict)
        ]
        self.citation_source_ids = list(
            dict.fromkeys([*self.citation_source_ids, *[item for item in extracted if item]])
        )
        return self


class GuidedOutlineSectionInput(BaseModel):
    section_key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    objective: str = Field(min_length=1, max_length=2000)
    key_points: list[GuidedOutlineKeyPointInput | str] = Field(default_factory=list, max_length=30)

    @field_validator("key_points")
    @classmethod
    def valid_key_points(
        cls, value: list[GuidedOutlineKeyPointInput | str]
    ) -> list[GuidedOutlineKeyPointInput | str]:
        normalized = [item.strip() if isinstance(item, str) else item.text.strip() for item in value]
        if any(not item or len(item) > 1000 for item in normalized):
            raise ValueError("outline key points must be non-empty and at most 1000 characters")
        return normalized


class GuidedOutlineRevisionUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    sections: list[GuidedOutlineSectionInput] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_section_keys(self) -> "GuidedOutlineRevisionUpdate":
        keys = [item.section_key for item in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("outline section keys must be unique")
        return self


class GuidedRevisionAction(BaseModel):
    expected_revision: int = Field(ge=1)
    preview_fingerprint: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class GuidedOutlineSectionRegenerate(BaseModel):
    expected_revision: int = Field(ge=1)
    guidance: str = Field(default="", max_length=4000)


class GuidedBranchSelect(BaseModel):
    node_code: str = Field(min_length=1, max_length=80)
    expected_head_revision: int = Field(ge=1)


class GuidedBranchUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    archived: bool | None = None

    @model_validator(mode="after")
    def has_change(self) -> "GuidedBranchUpdate":
        if self.label is None and self.archived is None:
            raise ValueError("branch update requires a label or archived state")
        return self


class GuidedItemVersionSelect(BaseModel):
    version_number: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


class GuidedScriptRestore(BaseModel):
    expected_current_revision: int | None = Field(default=None, ge=1)


class GuidedScriptBlockInput(BaseModel):
    section_key: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=20_000)


class GuidedScriptRevisionUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    blocks: list[GuidedScriptBlockInput] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_section_keys(self) -> "GuidedScriptRevisionUpdate":
        keys = [item.section_key for item in self.blocks]
        if len(keys) != len(set(keys)):
            raise ValueError("script section keys must be unique")
        return self


class GuidedMaterialWaiver(BaseModel):
    expected_script_revision: int = Field(ge=1)


class GuidedStoryboardGenerate(BaseModel):
    template_code: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)
    projection_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")


class GuidedStoryboardLayerInput(BaseModel):
    role: str = Field(min_length=1, max_length=64)
    asset_code: str = Field(min_length=1, max_length=64)
    geometry: dict[str, float]
    z_order: int = Field(ge=-1000, le=1000)


class GuidedStoryboardSceneInput(BaseModel):
    shot_code: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=255)
    script: str = Field(min_length=1, max_length=20_000)
    layers: list[GuidedStoryboardLayerInput] = Field(min_length=1)


class GuidedStoryboardUpdate(BaseModel):
    expected_plan_code: str = Field(min_length=1, max_length=64)
    scenes: list[GuidedStoryboardSceneInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def contiguous_scenes(self) -> "GuidedStoryboardUpdate":
        orders = [scene.sort_order for scene in self.scenes]
        shots = [scene.shot_code for scene in self.scenes]
        if sorted(orders) != list(range(len(orders))) or len(shots) != len(set(shots)):
            raise ValueError("storyboard scenes require unique shots and contiguous ordering")
        return self


class GuidedStoryboardConfirm(BaseModel):
    expected_plan_code: str = Field(min_length=1, max_length=64)
    preview_fingerprint: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class GuidedGenerationJobRead(BaseModel):
    job_code: str
    stage: str
    operation: str = "generate"
    target_section_key: str | None = None
    status: str
    total_items: int
    completed_items: int
    attempts: int
    max_attempts: int
    error_code: str | None = None
    error_message: str | None = None
    result_refs: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class GuidedWorkflowRead(BaseModel):
    workflow_version: str
    project: dict[str, Any]
    material_pool: dict[str, Any]
    setup: dict[str, Any] = Field(default_factory=dict)
    outline: dict[str, Any] | None = None
    script: dict[str, Any] | None = None
    storyboard: dict[str, Any] | None = None
    tree: dict[str, Any] = Field(default_factory=dict)
    active_path: list[str] = Field(default_factory=list)
    jobs: dict[str, GuidedGenerationJobRead] = Field(default_factory=dict)
    recommendations: dict[str, Any] = Field(default_factory=dict)
    revisions: dict[str, Any] = Field(default_factory=dict)
    script_archives: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    gates: dict[str, Any] = Field(default_factory=dict)
    setup_branch: dict[str, Any] | None = None
    confirmation: dict[str, Any] | None = None
    navigation: dict[str, Any] | None = None
