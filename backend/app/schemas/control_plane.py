from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


WorkflowRunStatus = Literal[
    "queued",
    "running",
    "waiting_human",
    "cancelling",
    "cancelled",
    "succeeded",
    "failed",
    "reconcile_required",
]
WorkflowStepStatus = Literal[
    "pending",
    "ready",
    "running",
    "waiting_human",
    "succeeded",
    "failed",
    "cancelled",
    "reconcile_required",
]
HumanTaskStatus = Literal["open", "claimed", "decided", "expired", "cancelled", "escalated"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkflowStepCreate(StrictModel):
    step_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    step_type: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    priority: int = Field(default=100, ge=0, le=1000)
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    side_effect_level: Literal[
        "pure_compute",
        "read_external",
        "write_external",
        "irreversible_external",
    ] = "pure_compute"
    max_attempts: int = Field(default=3, ge=1, le=100)
    backoff_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(..., ge=1, le=604800)
    cancellable: bool = True
    compensation_strategy: str | None = Field(default=None, max_length=64)
    reconcile_strategy: str | None = Field(default=None, max_length=64)
    input_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_effect_strategy(self) -> "WorkflowStepCreate":
        if self.side_effect_level in {"write_external", "irreversible_external"} and not self.reconcile_strategy:
            raise ValueError("external write steps require reconcile_strategy")
        if self.step_key in self.depends_on:
            raise ValueError("a step cannot depend on itself")
        return self


class WorkflowRunCreate(StrictModel):
    workflow_type: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    subject_type: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    subject_code: str = Field(..., min_length=1, max_length=128)
    subject_revision: int | None = Field(default=None, ge=1)
    parent_run_code: str | None = Field(default=None, max_length=80)
    priority: int = Field(default=100, ge=0, le=1000)
    budget: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    root_span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    steps: list[WorkflowStepCreate] = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_dag(self) -> "WorkflowRunCreate":
        keys = [step.step_key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("workflow step_key values must be unique")
        known = set(keys)
        for step in self.steps:
            unknown = sorted(set(step.depends_on) - known)
            if unknown:
                raise ValueError(f"step {step.step_key} has unknown dependencies: {unknown}")
        graph = {step.step_key: set(step.depends_on) for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("workflow dependencies must be acyclic")
            if key in visited:
                return
            visiting.add(key)
            for dependency in graph[key]:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in keys:
            visit(key)
        return self


class WorkflowStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_code: str
    step_type: str
    sort_order: int
    status: WorkflowStepStatus
    priority: int
    idempotency_key: str
    side_effect_level: str
    max_attempts: int
    attempt: int
    timeout_seconds: int
    cancellable: bool
    compensation_strategy: str | None = None
    reconcile_strategy: str | None = None
    input_fingerprint: str
    output_fingerprint: str | None = None
    claimed_by: str | None = None
    lease_version: int
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error_code: str | None = None
    error_summary: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    depends_on: list[str] = Field(default_factory=list)


class HumanTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_code: str
    run_code: str
    step_code: str | None = None
    task_type: str
    status: HumanTaskStatus
    revision: int
    priority: int
    owner_principal: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    due_at: datetime | None = None
    escalated_at: datetime | None = None
    subject: dict[str, Any]
    decision: str | None = None
    structured_reason: dict[str, Any] | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_code: str
    workflow_type: str
    subject_type: str
    subject_code: str
    subject_revision: int | None = None
    parent_run_code: str | None = None
    status: WorkflowRunStatus
    priority: int
    progress_completed: int
    progress_total: int
    queue_reason: str | None = None
    budget: dict[str, Any]
    actual_cost: dict[str, Any]
    trace_id: str | None = None
    root_span_id: str | None = None
    requested_by: str | None = None
    cancellation_requested_at: datetime | None = None
    waiting_reason: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepRead] = Field(default_factory=list)
    human_tasks: list[HumanTaskRead] = Field(default_factory=list)


class WorkflowCancelRequest(StrictModel):
    reason: str = Field(..., min_length=1, max_length=1000)


class WorkflowStepClaimRequest(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_seconds: int = Field(default=300, ge=30, le=3600)
    accepted_step_types: list[str] = Field(default_factory=list, max_length=100)


class WorkflowStepClaimedRead(WorkflowStepRead):
    run_code: str
    claim_token: str
    traceparent: str | None = None


class WorkflowStepHeartbeat(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class WorkflowStepComplete(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    output_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    actual_cost: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepFail(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    error_code: str = Field(..., min_length=1, max_length=64)
    error_summary: str = Field(..., min_length=1, max_length=4000)
    side_effect_known_not_applied: bool = False


class WorkflowExternalEffectPrepare(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    claim_token: str = Field(..., min_length=36, max_length=36)
    lease_version: int = Field(..., ge=1)
    target_type: str = Field(..., min_length=1, max_length=64)
    target_id: str = Field(..., min_length=1, max_length=255)
    operation_type: str = Field(..., min_length=1, max_length=64)
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    plan_or_release_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    request_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class WorkflowExternalEffectAuthorize(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    expected_revision: int = Field(..., ge=1)
    authorization_code: str = Field(..., min_length=1, max_length=80)
    authorization_token: SecretStr
    site_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class WorkflowExternalEffectBegin(StrictModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    expected_revision: int = Field(..., ge=1)


class WorkflowExternalEffectCommit(WorkflowExternalEffectBegin):
    outcome: Literal["applied", "not_applied", "unknown"]
    response_summary: dict[str, Any] | None = None
    external_identity: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=64)


class WorkflowExternalEffectReadback(WorkflowExternalEffectBegin):
    external_identity: dict[str, Any]
    readback_evidence: dict[str, Any]


class WorkflowExternalEffectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    effect_code: str
    step_code: str
    attempt: int
    revision: int
    phase: str
    target_type: str
    target_id: str
    operation_type: str
    idempotency_key: str
    plan_or_release_hash: str
    request_fingerprint: str
    authorization_code: str | None = None
    external_identity: dict[str, Any] | None = None
    response_summary: dict[str, Any] | None = None
    readback_evidence: dict[str, Any] | None = None
    reconcile_evidence: dict[str, Any] | None = None
    unknown_outcome: bool
    error_code: str | None = None
    prepared_at: datetime
    authorized_at: datetime | None = None
    commit_started_at: datetime | None = None
    commit_completed_at: datetime | None = None
    readback_completed_at: datetime | None = None
    reconciled_at: datetime | None = None
    updated_at: datetime


class HumanTaskClaim(StrictModel):
    claimed_by: str = Field(..., min_length=1, max_length=128)
    expected_revision: int = Field(..., ge=1)


class HumanTaskDecision(StrictModel):
    decided_by: str = Field(..., min_length=1, max_length=128)
    expected_revision: int = Field(..., ge=1)
    decision: str = Field(..., min_length=1, max_length=64)
    structured_reason: dict[str, Any]
