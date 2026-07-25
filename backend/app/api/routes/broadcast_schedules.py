from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.schemas.broadcast_schedules import BroadcastScheduleCreate, BroadcastScheduleRead
from app.services.broadcast_schedules import BroadcastScheduleService


router = APIRouter(prefix="/broadcast-schedules", tags=["broadcast-schedules"])


def service(c: Annotated[Connection, Depends(get_db)]) -> BroadcastScheduleService:
    return BroadcastScheduleService(c)


@router.post("", response_model=BroadcastScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: BroadcastScheduleCreate,
    schedules: Annotated[BroadcastScheduleService, Depends(service)],
) -> dict:
    return schedules.create(payload.model_dump())


@router.get("", response_model=list[BroadcastScheduleRead])
def list_schedules(
    schedules: Annotated[BroadcastScheduleService, Depends(service)],
) -> list[dict]:
    return schedules.list()


@router.get("/{schedule_code}", response_model=BroadcastScheduleRead)
def get_schedule(
    schedule_code: str,
    schedules: Annotated[BroadcastScheduleService, Depends(service)],
) -> dict:
    result = schedules.get(schedule_code)
    if result is None:
        raise HTTPException(status_code=404, detail="Broadcast schedule not found")
    return result


@router.post("/{schedule_code}/validate", response_model=BroadcastScheduleRead)
def validate_schedule(
    schedule_code: str,
    schedules: Annotated[BroadcastScheduleService, Depends(service)],
) -> dict:
    result = schedules.validate(schedule_code)
    if result is None:
        raise HTTPException(status_code=404, detail="Broadcast schedule not found")
    return result
