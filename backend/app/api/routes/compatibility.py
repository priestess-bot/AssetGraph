from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection

from app.api.auth import require_control_plane_operator
from app.core.database import get_db
from app.repositories.workflow_compatibility import WorkflowCompatibilityRepository
from app.schemas.compatibility import (
    LegacyAssetObservationRead,
    LegacyContentProjectRead,
    LegacyDeliveryUnknownRead,
    LegacyLayoutHypothesisRead,
    LegacyLiveRoomVariantRead,
    LegacyWorkflowRunRead,
)


router = APIRouter(prefix="/compatibility", tags=["compatibility"])


def get_workflow_compatibility_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> WorkflowCompatibilityRepository:
    return WorkflowCompatibilityRepository(connection)


@router.get("/workflow-runs", response_model=list[LegacyWorkflowRunRead])
def list_legacy_workflow_runs(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
    source_type: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_runs(
        source_type=source_type,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/workflow-runs/{projection_run_code}", response_model=LegacyWorkflowRunRead)
def get_legacy_workflow_run(
    projection_run_code: str,
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
) -> dict:
    run = repository.get_run(projection_run_code)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "LEGACY_WORKFLOW_PROJECTION_NOT_FOUND",
                "message": "Legacy workflow projection was not found",
            },
        )
    return run


@router.get("/assets", response_model=list[LegacyAssetObservationRead])
def list_legacy_asset_observations(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_asset_observations(limit=limit, offset=offset)


@router.get("/content-projects", response_model=list[LegacyContentProjectRead])
def list_legacy_content_projects(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_content_projects(limit=limit, offset=offset)


@router.get("/live-room-variants", response_model=list[LegacyLiveRoomVariantRead])
def list_legacy_live_room_variants(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_live_room_variants(limit=limit, offset=offset)


@router.get("/layout-hypotheses", response_model=list[LegacyLayoutHypothesisRead])
def list_legacy_layout_hypotheses(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_layout_hypotheses(limit=limit, offset=offset)


@router.get("/delivery-unknown", response_model=list[LegacyDeliveryUnknownRead])
def list_legacy_delivery_unknown(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[
        WorkflowCompatibilityRepository,
        Depends(get_workflow_compatibility_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return repository.list_delivery_unknown(limit=limit, offset=offset)
