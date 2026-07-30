from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsoleSessionRead(BaseModel):
    operator_id: str
    auth_scheme: Literal["bearer_memory"] = "bearer_memory"
    roles: list[str] = Field(default_factory=lambda: ["control_plane_operator"])


class ConsoleSearchResultRead(BaseModel):
    entity_type: str
    entity_code: str
    title: str
    status: str
    revision: int | None = None
    href: str
    updated_at: datetime


class ConsoleTaskRead(BaseModel):
    item_code: str
    item_type: Literal["human_task", "workflow_run"]
    title: str
    status: str
    priority: int
    summary: str
    href: str
    due_at: datetime | None = None
    updated_at: datetime
    run_code: str
    progress_completed: int
    progress_total: int
    owner_principal: str | None = None
    claimed_by: str | None = None


class ConsoleNotificationRead(BaseModel):
    notification_code: str
    state: Literal["error", "warning", "reconcile_required"]
    title: str
    summary: str
    href: str
    evidence: dict[str, Any]
    occurrence_count: int
    occurred_at: datetime
    status: str


class ConsoleOverviewMetricRead(BaseModel):
    key: Literal["projects", "live_rooms", "videos", "sessions"]
    label: str
    value: int
    previous_value: int
    unit: str


class ConsoleOverviewTrendRead(BaseModel):
    date: datetime
    projects: int
    live_rooms: int
    videos: int
    sessions: int


class ConsoleOverviewRankingRead(BaseModel):
    project_code: str
    title: str
    session_count: int
    last_session_at: datetime | None = None


class ConsoleOverviewCoverageRead(BaseModel):
    ready_assets: int
    published_templates: int
    approved_facts: int
    bound_sessions: int
    total_sessions: int


class ConsoleOverviewProjectRead(BaseModel):
    project_code: str
    title: str
    status: str
    has_live_room: bool
    has_video: bool
    session_count: int
    updated_at: datetime


class ConsoleBusinessOverviewRead(BaseModel):
    from_date: datetime
    to_date: datetime
    metrics: list[ConsoleOverviewMetricRead]
    trend: list[ConsoleOverviewTrendRead]
    rankings: list[ConsoleOverviewRankingRead]
    coverage: ConsoleOverviewCoverageRead
    recent_projects: list[ConsoleOverviewProjectRead]


class ConsoleEntityRevisionRead(BaseModel):
    revision: int
    status: str
    schema_version: str
    created_at: datetime
    created_by: str | None = None
    fingerprint: str | None = None
    snapshot: dict[str, Any]


class ConsoleEntityRelationRead(BaseModel):
    relation_type: str
    entity_type: str
    entity_code: str
    revision: int | None = None
    status: str | None = None
    href: str | None = None
    mapping_quality: str


class ConsoleDiffChangeRead(BaseModel):
    path: str
    change: Literal["added", "removed", "changed"]
    before: Any = None
    after: Any = None


class ConsoleRevisionDiffRead(BaseModel):
    from_revision: int
    to_revision: int
    available: bool
    changes: list[ConsoleDiffChangeRead]


class ConsoleEntityDetailRead(BaseModel):
    entity_type: str
    entity_code: str
    title: str
    status: str
    current_revision: int
    canonical_href: str
    source_of_truth: str
    revisions: list[ConsoleEntityRevisionRead]
    diff: ConsoleRevisionDiffRead
    sources: list[ConsoleEntityRelationRead]
    used_by: list[ConsoleEntityRelationRead]


ConsoleDraftEntityType = Literal[
    "content_project",
    "live_room_configuration",
    "asset_constraint_profile",
    "material_pack",
    "live_room_template",
    "metric_definition",
    "effect_estimate",
    "broadcast_schedule",
    "role_strategy",
    "experiment",
]
ConsoleDraftKind = Literal["input", "configuration", "constraints", "cleaning", "timeline", "strategy", "schedule"]


class ConsoleDraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=0)
    base_entity_revision: int = Field(..., ge=0)
    schema_version: str = Field(default="console-draft.v1", pattern=r"^[a-z0-9-]+\.v[1-9][0-9]*$")
    document: dict[str, Any]


class ConsoleDraftRead(BaseModel):
    draft_code: str
    entity_type: ConsoleDraftEntityType
    entity_code: str
    draft_kind: ConsoleDraftKind
    schema_version: str
    draft_revision: int
    base_entity_revision: int
    status: Literal["active", "consumed"]
    document: dict[str, Any]
    content_fingerprint: str
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class ConsoleIdempotentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class ConsoleContentProjectConfirm(ConsoleIdempotentCommand):
    expected_entity_revision: int = Field(..., ge=1)
    expected_draft_revision: int = Field(..., ge=1)


class ConsoleStructuredReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")
    summary: str = Field(..., min_length=3, max_length=4000)


class ConsoleTemplatePublish(ConsoleIdempotentCommand):
    expected_revision: int = Field(..., ge=1)
    structured_reason: ConsoleStructuredReason


class ConsoleReleaseDecision(ConsoleIdempotentCommand):
    expected_manifest_revision: int = Field(..., ge=1)
    decision: Literal["approve", "reject"]
    structured_reason: ConsoleStructuredReason
    approved_scope: dict[str, Any] = Field(default_factory=dict)


class ConsoleAuthorizationIssue(ConsoleIdempotentCommand):
    task_code: str = Field(..., min_length=1, max_length=80)
    expected_task_revision: int = Field(..., ge=1)


class ConsoleCommandRead(BaseModel):
    command: Literal["confirm", "publish", "approve", "reject", "authorize"]
    entity_type: str
    entity_code: str
    entity_revision: int | None = None
    status: str
    impact: str
    receipt_code: str
    replayed: bool
    draft_revision: int | None = None
    approval_code: str | None = None
    authorization_code: str | None = None
    authorization_token: str | None = Field(default=None, description="Ephemeral token returned only on first issuance")
    token_available: bool | None = None
    capability: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    expires_at: datetime | None = None
    layout_fidelity: str | None = None
    buildability: str | None = None
