from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from psycopg import Connection

from app.api.auth import require_control_plane_operator, require_control_plane_worker
from app.core.config import settings
from app.core.database import get_db
from app.core.telemetry import trace_context_from_current
from app.domain.contracts import Capability
from app.domain.errors import (
    DomainAuthorizationError,
    DomainConflictError,
    DomainError,
    DomainUnavailableError,
)
from app.repositories.control_plane import ControlPlaneRepository
from app.repositories.policy import PolicyRepository
from app.schemas.control_plane import (
    HumanTaskClaim,
    HumanTaskDecision,
    HumanTaskRead,
    HumanTaskStatus,
    WorkflowCancelRequest,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowExternalEffectAuthorize,
    WorkflowExternalEffectBegin,
    WorkflowExternalEffectCommit,
    WorkflowExternalEffectPrepare,
    WorkflowExternalEffectRead,
    WorkflowExternalEffectReadback,
    WorkflowStepClaimedRead,
    WorkflowStepClaimRequest,
    WorkflowStepComplete,
    WorkflowStepFail,
    WorkflowStepHeartbeat,
    WorkflowStepRead,
)
from app.services.policy import PolicyDecisionService, PolicyRequest


router = APIRouter(tags=["control-plane"])


def get_control_plane_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ControlPlaneRepository:
    return ControlPlaneRepository(connection)


def get_policy_decision_service(
    connection: Annotated[Connection, Depends(get_db)],
) -> PolicyDecisionService:
    return PolicyDecisionService(PolicyRepository(connection))


@contextmanager
def _domain_errors() -> Iterator[None]:
    try:
        yield
    except DomainAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.as_dict()) from exc
    except DomainUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.as_dict()) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc


def _found(value: dict | None, detail: str) -> dict:
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return value


@router.post("/workflow-runs", response_model=WorkflowRunRead, status_code=status.HTTP_201_CREATED)
def create_workflow_run(
    payload: WorkflowRunCreate,
    _request: Request,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    data = payload.model_dump(mode="json")
    data["requested_by"] = operator_id
    current_trace = trace_context_from_current()
    if current_trace is not None:
        data["trace_id"] = current_trace.trace_id
        data["root_span_id"] = current_trace.span_id
    with _domain_errors():
        return repository.create_workflow_run(data)


@router.get("/workflow-runs/{run_code}", response_model=WorkflowRunRead)
def get_workflow_run(
    run_code: str,
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    return _found(repository.get_workflow_run(run_code), "WorkflowRun not found")


@router.post("/workflow-runs/{run_code}/cancel", response_model=WorkflowRunRead)
def cancel_workflow_run(
    run_code: str,
    payload: WorkflowCancelRequest,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    with _domain_errors():
        return _found(
            repository.cancel_workflow_run(run_code, requested_by=operator_id, reason=payload.reason),
            "WorkflowRun not found",
        )


@router.post("/workflow-steps/claim-next", response_model=WorkflowStepClaimedRead | None)
def claim_next_workflow_step(
    payload: WorkflowStepClaimRequest,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict | None:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    return repository.claim_next_step(
        worker_id=worker_id,
        lease_seconds=payload.lease_seconds,
        accepted_step_types=payload.accepted_step_types,
    )


@router.post("/workflow-steps/{step_code}/heartbeat", response_model=WorkflowStepRead)
def heartbeat_workflow_step(
    step_code: str,
    payload: WorkflowStepHeartbeat,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    return _found(
        repository.heartbeat_step(
            step_code,
            worker_id=worker_id,
            claim_token=payload.claim_token,
            lease_version=payload.lease_version,
            lease_seconds=payload.lease_seconds,
        ),
        "Active workflow step lease not found",
    )


@router.post("/workflow-steps/{step_code}/complete", response_model=WorkflowStepRead)
def complete_workflow_step(
    step_code: str,
    payload: WorkflowStepComplete,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        return _found(
            repository.complete_step(
                step_code,
                worker_id=worker_id,
                claim_token=payload.claim_token,
                lease_version=payload.lease_version,
                output_fingerprint=payload.output_fingerprint,
                actual_cost=payload.actual_cost,
            ),
            "Active workflow step lease not found",
        )


@router.post("/workflow-steps/{step_code}/fail", response_model=WorkflowStepRead)
def fail_workflow_step(
    step_code: str,
    payload: WorkflowStepFail,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        return _found(
            repository.fail_step(
                step_code,
                worker_id=worker_id,
                claim_token=payload.claim_token,
                lease_version=payload.lease_version,
                error_code=payload.error_code,
                error_summary=payload.error_summary,
                side_effect_known_not_applied=payload.side_effect_known_not_applied,
            ),
            "Active workflow step lease not found",
        )


@router.post(
    "/workflow-steps/{step_code}/external-effects/prepare",
    response_model=WorkflowExternalEffectRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_workflow_external_effect(
    step_code: str,
    payload: WorkflowExternalEffectPrepare,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        return repository.prepare_external_effect(
            step_code,
            worker_id=worker_id,
            claim_token=payload.claim_token,
            lease_version=payload.lease_version,
            target_type=payload.target_type,
            target_id=payload.target_id,
            operation_type=payload.operation_type,
            idempotency_key=payload.idempotency_key,
            plan_or_release_hash=payload.plan_or_release_hash,
            request_fingerprint=payload.request_fingerprint,
        )


@router.post("/workflow-external-effects/{effect_code}/authorize", response_model=WorkflowExternalEffectRead)
def authorize_workflow_external_effect(
    effect_code: str,
    payload: WorkflowExternalEffectAuthorize,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
    policy_service: Annotated[PolicyDecisionService, Depends(get_policy_decision_service)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        effect = _found(repository.get_external_effect(effect_code), "Workflow external effect not found")
        try:
            capability = Capability(effect["operation_type"])
        except ValueError as exc:
            raise DomainAuthorizationError(
                "EXTERNAL_EFFECT_CAPABILITY_INVALID",
                "External effect operation is not an execution capability",
            ) from exc
        policy_service.authorize_commit(
            authorization_code=payload.authorization_code,
            raw_token=payload.authorization_token.get_secret_value(),
            request=PolicyRequest(
                principal_type="worker",
                principal_id=worker_id,
                roles=frozenset({"production_worker"}),
                capability=capability,
                target_type=effect["target_type"],
                target_id=effect["target_id"],
                action="commit",
                environment=settings.app_env,
                plan_or_release_hash=effect["plan_or_release_hash"],
                site_fingerprint=payload.site_fingerprint,
            ),
            commit=False,
        )
        repository.assert_external_effect_target_writable(
            effect_code,
            capability=capability.value,
        )
        return repository.authorize_external_effect(
            effect_code,
            expected_revision=payload.expected_revision,
            authorization_code=payload.authorization_code,
            actor_id=worker_id,
        )


@router.post("/workflow-external-effects/{effect_code}/commit", response_model=WorkflowExternalEffectRead)
def begin_workflow_external_commit(
    effect_code: str,
    payload: WorkflowExternalEffectBegin,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        return repository.begin_external_commit(
            effect_code,
            expected_revision=payload.expected_revision,
            actor_id=worker_id,
        )


@router.post("/workflow-external-effects/{effect_code}/commit-result", response_model=WorkflowExternalEffectRead)
def record_workflow_external_commit(
    effect_code: str,
    payload: WorkflowExternalEffectCommit,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        return repository.record_external_commit(
            effect_code,
            expected_revision=payload.expected_revision,
            actor_id=worker_id,
            outcome=payload.outcome,
            response_summary=payload.response_summary,
            external_identity=payload.external_identity,
            error_code=payload.error_code,
        )


@router.post("/workflow-external-effects/{effect_code}/readback", response_model=WorkflowExternalEffectRead)
def complete_workflow_external_readback(
    effect_code: str,
    payload: WorkflowExternalEffectReadback,
    worker_id: Annotated[str, Depends(require_control_plane_worker)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.worker_id != worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch")
    with _domain_errors():
        return repository.complete_external_readback(
            effect_code,
            expected_revision=payload.expected_revision,
            actor_id=worker_id,
            external_identity=payload.external_identity,
            readback_evidence=payload.readback_evidence,
        )


@router.get("/human-tasks", response_model=list[HumanTaskRead])
def list_human_tasks(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
    status_filter: Annotated[HumanTaskStatus | None, Query(alias="status")] = None,
    owner_principal: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_human_tasks(
        status=status_filter,
        owner_principal=owner_principal,
        limit=limit,
        offset=offset,
    )


@router.get("/human-tasks/{task_code}", response_model=HumanTaskRead)
def get_human_task(
    task_code: str,
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    return _found(repository.get_human_task(task_code), "HumanTask not found")


@router.post("/human-tasks/{task_code}/claim", response_model=HumanTaskRead)
def claim_human_task(
    task_code: str,
    payload: HumanTaskClaim,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.claimed_by != operator_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator identity mismatch")
    return _found(
        repository.claim_human_task(
            task_code,
            claimed_by=operator_id,
            expected_revision=payload.expected_revision,
        ),
        "Open HumanTask revision not found",
    )


@router.post("/human-tasks/{task_code}/decide", response_model=HumanTaskRead)
def decide_human_task(
    task_code: str,
    payload: HumanTaskDecision,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_plane_repository)],
) -> dict:
    if payload.decided_by != operator_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator identity mismatch")
    with _domain_errors():
        return _found(
            repository.decide_human_task(
                task_code,
                decided_by=operator_id,
                expected_revision=payload.expected_revision,
                decision=payload.decision,
                structured_reason=payload.structured_reason,
            ),
            "HumanTask not found",
        )
