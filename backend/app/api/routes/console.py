from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from psycopg import Connection

from app.api.auth import require_control_plane_operator
from app.core.config import settings
from app.core.database import get_db
from app.core.telemetry import trace_context_from_current
from app.domain.errors import (
    DomainAuthorizationError,
    DomainConflictError,
    DomainError,
    DomainUnavailableError,
)
from app.repositories.console import ConsoleRepository
from app.repositories.console_commands import ConsoleCommandRepository
from app.repositories.console_drafts import ConsoleDraftRepository
from app.repositories.console_entities import ConsoleEntityRepository
from app.schemas.console import (
    ConsoleAuthorizationIssue,
    ConsoleBusinessOverviewRead,
    ConsoleCommandRead,
    ConsoleContentProjectConfirm,
    ConsoleDraftEntityType,
    ConsoleDraftKind,
    ConsoleDraftRead,
    ConsoleDraftSave,
    ConsoleNotificationRead,
    ConsoleEntityDetailRead,
    ConsoleReleaseDecision,
    ConsoleSearchResultRead,
    ConsoleSessionRead,
    ConsoleTaskRead,
    ConsoleTemplatePublish,
)


router = APIRouter(prefix="/console", tags=["console"])


def get_console_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ConsoleRepository:
    return ConsoleRepository(connection)


def get_console_entity_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ConsoleEntityRepository:
    return ConsoleEntityRepository(connection)


def get_console_draft_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ConsoleDraftRepository:
    return ConsoleDraftRepository(connection)


def get_console_command_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ConsoleCommandRepository:
    return ConsoleCommandRepository(connection)


@contextmanager
def _domain_errors() -> Iterator[None]:
    try:
        yield
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Console command target was not found") from exc
    except DomainAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.as_dict()) from exc
    except DomainUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.as_dict()) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc


@router.get("/session", response_model=ConsoleSessionRead)
def get_console_session(
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
) -> dict:
    return {"operator_id": operator_id}


@router.get("/search", response_model=list[ConsoleSearchResultRead])
def search_console(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleRepository, Depends(get_console_repository)],
    q: Annotated[str, Query(min_length=2, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict]:
    return repository.search(q, limit=limit)


@router.get("/tasks", response_model=list[ConsoleTaskRead])
def list_console_tasks(
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleRepository, Depends(get_console_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    return repository.list_tasks(operator_id, limit=limit)


@router.get("/notifications", response_model=list[ConsoleNotificationRead])
def list_console_notifications(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleRepository, Depends(get_console_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    return repository.list_notifications(limit=limit)


@router.get("/business-overview", response_model=ConsoleBusinessOverviewRead)
def get_business_overview(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleRepository, Depends(get_console_repository)],
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict:
    end = to_at or datetime.now(UTC)
    start = from_at or end - timedelta(days=29)
    if start >= end:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="开始时间必须早于结束时间")
    if end - start > timedelta(days=366):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="单次最多查看一年数据")
    return repository.business_overview(from_at=start, to_at=end)


@router.get("/entities/{entity_type}/{entity_code}", response_model=ConsoleEntityDetailRead)
def get_console_entity(
    entity_type: str,
    entity_code: str,
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleEntityRepository, Depends(get_console_entity_repository)],
    from_revision: Annotated[int | None, Query(ge=1)] = None,
    to_revision: Annotated[int | None, Query(ge=1)] = None,
) -> dict:
    entity = repository.get_entity(
        entity_type,
        entity_code,
        from_revision=from_revision,
        to_revision=to_revision,
    )
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONSOLE_ENTITY_NOT_FOUND",
                "message": "Console entity was not found or is not a supported type",
            },
        )
    return entity


@router.get(
    "/drafts/{entity_type}/{entity_code}/{draft_kind}",
    response_model=ConsoleDraftRead | None,
)
def get_console_draft(
    entity_type: ConsoleDraftEntityType,
    entity_code: Annotated[str, Path(min_length=1, max_length=128)],
    draft_kind: ConsoleDraftKind,
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleDraftRepository, Depends(get_console_draft_repository)],
) -> dict | None:
    return repository.get_draft(entity_type, entity_code, draft_kind)


@router.put(
    "/drafts/{entity_type}/{entity_code}/{draft_kind}",
    response_model=ConsoleDraftRead,
)
def save_console_draft(
    entity_type: ConsoleDraftEntityType,
    entity_code: Annotated[str, Path(min_length=1, max_length=128)],
    draft_kind: ConsoleDraftKind,
    payload: ConsoleDraftSave,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleDraftRepository, Depends(get_console_draft_repository)],
) -> dict:
    with _domain_errors():
        return repository.save_draft(
            entity_type=entity_type,
            entity_code=entity_code,
            draft_kind=draft_kind,
            schema_version=payload.schema_version,
            expected_revision=payload.expected_revision,
            base_entity_revision=payload.base_entity_revision,
            document=payload.document,
            actor_id=operator_id,
        )


@router.post(
    "/content-projects/{project_code}/confirm",
    response_model=ConsoleCommandRead,
)
def confirm_content_project(
    project_code: Annotated[str, Path(min_length=1, max_length=64)],
    payload: ConsoleContentProjectConfirm,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleCommandRepository, Depends(get_console_command_repository)],
) -> dict:
    with _domain_errors():
        return repository.confirm_content_project(
            project_code,
            expected_entity_revision=payload.expected_entity_revision,
            expected_draft_revision=payload.expected_draft_revision,
            idempotency_key=payload.idempotency_key,
            actor_id=operator_id,
        )


@router.post(
    "/live-room-templates/{template_code}/publish",
    response_model=ConsoleCommandRead,
)
def publish_live_room_template(
    template_code: Annotated[str, Path(min_length=1, max_length=64)],
    payload: ConsoleTemplatePublish,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleCommandRepository, Depends(get_console_command_repository)],
) -> dict:
    with _domain_errors():
        return repository.publish_live_room_template(
            template_code,
            expected_revision=payload.expected_revision,
            structured_reason=payload.structured_reason.model_dump(mode="json"),
            idempotency_key=payload.idempotency_key,
            actor_id=operator_id,
        )


@router.post(
    "/releases/{release_code}/decision",
    response_model=ConsoleCommandRead,
)
def decide_release(
    release_code: Annotated[str, Path(min_length=1, max_length=80)],
    payload: ConsoleReleaseDecision,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleCommandRepository, Depends(get_console_command_repository)],
) -> dict:
    with _domain_errors():
        return repository.decide_release(
            release_code,
            expected_manifest_revision=payload.expected_manifest_revision,
            decision=payload.decision,
            structured_reason=payload.structured_reason.model_dump(mode="json"),
            approved_scope=payload.approved_scope,
            idempotency_key=payload.idempotency_key,
            actor_id=operator_id,
        )


@router.post(
    "/workflow-runs/{run_code}/authorize",
    response_model=ConsoleCommandRead,
)
def issue_workflow_authorization(
    run_code: Annotated[str, Path(min_length=1, max_length=80)],
    payload: ConsoleAuthorizationIssue,
    response: Response,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[ConsoleCommandRepository, Depends(get_console_command_repository)],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    trace = trace_context_from_current()
    with _domain_errors():
        return repository.issue_authorization(
            run_code,
            task_code=payload.task_code,
            expected_task_revision=payload.expected_task_revision,
            idempotency_key=payload.idempotency_key,
            actor_id=operator_id,
            environment=settings.app_env,
            trace_id=trace.trace_id if trace else None,
        )
