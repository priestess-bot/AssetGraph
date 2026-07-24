from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated, Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg import Connection

from app.api.auth import reject_maitu_durable_secret, require_maitu_script_layout_worker
from app.core.database import get_db
from app.repositories.maitu import MaituMaterialSlotRepository
from app.repositories.maitu_workbench import (
    MaituWorkbenchConflictError,
    MaituWorkbenchLeaseConflictError,
    MaituWorkbenchRepository,
)
from app.schemas.maitu_workbench import (
    DraftExecutionClaim,
    DraftExecutionComplete,
    DraftExecutionFail,
    DraftExecutionHeartbeat,
    DraftExecutionJobClaimedRead,
    DraftExecutionJobCreate,
    DraftExecutionJobRead,
    DraftExecutionRetry,
    InventorySnapshotRead,
    InventorySyncClaim,
    InventorySyncComplete,
    InventorySyncFail,
    InventorySyncHeartbeat,
    InventorySyncJobClaimedRead,
    InventorySyncJobCreate,
    InventorySyncJobRead,
    InventorySyncJobStatus,
    InventorySyncRetry,
    MaterialDecisionCreate,
    MaterialDecisionRead,
    MaterialRequirementRead,
    ProductFactCardCreate,
    ProductFactCardRead,
    ProductFactCardUsageRead,
    ProductFactCardVersionApprove,
    ProductFactCardVersionCreate,
    ProductFactCardVersionRead,
    ProductFactCardVersionReject,
    WorkbenchPlanCreate,
    WorkbenchPlanRevisionRead,
    WorkbenchPreflightCreate,
    WorkbenchPreflightRead,
    WorkbenchReplanCreate,
    WorkbenchRunCreate,
    WorkbenchRunRead,
    WorkbenchRunStatus,
    WorkbenchRunTargetUpdate,
)
from app.schemas.material_analysis import (
    AnalysisConflictRead,
    AnalysisConflictResolve,
    GeminiBackfillCreate,
    VideoAnalysisClaim,
    VideoAnalysisClaimedRead,
    VideoAnalysisComplete,
    VideoAnalysisFail,
    VideoAnalysisHeartbeat,
    VideoAnalysisRead,
    VideoAnalysisRetry,
)
from app.services.maitu_workbench import (
    MaituWorkbenchService,
    WorkbenchModelGenerationError,
    WorkbenchModelUnavailableError,
)
from app.services.maitu_authority import (
    MaituAuthorityConfigurationError,
    MaituAuthorityError,
    MaituAuthorityUpstreamError,
    MaituAuthorityVerifier,
    get_maitu_authority_verifier,
)
from app.services.material_analysis import MaterialAnalysisError, MaterialAnalysisWorkbenchService


router = APIRouter(prefix="/maitu/workbench", tags=["maitu-workbench"])

_PROTOCOL_FIELDS = {
    "lease_token",
    "idempotency_key",
    "checksum_sha256",
    "content_sha256",
    "fingerprint_sha256",
    "request_fingerprint",
    "input_fingerprint",
    "output_fingerprint",
    "source_revision",
    "source_material_url",
    "source_cover_url",
    "request_id",
    "completion_id",
    "attempt_id",
    "operation_fingerprint",
    "asset_fingerprint",
    "model_input_fingerprint",
    "model_output_fingerprint",
    "sha256",
}


def get_maitu_workbench_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> MaituWorkbenchRepository:
    return MaituWorkbenchRepository(connection)


def get_maitu_workbench_service(
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> MaituWorkbenchService:
    return MaituWorkbenchService(
        repository,
        MaituMaterialSlotRepository(repository.connection),
    )


def get_material_analysis_workbench_service(
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> MaterialAnalysisWorkbenchService:
    return MaterialAnalysisWorkbenchService(repository)


def _reject_secret(payload: Any) -> None:
    reject_maitu_durable_secret(payload, protocol_fields=_PROTOCOL_FIELDS)


@contextmanager
def _workbench_errors() -> Iterator[None]:
    try:
        yield
    except WorkbenchModelUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except WorkbenchModelGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except MaterialAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (MaituAuthorityConfigurationError, MaituAuthorityUpstreamError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except MaituAuthorityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workbench resource not found") from exc
    except (MaituWorkbenchLeaseConflictError, MaituWorkbenchConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _found(row: dict[str, Any] | None, detail: str) -> dict[str, Any]:
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return row


# Product fact cards ----------------------------------------------------


@router.post("/product-fact-cards", response_model=ProductFactCardRead, status_code=status.HTTP_201_CREATED)
def create_product_fact_card(
    payload: ProductFactCardCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.create_product_fact_card(payload.model_dump(mode="json"))


@router.get("/product-fact-cards", response_model=list[ProductFactCardRead])
def list_product_fact_cards(
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return repository.list_product_fact_cards(limit=limit, offset=offset)


@router.get("/product-fact-cards/{fact_card_code}", response_model=ProductFactCardRead)
def get_product_fact_card(
    fact_card_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    return _found(repository.get_product_fact_card(fact_card_code), "Product fact card not found")


@router.get(
    "/product-fact-cards/{fact_card_code}/versions/{version_number}/usage",
    response_model=list[ProductFactCardUsageRead],
)
def list_product_fact_card_usage(
    fact_card_code: str,
    version_number: int,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> list[dict[str, Any]]:
    usage = repository.list_product_fact_card_usage(fact_card_code, version_number)
    return _found(usage, "Product fact card version not found")


@router.post(
    "/product-fact-cards/{fact_card_code}/versions",
    response_model=ProductFactCardVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_product_fact_card_version(
    fact_card_code: str,
    payload: ProductFactCardVersionCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            service.create_product_fact_card_version(fact_card_code, payload.model_dump(mode="json")),
            "Product fact card not found",
        )


@router.post(
    "/product-fact-cards/{fact_card_code}/versions/{version_number}/approve",
    response_model=ProductFactCardVersionRead,
)
def approve_product_fact_card_version(
    fact_card_code: str,
    version_number: int,
    payload: ProductFactCardVersionApprove,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            repository.approve_product_fact_card_version(fact_card_code, version_number, payload.approved_by),
            "Product fact card version not found",
        )


@router.post(
    "/product-fact-cards/{fact_card_code}/versions/{version_number}/reject",
    response_model=ProductFactCardVersionRead,
)
def reject_product_fact_card_version(
    fact_card_code: str,
    version_number: int,
    payload: ProductFactCardVersionReject,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            repository.reject_product_fact_card_version(
                fact_card_code,
                version_number,
                rejected_by=payload.rejected_by,
                reason=payload.reason,
            ),
            "Product fact card version not found",
        )


# Inventory snapshots --------------------------------------------------


@router.post("/inventory-sync-jobs", response_model=InventorySyncJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_inventory_sync_job(
    payload: InventorySyncJobCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.create_inventory_sync_job(payload.model_dump(mode="json"))


@router.get("/inventory-sync-jobs", response_model=list[InventorySyncJobRead])
def list_inventory_sync_jobs(
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
    status_filter: Annotated[InventorySyncJobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return repository.list_inventory_sync_jobs(status=status_filter, limit=limit, offset=offset)


@router.post("/inventory-sync-jobs/claim-next", response_model=InventorySyncJobClaimedRead | None)
def claim_next_inventory_sync_job(
    payload: InventorySyncClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any] | Response:
    claimed = repository.claim_inventory_sync_job(worker_id, payload.lease_seconds)
    return claimed if claimed is not None else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/inventory-sync-jobs/{sync_job_code}", response_model=InventorySyncJobRead)
def get_inventory_sync_job(
    sync_job_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    return _found(repository.get_inventory_sync_job(sync_job_code), "Inventory sync job not found")


@router.post("/inventory-sync-jobs/{sync_job_code}/claim", response_model=InventorySyncJobClaimedRead)
def claim_inventory_sync_job(
    sync_job_code: str,
    payload: InventorySyncClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    row = repository.claim_inventory_sync_job(worker_id, payload.lease_seconds, sync_job_code=sync_job_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory sync job is not claimable")
    return row


@router.post("/inventory-sync-jobs/{sync_job_code}/heartbeat", response_model=InventorySyncJobRead)
def heartbeat_inventory_sync_job(
    sync_job_code: str,
    payload: InventorySyncHeartbeat,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    row = repository.heartbeat_inventory_sync_job(
        sync_job_code,
        worker_id,
        payload.lease_token,
        payload.lease_seconds,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory sync lease is not active")
    return row


@router.post("/inventory-sync-jobs/{sync_job_code}/complete", response_model=InventorySyncJobRead)
def complete_inventory_sync_job(
    sync_job_code: str,
    payload: InventorySyncComplete,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            service.complete_inventory_sync_job(sync_job_code, worker_id, payload.model_dump(mode="json")),
            "Inventory sync job not found",
        )


@router.post("/inventory-sync-jobs/{sync_job_code}/fail", response_model=InventorySyncJobRead)
def fail_inventory_sync_job(
    sync_job_code: str,
    payload: InventorySyncFail,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return repository.fail_inventory_sync_job(
            sync_job_code,
            worker_id,
            payload.lease_token,
            error_code=payload.error_code,
            error_message=payload.error_message,
        )


@router.post("/inventory-sync-jobs/{sync_job_code}/retry", response_model=InventorySyncJobRead)
def retry_inventory_sync_job(
    sync_job_code: str,
    payload: InventorySyncRetry,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            repository.retry_inventory_sync_job(sync_job_code, payload.requested_by),
            "Inventory sync job not found",
        )


@router.get("/inventory-snapshots/{snapshot_code}", response_model=InventorySnapshotRead)
def get_inventory_snapshot(
    snapshot_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
    include_items: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    return _found(
        repository.get_inventory_snapshot(snapshot_code, include_items=include_items),
        "Inventory snapshot not found",
    )


# Workbench plans and decisions ---------------------------------------


@router.post("/runs", response_model=WorkbenchRunRead, status_code=status.HTTP_201_CREATED)
def create_workbench_run(
    payload: WorkbenchRunCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.create_run(payload.model_dump(mode="json"))


@router.get("/runs", response_model=list[WorkbenchRunRead])
def list_workbench_runs(
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
    status_filter: Annotated[WorkbenchRunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return repository.list_runs(status=status_filter, limit=limit, offset=offset)


@router.get("/runs/{run_code}", response_model=WorkbenchRunRead)
def get_workbench_run(
    run_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    return _found(repository.get_run(run_code), "Workbench run not found")


@router.patch("/runs/{run_code}/target-live-room", response_model=WorkbenchRunRead)
def update_workbench_run_target_live_room(
    run_code: str,
    payload: WorkbenchRunTargetUpdate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            service.update_run_target_live_room(run_code, payload.target_live_room_id),
            "Workbench run not found",
        )


@router.post(
    "/runs/{run_code}/plans",
    response_model=WorkbenchPlanRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_initial_workbench_plan(
    run_code: str,
    payload: WorkbenchPlanCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.create_initial_plan(run_code, payload.model_dump(mode="json"))


@router.get("/runs/{run_code}/plan-revisions", response_model=list[WorkbenchPlanRevisionRead])
def list_workbench_plan_revisions(
    run_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> list[dict[str, Any]]:
    rows = repository.list_plan_revisions(run_code)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workbench run not found")
    return rows


@router.post(
    "/runs/{run_code}/replan",
    response_model=WorkbenchPlanRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
def replan_workbench_run(
    run_code: str,
    payload: WorkbenchReplanCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.replan(run_code, payload.model_dump(mode="json"))


@router.get("/runs/{run_code}/material-requirements", response_model=list[MaterialRequirementRead])
def list_material_requirements(
    run_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
    active_only: Annotated[bool, Query()] = True,
) -> list[dict[str, Any]]:
    rows = repository.list_material_requirements(run_code, active_only=active_only)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workbench run not found")
    return rows


@router.post(
    "/runs/{run_code}/material-requirements/{requirement_code}/decisions",
    response_model=MaterialDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material_decision(
    run_code: str,
    requirement_code: str,
    payload: MaterialDecisionCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            service.create_material_decision(
                run_code,
                requirement_code,
                payload.model_dump(mode="json"),
            ),
            "Material requirement not found",
        )


@router.post("/runs/{run_code}/preflight", response_model=WorkbenchPreflightRead)
def preflight_workbench_run(
    run_code: str,
    payload: WorkbenchPreflightCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
    authority: Annotated[MaituAuthorityVerifier, Depends(get_maitu_authority_verifier)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.preflight(
            run_code,
            payload.model_dump(mode="json"),
            room_verifier=authority.attest_fresh_blank_room,
        )


@router.post(
    "/runs/{run_code}/draft-execution-jobs",
    response_model=DraftExecutionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_draft_execution_job(
    run_code: str,
    payload: DraftExecutionJobCreate,
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
    authority: Annotated[MaituAuthorityVerifier, Depends(get_maitu_authority_verifier)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.create_draft_execution_job(
            run_code,
            payload.model_dump(mode="json"),
            room_verifier=authority.attest_fresh_blank_room,
        )


# Selected video analysis and manual Gemini review --------------------


@router.get("/runs/{run_code}/video-analyses", response_model=list[VideoAnalysisRead])
def list_video_analyses(
    run_code: str,
    service: Annotated[
        MaterialAnalysisWorkbenchService,
        Depends(get_material_analysis_workbench_service),
    ],
) -> list[dict[str, Any]]:
    with _workbench_errors():
        rows = service.list_video_analyses(run_code)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workbench run not found")
    return rows


@router.post(
    "/runs/{run_code}/video-analyses/{analysis_code}/gemini-backfill",
    response_model=VideoAnalysisRead,
)
def submit_gemini_backfill(
    run_code: str,
    analysis_code: str,
    payload: GeminiBackfillCreate,
    service: Annotated[
        MaterialAnalysisWorkbenchService,
        Depends(get_material_analysis_workbench_service),
    ],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            service.submit_gemini_backfill(
                run_code,
                analysis_code,
                payload.model_dump(mode="json"),
            ),
            "Video analysis not found",
        )


@router.get("/runs/{run_code}/analysis-conflicts", response_model=list[AnalysisConflictRead])
def list_analysis_conflicts(
    run_code: str,
    service: Annotated[
        MaterialAnalysisWorkbenchService,
        Depends(get_material_analysis_workbench_service),
    ],
) -> list[dict[str, Any]]:
    rows = service.list_analysis_conflicts(run_code)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workbench run not found")
    return rows


@router.patch(
    "/runs/{run_code}/analysis-conflicts/{conflict_code}",
    response_model=AnalysisConflictRead,
)
def resolve_analysis_conflict(
    run_code: str,
    conflict_code: str,
    payload: AnalysisConflictResolve,
    service: Annotated[
        MaterialAnalysisWorkbenchService,
        Depends(get_material_analysis_workbench_service),
    ],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            service.resolve_analysis_conflict(
                run_code,
                conflict_code,
                payload.model_dump(mode="json"),
            ),
            "Analysis conflict not found",
        )


# Material analysis worker protocol ----------------------------------


@router.post("/video-analysis-jobs/claim-next", response_model=VideoAnalysisClaimedRead | None)
def claim_next_video_analysis(
    payload: VideoAnalysisClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any] | Response:
    repository.synchronize_all_selected_video_analyses()
    row = repository.claim_video_analysis(worker_id, payload.lease_seconds)
    return row if row is not None else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/video-analysis-jobs/{analysis_code}", response_model=VideoAnalysisRead)
def get_video_analysis(
    analysis_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    return _found(repository.get_video_analysis(analysis_code), "Video analysis not found")


@router.post("/video-analysis-jobs/{analysis_code}/claim", response_model=VideoAnalysisClaimedRead)
def claim_video_analysis(
    analysis_code: str,
    payload: VideoAnalysisClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    row = repository.claim_video_analysis(
        worker_id,
        payload.lease_seconds,
        analysis_code=analysis_code,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Video analysis is not claimable")
    return row


@router.post("/video-analysis-jobs/{analysis_code}/heartbeat", response_model=VideoAnalysisRead)
def heartbeat_video_analysis(
    analysis_code: str,
    payload: VideoAnalysisHeartbeat,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    row = repository.heartbeat_video_analysis(
        analysis_code,
        worker_id,
        payload.lease_token,
        payload.lease_seconds,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Video analysis lease is not active")
    return row


@router.post("/video-analysis-jobs/{analysis_code}/complete", response_model=VideoAnalysisRead)
def complete_video_analysis(
    analysis_code: str,
    payload: VideoAnalysisComplete,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    service: Annotated[
        MaterialAnalysisWorkbenchService,
        Depends(get_material_analysis_workbench_service),
    ],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.complete_video_analysis(
            analysis_code,
            worker_id,
            payload.model_dump(mode="json"),
        )


@router.post("/video-analysis-jobs/{analysis_code}/fail", response_model=VideoAnalysisRead)
def fail_video_analysis(
    analysis_code: str,
    payload: VideoAnalysisFail,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return repository.fail_video_analysis(
            analysis_code,
            worker_id,
            payload.lease_token,
            error_code=payload.error_code,
            error_message=payload.error_message,
        )


@router.post("/video-analysis-jobs/{analysis_code}/retry", response_model=VideoAnalysisRead)
def retry_video_analysis(
    analysis_code: str,
    payload: VideoAnalysisRetry,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            repository.retry_video_analysis(analysis_code),
            "Video analysis not found",
        )


# Draft execution worker protocol -------------------------------------


@router.post("/draft-execution-jobs/claim-next", response_model=DraftExecutionJobClaimedRead | None)
def claim_next_draft_execution_job(
    payload: DraftExecutionClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any] | Response:
    row = repository.claim_draft_execution_job(worker_id, payload.lease_seconds)
    return row if row is not None else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/draft-execution-jobs/{execution_job_code}", response_model=DraftExecutionJobRead)
def get_draft_execution_job(
    execution_job_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    return _found(repository.get_draft_execution_job(execution_job_code), "Draft execution job not found")


@router.post("/draft-execution-jobs/{execution_job_code}/claim", response_model=DraftExecutionJobClaimedRead)
def claim_draft_execution_job(
    execution_job_code: str,
    payload: DraftExecutionClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    row = repository.claim_draft_execution_job(
        worker_id,
        payload.lease_seconds,
        execution_job_code=execution_job_code,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft execution job is not claimable")
    return row


@router.post("/draft-execution-jobs/{execution_job_code}/heartbeat", response_model=DraftExecutionJobRead)
def heartbeat_draft_execution_job(
    execution_job_code: str,
    payload: DraftExecutionHeartbeat,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    row = repository.heartbeat_draft_execution_job(
        execution_job_code,
        worker_id,
        payload.lease_token,
        payload.lease_seconds,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft execution lease is not active")
    return row


@router.post("/draft-execution-jobs/{execution_job_code}/complete", response_model=DraftExecutionJobRead)
def complete_draft_execution_job(
    execution_job_code: str,
    payload: DraftExecutionComplete,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    service: Annotated[MaituWorkbenchService, Depends(get_maitu_workbench_service)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return service.complete_draft_execution_job(
            execution_job_code,
            worker_id,
            payload.model_dump(mode="json"),
        )


@router.post("/draft-execution-jobs/{execution_job_code}/fail", response_model=DraftExecutionJobRead)
def fail_draft_execution_job(
    execution_job_code: str,
    payload: DraftExecutionFail,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return repository.fail_draft_execution_job(
            execution_job_code,
            worker_id,
            payload.lease_token,
            error_code=payload.error_code,
            error_message=payload.error_message,
        )


@router.post("/draft-execution-jobs/{execution_job_code}/retry", response_model=DraftExecutionJobRead)
def retry_draft_execution_job(
    execution_job_code: str,
    payload: DraftExecutionRetry,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    _reject_secret(payload)
    with _workbench_errors():
        return _found(
            repository.retry_draft_execution_job(execution_job_code, payload.requested_by),
            "Draft execution job not found",
        )


@router.post("/draft-execution-jobs/{execution_job_code}/cancel", response_model=DraftExecutionJobRead)
def cancel_draft_execution_job(
    execution_job_code: str,
    repository: Annotated[MaituWorkbenchRepository, Depends(get_maitu_workbench_repository)],
) -> dict[str, Any]:
    with _workbench_errors():
        return _found(
            repository.cancel_draft_execution_job(execution_job_code),
            "Draft execution job not found",
        )
