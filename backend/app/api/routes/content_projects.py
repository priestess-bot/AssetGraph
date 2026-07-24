from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.domain.errors import DomainConflictError, DomainValidationError
from app.schemas.content_projects import (
    ContentProjectConfirm,
    ContentProjectCreate,
    ContentProjectDetail,
    ContentProjectSummary,
    ContentProjectUpdate,
)
from app.services.functional_content import FunctionalContentService


router = APIRouter(prefix="/content-projects", tags=["content-projects"])


def get_service(connection: Annotated[Connection, Depends(get_db)]) -> FunctionalContentService:
    return FunctionalContentService(connection)


@router.post("", response_model=ContentProjectSummary, status_code=status.HTTP_201_CREATED)
def create_content_project(
    payload: ContentProjectCreate,
    service: Annotated[FunctionalContentService, Depends(get_service)],
) -> dict:
    return service.create_project(payload.model_dump(mode="json"), actor_id="functional-operator")


@router.get("", response_model=list[ContentProjectSummary])
def list_content_projects(service: Annotated[FunctionalContentService, Depends(get_service)]) -> list[dict]:
    return service.list_projects()


@router.get("/{project_code}", response_model=ContentProjectDetail)
def get_content_project(project_code: str, service: Annotated[FunctionalContentService, Depends(get_service)]) -> dict:
    detail = service.get_detail(project_code)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found")
    return detail


@router.patch("/{project_code}", response_model=ContentProjectDetail)
def update_content_project(
    project_code: str,
    payload: ContentProjectUpdate,
    service: Annotated[FunctionalContentService, Depends(get_service)],
) -> dict:
    try:
        return service.update_project(
            project_code,
            payload.model_dump(mode="json", exclude_unset=True),
            actor_id="functional-operator",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found") from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc


@router.post("/{project_code}/confirm", response_model=ContentProjectDetail)
def confirm_content_project(
    project_code: str,
    payload: ContentProjectConfirm,
    service: Annotated[FunctionalContentService, Depends(get_service)],
) -> dict:
    try:
        return service.confirm_project(
            project_code,
            expected_revision=payload.expected_revision,
            actor_id="functional-operator",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found") from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc


@router.post("/{project_code}/generate", response_model=ContentProjectDetail)
def generate_content_chain(project_code: str, service: Annotated[FunctionalContentService, Depends(get_service)]) -> dict:
    try:
        detail = service.generate_chain(project_code, actor_id="functional-operator")
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found") from exc
    except (DomainConflictError, DomainValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc
    return detail
