from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AudioClass = Literal["unknown", "silent", "speech", "music", "speech_and_music", "effect", "ambient"]


class MaterialSceneObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    visual: str = Field(min_length=1, max_length=2000)
    roles: list[str] = Field(default_factory=list, max_length=20)
    visible_text: list[str] = Field(default_factory=list, max_length=50)
    evidence_frame_codes: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_range(self) -> "MaterialSceneObservation":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("scene end_seconds must be greater than start_seconds")
        return self


class MaterialSemanticObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["material-profile-observation-v1"] = "material-profile-observation-v1"
    asset_code: str = Field(min_length=1, max_length=64)
    asset_fingerprint: str = Field(min_length=64, max_length=64)
    summary: str = Field(min_length=1, max_length=4000)
    semantic_roles: list[str] = Field(default_factory=list, max_length=30)
    product_identities: list[str] = Field(default_factory=list, max_length=30)
    people: list[str] = Field(default_factory=list, max_length=30)
    visible_text: list[str] = Field(default_factory=list, max_length=100)
    palette: list[str] = Field(default_factory=list, max_length=20)
    style_tags: list[str] = Field(default_factory=list, max_length=30)
    audio_class: AudioClass = "unknown"
    original_audio_recommended: bool = False
    reusable_as_whole: bool = True
    scenes: list[MaterialSceneObservation] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class MaterialProfileConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    automatic_value: object | None = None
    manual_value: object | None = None
    severity: Literal["warning", "critical"]
    reason: str


class MergedMaterialProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["merged-material-profile-v1"] = "merged-material-profile-v1"
    asset_code: str
    asset_fingerprint: str
    status: Literal["provisional", "canonical", "review_required"]
    technical: dict[str, object]
    semantic: MaterialSemanticObservation
    conflicts: list[MaterialProfileConflict] = Field(default_factory=list)
    field_provenance: dict[str, list[str]] = Field(default_factory=dict)
    merge_policy_version: Literal["material-profile-merge-v1"] = "material-profile-merge-v1"


class GeminiManualSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_task_code: str = Field(min_length=1, max_length=64)
    asset_code: str = Field(min_length=1, max_length=64)
    asset_fingerprint: str = Field(min_length=64, max_length=64)
    prompt_schema_version: Literal["gemini-material-analysis-v1"]
    observation: MaterialSemanticObservation


VideoAnalysisStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
GeminiStatus = Literal["not_requested", "queued", "running", "succeeded", "failed"]
ConflictResolution = Literal["provisional", "gemini", "replace_asset"]


class VideoAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_code: str
    run_code: str
    requirement_code: str | None = None
    asset_code: str
    asset_fingerprint: str | None = None
    asset_title: str
    selected: bool
    status: VideoAnalysisStatus
    attempt: int
    provisional_source: Literal["none", "keyframe", "strategy_frames"]
    provisional_summary: str | None = None
    gemini_status: GeminiStatus
    gemini_summary: str | None = None
    conflict_count: int = 0
    analysis_strategy_revision: str
    invocation_evidence_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class VideoAnalysisClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_seconds: int = Field(default=900, ge=30, le=3600)


class VideoAnalysisClaimedRead(VideoAnalysisRead):
    lease_token: str
    source_relative_path: str | None = None
    source_root_kind: Literal["asset_materials", "maitu_mirror"] | None = None


class VideoAnalysisHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: str = Field(min_length=1, max_length=64)
    lease_seconds: int = Field(default=900, ge=30, le=3600)


class VideoAnalysisComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: str = Field(min_length=1, max_length=64)
    technical: dict[str, Any]
    frame_manifest: dict[str, Any]
    observation: MaterialSemanticObservation
    analysis_strategy_revision: str = Field(min_length=1, max_length=128)
    invocation_evidence_ref: str = Field(min_length=1, max_length=80)
    analysis_prompt_revision: str = Field(min_length=1, max_length=64)
    analysis_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_output_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class VideoAnalysisFail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_token: str = Field(min_length=1, max_length=64)
    error_code: str = Field(min_length=1, max_length=64)
    error_message: str = Field(min_length=1, max_length=4000)


class VideoAnalysisRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str | None = Field(default=None, max_length=128)


class GeminiBackfillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_json: dict[str, Any]
    asset_code: str = Field(min_length=1, max_length=64)
    asset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    submitted_by: str | None = Field(default=None, max_length=128)


class AnalysisConflictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conflict_code: str
    analysis_code: str
    field: str
    severity: Literal["warning", "critical"]
    provisional_value: str | None = None
    gemini_value: str | None = None
    resolution: ConflictResolution | None = None
    reason: str
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class AnalysisConflictResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: ConflictResolution
    resolved_by: str = Field(default="maitu_workbench_reviewer", min_length=1, max_length=128)
