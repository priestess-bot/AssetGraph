from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.schemas.functional_live_rooms import (
    FunctionalLiveRoomBlueprintRevision,
    FunctionalLiveRoomExecutionConfirm,
    FunctionalLiveRoomExecutionHandoffRead,
    FunctionalLiveRoomMaterialGapPreviewRead,
    FunctionalLiveRoomMaterialGapPreviewRequest,
    FunctionalLiveRoomPlanCreate,
    FunctionalLiveRoomPlanClone,
    FunctionalLiveRoomPlanRead,
    FunctionalLiveRoomTraceRead,
    MaituCapabilityMatrixRead,
)
from app.services.functional_live_rooms import FunctionalLiveRoomService
from app.services.maitu_capabilities import maitu_capability_matrix


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


@router.post("/material-gap-preview", response_model=FunctionalLiveRoomMaterialGapPreviewRead)
def preview_live_room_material_gaps(
    payload: FunctionalLiveRoomMaterialGapPreviewRequest,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        return service.preview_material_gaps(payload.model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content project not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc


@router.get("", response_model=list[FunctionalLiveRoomPlanRead])
def list_live_room_plans(service: Annotated[FunctionalLiveRoomService, Depends(get_service)]) -> list[dict]:
    return service.list_plans()


@router.get("/maitu-capabilities", response_model=MaituCapabilityMatrixRead)
def get_maitu_capabilities() -> dict:
    return maitu_capability_matrix()


@router.get("/{plan_code}", response_model=FunctionalLiveRoomPlanRead)
def get_live_room_plan(plan_code: str, service: Annotated[FunctionalLiveRoomService, Depends(get_service)]) -> dict:
    plan = service.get_plan(plan_code)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found")
    return plan


@router.get("/{plan_code}/trace", response_model=FunctionalLiveRoomTraceRead)
def get_live_room_plan_trace(
    plan_code: str,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        return service.get_trace(plan_code)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found") from exc


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


@router.get("/{plan_code}/execution-handoff", response_model=FunctionalLiveRoomExecutionHandoffRead)
def get_live_room_execution_handoff(
    plan_code: str,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        return service.get_execution_handoff(plan_code)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc


@router.post("/{plan_code}/sync-execution", response_model=FunctionalLiveRoomPlanRead)
def sync_live_room_execution(
    plan_code: str,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        plan = service.sync_execution(plan_code)
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


@router.post("/{plan_code}/clone", response_model=FunctionalLiveRoomPlanRead, status_code=status.HTTP_201_CREATED)
def clone_live_room_plan(
    plan_code: str,
    payload: FunctionalLiveRoomPlanClone,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        return service.clone_plan(plan_code, payload.model_dump(mode="json"), actor_id="functional-operator")
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc


@router.post(
    "/{plan_code}/blueprint-revisions",
    response_model=FunctionalLiveRoomPlanRead,
    status_code=status.HTTP_201_CREATED,
)
def revise_live_room_blueprint(
    plan_code: str,
    payload: FunctionalLiveRoomBlueprintRevision,
    service: Annotated[FunctionalLiveRoomService, Depends(get_service)],
) -> dict:
    try:
        return service.revise_blueprint(
            plan_code,
            payload.model_dump(mode="json"),
            actor_id="functional-operator",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live-room plan not found") from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc
