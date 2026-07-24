from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.repositories.video_productions import VideoProductionRetryConflictError
from app.schemas.functional_videos import FunctionalVideoPlanCreate, FunctionalVideoPlanRead, FunctionalVideoTimelineRevisionRead, FunctionalVideoTimelineUpdate
from app.services.functional_videos import FunctionalVideoService


router = APIRouter(prefix="/functional-video-plans", tags=["functional-videos"])


def get_service(connection: Annotated[Connection, Depends(get_db)]) -> FunctionalVideoService:
    return FunctionalVideoService(connection)


@router.post("", response_model=FunctionalVideoPlanRead, status_code=status.HTTP_201_CREATED)
def create_video_plan(payload: FunctionalVideoPlanCreate, service: Annotated[FunctionalVideoService, Depends(get_service)]) -> dict:
    try:
        return service.create_plan(payload.model_dump(mode="json"), actor_id="functional-operator")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Content project not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get("", response_model=list[FunctionalVideoPlanRead])
def list_video_plans(service: Annotated[FunctionalVideoService, Depends(get_service)]) -> list[dict]:
    return service.list_plans()


@router.get("/{plan_code}", response_model=FunctionalVideoPlanRead)
def get_video_plan(plan_code: str, service: Annotated[FunctionalVideoService, Depends(get_service)]) -> dict:
    plan = service.get_plan(plan_code)
    if plan is None:
        raise HTTPException(status_code=404, detail="Video plan not found")
    return plan


@router.get("/{plan_code}/timeline-revisions", response_model=list[FunctionalVideoTimelineRevisionRead])
def list_video_timeline_revisions(
    plan_code: str,
    service: Annotated[FunctionalVideoService, Depends(get_service)],
) -> list[dict]:
    revisions = service.list_timeline_revisions(plan_code)
    if revisions is None:
        raise HTTPException(status_code=404, detail="Video plan not found")
    return revisions


@router.put("/{plan_code}/timeline", response_model=FunctionalVideoPlanRead)
def update_video_timeline(
    plan_code: str,
    payload: FunctionalVideoTimelineUpdate,
    service: Annotated[FunctionalVideoService, Depends(get_service)],
) -> dict:
    try:
        plan = service.update_timeline(plan_code, payload.model_dump(mode="json"), actor_id="functional-operator")
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Video plan not found")
    return plan


@router.post("/{plan_code}/retry", response_model=FunctionalVideoPlanRead)
def retry_video_plan(plan_code: str, service: Annotated[FunctionalVideoService, Depends(get_service)]) -> dict:
    try:
        plan = service.retry(plan_code)
    except VideoProductionRetryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Video plan not found")
    return plan
