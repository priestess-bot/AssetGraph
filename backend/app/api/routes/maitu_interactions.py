from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg import Connection

from app.api.auth import reject_maitu_durable_secret, require_maitu_script_layout_worker
from app.core.database import get_db
from app.repositories.maitu_interactions import (
    MaituAccountMismatchError,
    MaituInteractionConflictError,
    MaituInteractionLeaseError,
    MaituInteractionsRepository,
)
from app.schemas.maitu_interactions import (
    AnalysisDashboardRead,
    AnalysisSummaryRead,
    BusinessIntent,
    InteractionBatchWrite,
    InteractionForm,
    InteractionPage,
    InteractionSourceRead,
    InteractionTopicPage,
    LiveSessionPage,
    LiveSessionRead,
    PlatformSummary,
    QualityGrade,
    SyncCatalogResult,
    SyncCatalogWrite,
    SyncRunComplete,
    SyncRunClaimRead,
    SyncRunCreate,
    SyncRunFail,
    SyncRunRead,
    WorkerClaim,
    WorkerHeartbeat,
)
from app.services.maitu_interactions import (
    BUSINESS_INTENTS,
    BUSINESS_INTENT_LABELS,
    interaction_analysis_configured,
    interaction_analyzer_version,
    prepare_interaction_for_storage,
)


router = APIRouter(prefix="/maitu/interactions", tags=["maitu-interactions"])

_PROTOCOL_FIELDS = {
    "lease_token",
    "external_interaction_id",
    "request_id",
    "source_payload",
    "source_fingerprint",
    "analysis_input_fingerprint",
}


def repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> MaituInteractionsRepository:
    return MaituInteractionsRepository(connection)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MaituInteractionLeaseError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, MaituAccountMismatchError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, MaituInteractionConflictError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Interaction operation failed")


@router.get("/source", response_model=InteractionSourceRead)
def get_source(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    source = store.get_source() or store.ensure_source()
    return {**source, "analysis_configured": interaction_analysis_configured(store.connection)}


@router.post(
    "/sync-runs",
    response_model=SyncRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_sync_run(
    payload: SyncRunCreate,
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    return store.create_sync_run(
        sync_mode=payload.sync_mode,
        target_external_session_id=payload.target_external_session_id,
        requested_by=payload.requested_by,
    )


@router.get("/sync-runs", response_model=list[SyncRunRead])
def list_sync_runs(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return store.list_sync_runs(limit=limit, offset=offset)


@router.get("/platforms", response_model=list[PlatformSummary])
def list_platforms(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> list[dict[str, Any]]:
    return store.list_platforms()


@router.get("/sessions", response_model=LiveSessionPage)
def list_sessions(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
    platform_id: Annotated[int | None, Query(ge=1)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return store.list_sessions(
        platform_id=platform_id,
        search=search.strip() if search else None,
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/{external_session_id}", response_model=LiveSessionRead)
def get_session(
    external_session_id: int,
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    session = store.get_session(external_session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live session not found")
    return session


@router.get("/sessions/{external_session_id}/items", response_model=InteractionPage)
def list_session_interactions(
    external_session_id: int,
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
    include_arrivals: bool = False,
    answered: bool | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return store.list_interactions(
        analyzer_version=interaction_analyzer_version(),
        external_session_id=external_session_id,
        platform_id=None,
        include_arrivals=include_arrivals,
        answered=answered,
        interaction_form=None,
        business_intent=None,
        overall_grade=None,
        search=search.strip() if search else None,
        limit=limit,
        offset=offset,
    )


@router.get("/analysis/summary", response_model=AnalysisSummaryRead)
def get_analysis_summary(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    analyzer_version = interaction_analyzer_version()
    return {
        "analyzer_version": analyzer_version,
        "analysis_configured": interaction_analysis_configured(store.connection),
        **store.analysis_summary(analyzer_version),
    }


@router.get("/analysis/dashboard", response_model=AnalysisDashboardRead)
def get_analysis_dashboard(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
    platform_id: Annotated[int | None, Query(ge=1)] = None,
    external_session_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    analyzer_version = interaction_analyzer_version()
    dashboard = store.analysis_dashboard(
        analyzer_version,
        platform_id=platform_id,
        external_session_id=external_session_id,
    )
    by_intent = {row["business_intent"]: row for row in dashboard.pop("intents")}
    intents = []
    for business_intent in BUSINESS_INTENTS:
        row = by_intent.get(business_intent) or {
            "business_intent": business_intent,
            "total": 0,
            "answered": 0,
            "unanswered": 0,
            "good": 0,
            "fair": 0,
            "poor": 0,
        }
        intents.append(
            {
                **row,
                "label": BUSINESS_INTENT_LABELS[business_intent],
                "answer_rate": row["answered"] / row["total"] if row["total"] else 0.0,
            }
        )
    return {
        "analyzer_version": analyzer_version,
        "analysis_configured": interaction_analysis_configured(store.connection),
        **dashboard,
        "intents": intents,
    }


@router.get("/analysis/topics", response_model=InteractionTopicPage)
def list_analysis_topics(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
    business_intent: BusinessIntent | None = None,
    platform_id: Annotated[int | None, Query(ge=1)] = None,
    external_session_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    result = store.list_topics(
        interaction_analyzer_version(),
        business_intent=business_intent,
        platform_id=platform_id,
        external_session_id=external_session_id,
        limit=limit,
        offset=offset,
    )
    for item in result["items"]:
        item["answer_rate"] = item["answered"] / item["total"] if item["total"] else 0.0
    return result


@router.get("/analysis/items", response_model=InteractionPage)
def list_analysis_items(
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
    platform_id: Annotated[int | None, Query(ge=1)] = None,
    external_session_id: Annotated[int | None, Query(ge=1)] = None,
    answered: bool | None = None,
    interaction_form: InteractionForm | None = None,
    business_intent: BusinessIntent | None = None,
    overall_grade: QualityGrade | None = None,
    topic_code: Annotated[str | None, Query(max_length=80)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return store.list_interactions(
        analyzer_version=interaction_analyzer_version(),
        external_session_id=external_session_id,
        platform_id=platform_id,
        include_arrivals=False,
        answered=answered,
        interaction_form=interaction_form,
        business_intent=business_intent,
        overall_grade=overall_grade,
        search=search.strip() if search else None,
        limit=limit,
        offset=offset,
        topic_code=topic_code.strip() if topic_code else None,
    )


@router.post("/sync-jobs/claim-next", response_model=SyncRunClaimRead | None)
def claim_next_sync_job(
    payload: WorkerClaim,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any] | Response:
    claimed = store.claim_next_sync_job(worker_id, payload.lease_seconds)
    return claimed if claimed is not None else Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync-jobs/{run_code}/heartbeat", response_model=SyncRunRead)
def heartbeat_sync_job(
    run_code: str,
    payload: WorkerHeartbeat,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    try:
        return store.heartbeat_sync_job(
            run_code,
            worker_id,
            payload.lease_token,
            payload.lease_seconds,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/sync-jobs/{run_code}/catalog", response_model=SyncCatalogResult)
def write_sync_catalog(
    run_code: str,
    payload: SyncCatalogWrite,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    reject_maitu_durable_secret(payload, protocol_fields=_PROTOCOL_FIELDS)
    try:
        return store.write_sync_catalog(
            run_code,
            worker_id,
            payload.lease_token,
            payload.model_dump(mode="python", exclude={"lease_token"}),
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/sync-jobs/{run_code}/interaction-batches")
def write_interaction_batch(
    run_code: str,
    payload: InteractionBatchWrite,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    reject_maitu_durable_secret(payload, protocol_fields=_PROTOCOL_FIELDS)
    prepared = [
        prepare_interaction_for_storage(item.model_dump(mode="python"))
        for item in payload.items
    ]
    durable = payload.model_dump(mode="python", exclude={"lease_token", "items"})
    durable["items"] = prepared
    try:
        return store.write_interaction_batch(
            run_code,
            worker_id,
            payload.lease_token,
            durable,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/sync-jobs/{run_code}/complete", response_model=SyncRunRead)
def complete_sync_job(
    run_code: str,
    payload: SyncRunComplete,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    reject_maitu_durable_secret(payload, protocol_fields=_PROTOCOL_FIELDS)
    try:
        return store.complete_sync_job(
            run_code,
            worker_id,
            payload.lease_token,
            summary=payload.summary,
            partial=payload.partial,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/sync-jobs/{run_code}/fail", response_model=SyncRunRead)
def fail_sync_job(
    run_code: str,
    payload: SyncRunFail,
    worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    store: Annotated[MaituInteractionsRepository, Depends(repository)],
) -> dict[str, Any]:
    reject_maitu_durable_secret(payload, protocol_fields=_PROTOCOL_FIELDS)
    try:
        return store.fail_sync_job(
            run_code,
            worker_id,
            payload.lease_token,
            error_code=payload.error_code,
            error_message=payload.error_message,
            retry_kind=payload.retry_kind,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
