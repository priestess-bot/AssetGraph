from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.maitu import MaituMaterialSlotRepository
from app.schemas.maitu import (
    MaituBrowserUseOperationPlanResponse,
    MaituCandidateAssetsResponse,
    MaituMaterialSlotCreate,
    MaituMaterialSlotRead,
    MaituMaterialSlotUpdate,
    MaituReplacementPlanCreate,
    MaituReplacementPlanExecutionResultCreate,
    MaituReplacementPlanExecutionResultRead,
    MaituReplacementPlanRead,
    MaituRetryBrowserUseOperationPlanResponse,
    MaituRetryQueueClaimNextCreate,
    MaituRetryQueueItemRead,
    MaituRetryQueueReclaimExpiredResponse,
    MaituRetryTaskExecutionResultCreate,
    MaituRetryTaskRead,
    MaituRetryTaskReleaseCreate,
    MaituRetryTaskUpdate,
    MaituRetryWorkerNextResponse,
)

router = APIRouter(prefix="/maitu", tags=["maitu"])


def get_maitu_slot_repository(connection: Annotated[Connection, Depends(get_db)]) -> MaituMaterialSlotRepository:
    return MaituMaterialSlotRepository(connection)


@router.post("/slots", response_model=MaituMaterialSlotRead, status_code=status.HTTP_201_CREATED)
def create_maitu_slot(
    payload: MaituMaterialSlotCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("/slots", response_model=list[MaituMaterialSlotRead])
def list_maitu_slots(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    maitu_project_code: str | None = None,
    scene_name: str | None = None,
    required_category: str | None = None,
    slot_name: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(
        maitu_project_code=maitu_project_code,
        scene_name=scene_name,
        required_category=required_category,
        slot_name=slot_name,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/slots/{slot_code}", response_model=MaituMaterialSlotRead)
def get_maitu_slot(
    slot_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_by_code(slot_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
    return row


@router.get("/slots/{slot_code}/candidate-assets", response_model=MaituCandidateAssetsResponse)
def list_candidate_assets_for_slot(
    slot_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    limit: int = 20,
    offset: int = 0,
) -> dict:
    row = repository.list_candidate_assets(slot_code, limit=limit, offset=offset)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
    return row


@router.patch("/slots/{slot_code}", response_model=MaituMaterialSlotRead)
def update_maitu_slot(
    slot_code: str,
    payload: MaituMaterialSlotUpdate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.update(slot_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
    return row


@router.delete("/slots/{slot_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_maitu_slot(
    slot_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> None:
    deleted = repository.soft_delete(slot_code)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")


@router.post("/replacement-plans", response_model=MaituReplacementPlanRead, status_code=status.HTTP_201_CREATED)
def create_replacement_plan(
    payload: MaituReplacementPlanCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.create_replacement_plan(payload.model_dump(exclude_none=True))


@router.get("/replacement-plans", response_model=list[MaituReplacementPlanRead])
def list_replacement_plans(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    maitu_project_code: str | None = None,
    scene_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_replacement_plans(
        maitu_project_code=maitu_project_code,
        scene_name=scene_name,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/replacement-plans/{plan_code}", response_model=MaituReplacementPlanRead)
def get_replacement_plan(
    plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_replacement_plan_by_code(plan_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return row


@router.get("/replacement-plans/{plan_code}/browser-use-operations", response_model=MaituBrowserUseOperationPlanResponse)
def get_browser_use_operations(
    plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_browser_use_operation_plan(plan_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return row


@router.post(
    "/replacement-plans/{plan_code}/execution-results",
    response_model=MaituReplacementPlanExecutionResultRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution_result(
    plan_code: str,
    payload: MaituReplacementPlanExecutionResultCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_execution_result(plan_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return row


@router.get("/replacement-plans/{plan_code}/execution-results", response_model=list[MaituReplacementPlanExecutionResultRead])
def list_execution_results(
    plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    executor: str | None = None,
    execution_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    rows = repository.list_execution_results(
        plan_code,
        executor=executor,
        execution_status=execution_status,
        limit=limit,
        offset=offset,
    )
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return rows


@router.get(
    "/replacement-plans/{plan_code}/execution-results/{execution_code}",
    response_model=MaituReplacementPlanExecutionResultRead,
)
def get_execution_result(
    plan_code: str,
    execution_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_execution_result_by_code(plan_code, execution_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu execution result not found")
    return row


@router.get("/retry-tasks", response_model=list[MaituRetryTaskRead])
def list_retry_tasks(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    plan_code: str | None = None,
    execution_code: str | None = None,
    status: str | None = None,
    failure_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_retry_tasks(
        plan_code=plan_code,
        execution_code=execution_code,
        status=status,
        failure_type=failure_type,
        limit=limit,
        offset=offset,
    )


@router.get("/retry-queue", response_model=list[MaituRetryQueueItemRead])
def list_retry_queue(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    status: str | None = "pending",
    failure_type: str | None = None,
    maitu_project_code: str | None = None,
    scene_name: str | None = None,
    max_attempts: int = 3,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_retry_queue(
        status=status,
        failure_type=failure_type,
        maitu_project_code=maitu_project_code,
        scene_name=scene_name,
        max_attempts=max_attempts,
        limit=limit,
        offset=offset,
    )


@router.post("/retry-queue/claim-next", response_model=MaituRetryQueueItemRead)
def claim_next_retry_task(
    payload: MaituRetryQueueClaimNextCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.claim_next_retry_task(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No claimable Maitu retry task found")
    return row


@router.post("/retry-queue/reclaim-expired", response_model=MaituRetryQueueReclaimExpiredResponse)
def reclaim_expired_retry_tasks(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.reclaim_expired_retry_tasks()


@router.post("/retry-worker/next", response_model=MaituRetryWorkerNextResponse)
def get_retry_worker_next(
    payload: MaituRetryQueueClaimNextCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_retry_worker_next(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No claimable Maitu retry task found")
    return row


@router.get("/retry-tasks/{retry_task_code}", response_model=MaituRetryTaskRead)
def get_retry_task(
    retry_task_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_retry_task_by_code(retry_task_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.get(
    "/retry-tasks/{retry_task_code}/browser-use-operations",
    response_model=MaituRetryBrowserUseOperationPlanResponse,
)
def get_retry_task_browser_use_operations(
    retry_task_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.post("/retry-tasks/{retry_task_code}/execution-results", response_model=MaituRetryTaskRead)
def create_retry_task_execution_result(
    retry_task_code: str,
    payload: MaituRetryTaskExecutionResultCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_retry_task_execution_result(retry_task_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.post("/retry-tasks/{retry_task_code}/release", response_model=MaituRetryTaskRead)
def release_retry_task(
    retry_task_code: str,
    payload: MaituRetryTaskReleaseCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.release_retry_task(retry_task_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.patch("/retry-tasks/{retry_task_code}", response_model=MaituRetryTaskRead)
def update_retry_task(
    retry_task_code: str,
    payload: MaituRetryTaskUpdate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.update_retry_task(retry_task_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row
