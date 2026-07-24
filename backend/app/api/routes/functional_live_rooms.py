from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.schemas.functional_live_rooms import (
    FunctionalLiveRoomExecutionConfirm,
    FunctionalLiveRoomPlanCreate,
    FunctionalLiveRoomPlanRead,
)
from app.services.functional_live_rooms import FunctionalLiveRoomService


router = APIRouter(prefix="/functional-live-room-plans", tags=["functional-live-rooms"])


def get_service(connection: Annotated[Connection, Depends(get_db)]) -> FunctionalLiveRoomService:
    return FunctionalLiveRoomService(connection)


@router.post("", response_model=FunctionalLiveRoomPlanRead, status_code=status.HTTP_201_CREATED)
def create_live_room_plan(
    payload: FunctionalLiveRoomPlanCreate,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        return service.create_plan(payload.model_dump(mode="json"), actor_id="functional-operator")
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc


@router.get("", response_model=list[FunctionalLiveRoomPlanRead])
def list_live_room_plans(service: Annotated[FunctionalLiveRoomService, Depends(get_service)]) -> list[dict]:
    return service.list_plans()


@router.get("/{plan_code}", response_model=FunctionalLiveRoomPlanRead)
def get_live_room_plan(plan_code: str, service: Annotated[FunctionalLiveRoomService, Depends(get_service)]) -> dict:
    plan = service.get_plan(plan_code)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found")
    return plan


@router.post("/{plan_code}/confirm-execution", response_model=FunctionalLiveRoomPlanRead)
def confirm_live_room_execution(
    plan_code: str,
    payload: FunctionalLiveRoomExecutionConfirm,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        plan = service.confirm_execution(plan_code, confirmed=payload.confirmed)
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found")
    return plan


@router.post("/{plan_code}/release-candidate", response_model=FunctionalLiveRoomPlanRead)
def create_live_room_release_candidate(
    plan_code: str,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        plan = service.create_release_candidate(plan_code, actor_id="functional-operator")
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc
    return plan
