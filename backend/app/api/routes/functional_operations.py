from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.schemas.functional_operations import (
    AttributionReportCreate,
    AttributionReportRead,
    ContentExposureCreate,
    ContentExposureRead,
    OperationSessionCreate,
    OperationSessionRead,
    SchedulePlanCreate,
    SchedulePlanRead,
)
from app.services.functional_operations import FunctionalOperationsService

router = APIRouter(prefix="/functional-operations", tags=["functional-operations"])


def service(
    connection: Annotated[Connection, Depends(get_db)],
) -> FunctionalOperationsService:
    return FunctionalOperationsService(connection)


def call(fn, *args):
    try:
        return fn(*args)
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post(
    "/sessions",
    response_model=OperationSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: OperationSessionCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.import_session, payload.model_dump())


@router.get("/sessions", response_model=list[OperationSessionRead])
def list_sessions(
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> list[dict]:
    return instance.list_sessions()


@router.post("/exposures", response_model=ContentExposureRead, status_code=status.HTTP_201_CREATED)
def create_exposure(
    payload: ContentExposureCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.create_exposure, payload.model_dump())


@router.get("/exposures", response_model=list[ContentExposureRead])
def list_exposures(instance: Annotated[FunctionalOperationsService, Depends(service)]) -> list[dict]:
    return instance.list_exposures()


@router.post(
    "/attribution-reports",
    response_model=AttributionReportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    payload: AttributionReportCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.create_report, payload.model_dump())


@router.get("/attribution-reports", response_model=list[AttributionReportRead])
def list_reports(
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> list[dict]:
    return instance.list_reports()


@router.post(
    "/schedule-plans",
    response_model=SchedulePlanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_schedule(
    payload: SchedulePlanCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return instance.create_schedule(payload.model_dump())


@router.get("/schedule-plans", response_model=list[SchedulePlanRead])
def list_schedules(
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> list[dict]:
    return instance.list_schedules()
