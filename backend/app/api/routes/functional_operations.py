from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from psycopg import Connection
from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.schemas.functional_operations import (
    AttributionReportCreate,
    AttributionReportPublish,
    AttributionReportRead,
    ContentExposureCorrection,
    ContentExposureCreate,
    ContentExposureRead,
    ContentTimelineRead,
    OperationSessionCreate,
    OperationSessionRead,
    OperationImportBatchRead,
    OperationImportConfirm,
    OperationSessionBindingRead,
    OperationSessionBindingResolve,
    PendingOperationBindingRead,
    SessionMetricSnapshotCreate,
    SessionMetricSnapshotRead,
    SchedulePlanCreate,
    SchedulePlanRead,
    TimeMappingCreate,
    TimeMappingRead,
)
from app.services.functional_operations import FunctionalOperationsService
from app.services.functional_operation_imports import FunctionalOperationImportService

router = APIRouter(prefix="/functional-operations", tags=["functional-operations"])


def service(
    connection: Annotated[Connection, Depends(get_db)],
) -> FunctionalOperationsService:
    return FunctionalOperationsService(connection)


def import_service(
    connection: Annotated[Connection, Depends(get_db)],
) -> FunctionalOperationImportService:
    return FunctionalOperationImportService(connection)


def call(fn, *args):
    try:
        return fn(*args)
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get("/import-template")
def download_import_template(
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx)$")] = "xlsx",
) -> Response:
    try:
        content, media_type, filename = FunctionalOperationImportService.template(file_format)
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/import-batches/preview",
    response_model=OperationImportBatchRead,
    status_code=status.HTTP_201_CREATED,
)
async def preview_import_batch(
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
    file: Annotated[UploadFile, File(...)],
    actor: Annotated[str, Form(min_length=1, max_length=128)] = "functional-operator",
) -> dict:
    content = await file.read()
    return call(instance.preview, file.filename or "operation-data", content, actor)


@router.get("/import-batches", response_model=list[OperationImportBatchRead])
def list_import_batches(
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
) -> list[dict]:
    return instance.list()


@router.get("/import-batches/{batch_code}", response_model=OperationImportBatchRead)
def get_import_batch(
    batch_code: str,
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
) -> dict:
    result = instance.get(batch_code)
    if result is None:
        raise HTTPException(status_code=404, detail="Operation import batch not found")
    return result


@router.get("/import-batches/{batch_code}/source")
def download_import_source(
    batch_code: str,
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
) -> Response:
    result = instance.source_file(batch_code)
    if result is None:
        raise HTTPException(status_code=404, detail="Operation import batch not found")
    content, media_type, filename = result
    safe_filename = filename.replace('"', "")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.post(
    "/import-batches/{batch_code}/confirm",
    response_model=OperationImportBatchRead,
)
def confirm_import_batch(
    batch_code: str,
    payload: OperationImportConfirm,
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
) -> dict:
    return call(instance.confirm, batch_code, payload.actor)


@router.get("/pending-bindings", response_model=list[PendingOperationBindingRead])
def list_pending_bindings(
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
) -> list[dict]:
    return instance.pending_bindings()


@router.post(
    "/sessions/{session_code}/binding",
    response_model=OperationSessionBindingRead,
)
def resolve_session_binding(
    session_code: str,
    payload: OperationSessionBindingResolve,
    instance: Annotated[FunctionalOperationImportService, Depends(import_service)],
) -> dict:
    return call(instance.resolve_session_binding, session_code, payload.model_dump())


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


@router.get(
    "/sessions/{session_code}/metric-snapshots",
    response_model=list[SessionMetricSnapshotRead],
)
def list_session_metric_snapshots(
    session_code: str,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> list[dict]:
    return call(instance.list_session_metric_snapshots, session_code)


@router.post(
    "/sessions/{session_code}/metric-snapshots",
    response_model=SessionMetricSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_session_metric_snapshot(
    session_code: str,
    payload: SessionMetricSnapshotCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.create_session_metric_snapshot, session_code, payload.model_dump())


@router.get(
    "/sessions/{session_code}/content-timeline", response_model=ContentTimelineRead
)
def get_content_timeline(
    session_code: str,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.get_content_timeline, session_code)


@router.get(
    "/sessions/{session_code}/time-mappings", response_model=list[TimeMappingRead]
)
def list_time_mappings(
    session_code: str,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> list[dict]:
    return instance.list_time_mappings(session_code)


@router.post(
    "/sessions/{session_code}/time-mappings",
    response_model=TimeMappingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_time_mapping(
    session_code: str,
    payload: TimeMappingCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.create_time_mapping, session_code, payload.model_dump())


@router.post(
    "/exposures",
    response_model=ContentExposureRead,
    status_code=status.HTTP_201_CREATED,
)
def create_exposure(
    payload: ContentExposureCreate,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.create_exposure, payload.model_dump())


@router.get("/exposures", response_model=list[ContentExposureRead])
def list_exposures(
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> list[dict]:
    return instance.list_exposures()


@router.post("/exposure-corrections", response_model=ContentExposureRead)
def correct_exposure(
    payload: ContentExposureCorrection,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.correct_exposure, payload.model_dump())


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
    "/attribution-reports/{report_code}/publish-descriptive",
    response_model=AttributionReportRead,
)
def publish_descriptive_report(
    report_code: str,
    payload: AttributionReportPublish,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.publish_descriptive_report, report_code, payload.actor)


@router.post(
    "/attribution-reports/{report_code}/rerun",
    response_model=AttributionReportRead,
    status_code=status.HTTP_201_CREATED,
)
def rerun_report(
    report_code: str,
    instance: Annotated[FunctionalOperationsService, Depends(service)],
) -> dict:
    return call(instance.rerun_report, report_code)


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
