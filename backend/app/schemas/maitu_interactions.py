from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SyncMode = Literal["full", "incremental", "session"]
SyncStatus = Literal["queued", "running", "waiting_login", "succeeded", "partial", "failed"]
InteractionForm = Literal[
    "question",
    "request",
    "greeting",
    "feedback",
    "purchase_signal",
    "noise",
    "other",
]
BusinessIntent = Literal[
    "product_attributes",
    "product_lookup",
    "recommendation",
    "price_promotion_gift",
    "inventory_shipping",
    "order_purchase",
    "after_sales_invoice",
    "live_room_operation",
    "social_feedback",
    "off_topic_noise",
    "other",
]
QualityGrade = Literal["good", "fair", "poor"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SyncRunCreate(StrictModel):
    sync_mode: SyncMode = "incremental"
    target_external_session_id: int | None = Field(default=None, ge=1)
    requested_by: str = Field(default="console-operator", min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_target(self) -> "SyncRunCreate":
        if (self.sync_mode == "session") != (self.target_external_session_id is not None):
            raise ValueError("target_external_session_id is required only for session sync")
        return self


class WorkerClaim(StrictModel):
    lease_seconds: int = Field(default=600, ge=30, le=3600)


class WorkerHeartbeat(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    lease_seconds: int = Field(default=600, ge=30, le=3600)


class PlatformInput(StrictModel):
    external_platform_id: int = Field(..., ge=1)
    platform_code: str = Field(..., min_length=1, max_length=64)
    platform_name: str = Field(..., min_length=1, max_length=128)


class LiveSessionInput(StrictModel):
    external_session_id: int = Field(..., ge=1)
    external_live_room_id: int = Field(..., ge=1)
    external_platform_id: int = Field(..., ge=1)
    platform_live_id: str | None = Field(default=None, max_length=255)
    title: str = Field(..., min_length=1, max_length=512)
    live_room_type: str | None = Field(default=None, max_length=64)
    source_status: int = 2
    started_at: datetime
    ended_at: datetime
    duration_seconds: int = Field(default=0, ge=0)
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)
    source_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_window(self) -> "LiveSessionInput":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class SyncCatalogWrite(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    external_account_id: int = Field(..., ge=1)
    account_name: str | None = Field(default=None, max_length=255)
    platforms: list[PlatformInput] = Field(..., min_length=1, max_length=64)
    sessions: list[LiveSessionInput] = Field(default_factory=list, max_length=100000)


class InteractionInput(StrictModel):
    external_interaction_id: str = Field(..., min_length=1, max_length=128)
    live_room_id: int = Field(..., ge=1)
    platform: int | None = None
    platform_live_id: str | None = Field(default=None, max_length=255)
    request_id: str | None = Field(default=None, max_length=255)
    interaction_type: int = 0
    content: str = ""
    publisher_name: str | None = Field(default=None, max_length=512)
    publisher_role: str | None = Field(default=None, max_length=64)
    item_id: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None
    digital_reply_type: int | None = None
    digital_reply_status: int | None = None
    digital_reply_content: str | None = None
    digital_replied_at: datetime | None = None
    bullet_reply_type: int | None = None
    bullet_reply_status: int | None = None
    bullet_reply_content: str | None = None
    bullet_replied_at: datetime | None = None
    reply_decision_code: int | None = None
    bullet_reply_decision_code: int | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)


class InteractionBatchWrite(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    external_session_id: int = Field(..., ge=1)
    source_total: int = Field(..., ge=0)
    final_page: bool = False
    items: list[InteractionInput] = Field(default_factory=list, max_length=100)


class SyncRunComplete(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    summary: dict[str, Any] = Field(default_factory=dict)
    partial: bool = False


class SyncRunFail(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)
    retry_kind: Literal["login", "network", "account", "permanent"] = "network"


class AnalysisComplete(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    output_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    invocation_evidence_ref: str = Field(..., min_length=1, max_length=512)
    interaction_form: InteractionForm
    business_intent: BusinessIntent
    relevance_grade: QualityGrade
    completeness_grade: QualityGrade
    resolution_grade: QualityGrade
    overall_grade: QualityGrade
    confidence: float = Field(..., ge=0, le=1)
    reason: str = Field(..., min_length=1, max_length=1000)


class AnalysisFail(StrictModel):
    lease_token: str = Field(..., min_length=36, max_length=36)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_message: str = Field(..., min_length=1, max_length=4000)


class InteractionSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_code: str
    external_account_id: int | None = None
    account_name: str | None = None
    status: str
    timezone: str
    daily_sync_time: str
    rescan_days: int
    last_full_sync_at: datetime | None = None
    last_incremental_sync_at: datetime | None = None
    next_sync_at: datetime | None = None
    retry_after: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    analysis_configured: bool = False


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_code: str
    sync_mode: SyncMode
    target_external_session_id: int | None = None
    status: SyncStatus
    attempt: int
    requested_by: str | None = None
    scheduled_for: datetime | None = None
    retry_after: datetime | None = None
    claimed_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    source: InteractionSourceRead | None = None


class SyncRunClaimRead(SyncRunRead):
    lease_token: str = Field(..., min_length=36, max_length=36)


class PlatformSummary(BaseModel):
    external_platform_id: int
    platform_code: str
    platform_name: str
    is_available: bool
    session_count: int = 0
    interaction_count: int = 0
    arrival_count: int = 0
    effective_count: int = 0
    last_session_at: datetime | None = None


class LiveSessionRead(BaseModel):
    id: str
    external_session_id: int
    external_live_room_id: int
    external_platform_id: int
    platform_code: str
    platform_name: str
    platform_live_id: str | None = None
    title: str
    live_room_type: str | None = None
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    source_interaction_count: int | None = None
    stored_interaction_count: int
    arrival_count: int = 0
    effective_count: int = 0
    answered_count: int = 0
    unanswered_count: int = 0
    is_sync_complete: bool
    last_interaction_sync_at: datetime | None = None


class LiveSessionPage(BaseModel):
    items: list[LiveSessionRead]
    total: int
    limit: int
    offset: int


class InteractionAnalysisRead(BaseModel):
    analyzer_version: str
    interaction_form: InteractionForm
    business_intent: BusinessIntent
    relevance_grade: QualityGrade
    completeness_grade: QualityGrade
    resolution_grade: QualityGrade
    overall_grade: QualityGrade
    confidence: float
    reason: str
    created_at: datetime


class InteractionRead(BaseModel):
    id: str
    external_interaction_id: str
    external_session_id: int
    session_title: str
    external_platform_id: int
    platform_name: str
    interaction_type: int
    content: str
    normalized_content: str
    is_arrival: bool
    publisher_name: str | None = None
    publisher_role: str | None = None
    item_id: str | None = None
    published_at: datetime | None = None
    digital_reply_content: str | None = None
    digital_replied_at: datetime | None = None
    bullet_reply_content: str | None = None
    bullet_replied_at: datetime | None = None
    is_answered: bool
    analysis_status: str
    analysis: InteractionAnalysisRead | None = None


class InteractionPage(BaseModel):
    items: list[InteractionRead]
    total: int
    limit: int
    offset: int


class AnalysisSummaryRead(BaseModel):
    analyzer_version: str
    analysis_configured: bool
    total: int
    analyzed: int
    pending: int
    answered: int
    unanswered: int
    forms: dict[str, int] = Field(default_factory=dict)
    intents: dict[str, int] = Field(default_factory=dict)
    grades: dict[str, int] = Field(default_factory=dict)


class SyncCatalogResult(BaseModel):
    source_code: str
    session_count: int
    sessions_to_sync: list[LiveSessionInput]
