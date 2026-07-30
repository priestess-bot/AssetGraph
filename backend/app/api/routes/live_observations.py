from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from psycopg import Connection, IntegrityError

from app.api.auth import require_maitu_script_layout_worker
from app.core.config import settings
from app.core.database import get_db
from app.domain.contracts import DataClassification
from app.domain.errors import (
    DomainAuthorizationError,
    DomainUnavailableError,
    DomainValidationError,
)
from app.repositories.evidence import EvidenceRepository
from app.repositories.live_observations import LiveObservationRepository
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.schemas.live_observations import (
    AnalysisRunCompletion,
    AnalysisRunCreate,
    AnalysisRunRead,
    AnalysisRetryRequest,
    CaptureChannelCreate,
    CaptureChannelRead,
    CaptureChunkFinalize,
    CaptureChunkRead,
    CaptureRecordingUploadRead,
    CaptureSessionCreate,
    CaptureSessionFinish,
    CaptureSessionRead,
    CaptureSessionStatus,
    CaptureSessionSummary,
    ClaimedAnalysisRun,
    ClaimedClipJob,
    ClipJobCompletion,
    ClipJobCreate,
    ClipJobRead,
    InteractionSummary,
    LiveResearchOverview,
    OperatorAnalysisRetryRequest,
    ProviderEvidenceArtifactRead,
    ProviderStrategyAuthorizationRead,
    ProviderStrategyAuthorizationRequest,
    RawEventBatchRead,
    RawEventBatchRegistration,
    RetentionCandidate,
    RetentionClaimRequest,
    RetentionCompleteRequest,
    RoomTemplateCreate,
    RoomTemplateArchiveRequest,
    RoomTemplatePublicationRequest,
    RoomTemplateProjectionRead,
    RoomTemplateRead,
    RoomTemplateRevisionCreate,
    RoomTemplateRevisionRead,
    RoomTemplateSummary,
    SchedulerClaimRead,
    SchedulerClaimRequest,
    SchedulerHeartbeatRequest,
    SchedulerReleaseRequest,
    TimelineSpanCreate,
    TimelineSpanRead,
    WatchTargetCreate,
    WatchTargetRead,
    WatchTargetStatus,
    WatchTargetUpdate,
    WorkClaimRequest,
    WorkFailure,
    WorkHeartbeatRequest,
    WorkStatus,
)
from app.services.artifacts import ContentAddressedArtifactService
from app.services.live_observations import (
    LiveObservationConflictError,
    LiveObservationNotFoundError,
    LiveObservationService,
)
from app.services.object_storage import MinioObjectStorage
from app.services.processor_credentials import ExternalProcessorService
from app.services.recording_upload import RecordingUploadError, store_recording_upload
from app.services.providers import (
    ArtifactProviderEvidenceSink,
    ModelCapability,
    ProviderInvocationEvidenceRecord,
)


router = APIRouter(prefix="/live-research", tags=["live-research"])
_LIVE_RESEARCH_ROOT = settings.live_research_root
_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
_STREAM_CHUNK_SIZE = 1024 * 1024


def get_live_observation_service(
    connection: Annotated[Connection, Depends(get_db)],
) -> LiveObservationService:
    return LiveObservationService(LiveObservationRepository(connection))


Service = Annotated[LiveObservationService, Depends(get_live_observation_service)]
WorkerIdentity = Annotated[str, Depends(require_maitu_script_layout_worker)]


_LIVE_EXTERNAL_STRATEGIES: dict[str, tuple[str, ModelCapability, str, str | None]] = {
    "live.asr.zh.v2": (
        "asr",
        ModelCapability.SPEECH_TO_TEXT,
        settings.openai_processor_code,
        settings.openai_processing_region,
    ),
    "live.ocr.v2": (
        "ocr",
        ModelCapability.OPTICAL_CHARACTER_RECOGNITION,
        settings.openai_processor_code,
        settings.openai_processing_region,
    ),
    "live.layout-inference.v2": (
        "layout_inference",
        ModelCapability.IMAGE_UNDERSTANDING,
        settings.openai_processor_code,
        settings.openai_processing_region,
    ),
    "live.template-aggregation.v2": (
        "template_aggregation",
        ModelCapability.STRUCTURED_GENERATION,
        settings.deepseek_processor_code,
        settings.deepseek_processing_region,
    ),
}


def get_provider_evidence_sink(
    connection: Annotated[Connection, Depends(get_db)],
) -> ArtifactProviderEvidenceSink:
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return ArtifactProviderEvidenceSink(
        ContentAddressedArtifactService(
            EvidenceRepository(connection),
            storage,
            bucket_name=settings.minio_bucket,
        ),
        producer_code="live-research-analysis-worker",
    )


def _provider_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DomainAuthorizationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.as_dict())
    if isinstance(exc, DomainValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.as_dict(),
        )
    if isinstance(exc, DomainUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.as_dict(),
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Provider evidence infrastructure is unavailable",
    )
@router.get("/overview", response_model=LiveResearchOverview)
def overview(service: Service) -> dict[str, int]:
    return service.overview()


@router.post(
    "/watch-targets", response_model=WatchTargetRead, status_code=status.HTTP_201_CREATED
)
def create_watch_target(payload: WatchTargetCreate, service: Service) -> dict[str, Any]:
    try:
        return service.create_watch_target(payload)
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Watch target already exists") from exc


@router.get("/watch-targets", response_model=list[WatchTargetRead])
def list_watch_targets(
    service: Service,
    status_filter: Annotated[WatchTargetStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return service.list_watch_targets(
        status=status_filter.value if status_filter else None, limit=limit, offset=offset
    )


@router.get("/watch-targets/{target_code}", response_model=WatchTargetRead)
def get_watch_target(target_code: str, service: Service) -> dict[str, Any]:
    return _call(service.get_watch_target, target_code)


@router.patch("/watch-targets/{target_code}", response_model=WatchTargetRead)
def update_watch_target(
    target_code: str, payload: WatchTargetUpdate, service: Service
) -> dict[str, Any]:
    return _call(service.update_watch_target, target_code, payload)


@router.get("/capture-sessions", response_model=list[CaptureSessionSummary])
def list_capture_sessions(
    service: Service,
    target_code: Annotated[str | None, Query(max_length=64)] = None,
    status_filter: Annotated[CaptureSessionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return service.list_capture_sessions(
        target_code=target_code,
        status=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/capture-sessions/uploads",
    response_model=CaptureRecordingUploadRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_capture_recording(
    service: Service,
    source_room_id: Annotated[
        str,
        Form(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    ],
    source_room_title: Annotated[str, Form(min_length=1, max_length=255)],
    file: Annotated[UploadFile, File(...)],
) -> dict[str, Any]:
    try:
        stored = store_recording_upload(
            file.file,
            filename=file.filename or "recording.mp4",
            content_type=file.content_type,
            root=settings.live_research_root,
            max_bytes=settings.live_research_upload_max_bytes,
        )
    except RecordingUploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    observed_ended_at = datetime.now(UTC)
    observed_started_at = observed_ended_at - timedelta(seconds=stored.duration_seconds)
    session = _call(
        service.import_recording,
        {
            "source_room_id": source_room_id,
            "source_room_title": source_room_title,
            "file_name": stored.original_name,
            "relative_path": stored.relative_path,
            "file_size": stored.file_size,
            "checksum_sha256": stored.checksum_sha256,
            "content_type": stored.content_type,
            "container_format": stored.container_format,
            "duration_seconds": stored.duration_seconds,
            "media_probe": stored.media_probe,
            "observed_started_at": observed_started_at,
            "observed_ended_at": observed_ended_at,
        },
    )
    return {
        "session_code": session["session_code"],
        "target_code": session["target_code"],
        "source_room_id": source_room_id,
        "source_room_title": source_room_title,
        "file_name": stored.original_name,
        "file_size": stored.file_size,
        "checksum_sha256": stored.checksum_sha256,
        "duration_seconds": stored.duration_seconds,
        "upload_status": "stored",
        "analysis_status": "queued",
        "queued_analysis_types": ["frame_sampling", "asr", "ocr", "layout_inference"],
        "created_at": session["created_at"],
    }


@router.get("/capture-sessions/{session_code}", response_model=CaptureSessionRead)
def get_capture_session(session_code: str, service: Service) -> dict[str, Any]:
    return _add_session_media_urls(_call(service.get_capture_session, session_code))


@router.get("/capture-sessions/{session_code}/chunks/{chunk_code}/media")
def get_capture_chunk_media(
    session_code: str,
    chunk_code: str,
    service: Service,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    session = _call(service.get_capture_session, session_code)
    chunk = next(
        (item for item in session.get("chunks") or [] if item.get("chunk_code") == chunk_code),
        None,
    )
    if chunk is None or chunk.get("status") not in {"finalized", "delete_candidate"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture chunk not found")
    root = _LIVE_RESEARCH_ROOT.expanduser().resolve()
    relative = PurePosixPath(str(chunk["relative_path"]).replace("\\", "/"))
    candidate = (root / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture chunk file not found")
    file_size = candidate.stat().st_size
    if int(chunk.get("file_size") or -1) != file_size:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Capture chunk file changed")
    checksum = str(chunk.get("checksum_sha256") or "")
    if not checksum or _sha256_file(candidate) != checksum:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Capture chunk file changed")
    media_type = mimetypes.guess_type(candidate.name)[0] or "video/mp2t"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
    if range_header is None:
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(_file_chunks(candidate, 0, file_size), media_type=media_type, headers=headers)
    byte_range = _parse_range(range_header, file_size)
    if byte_range is None:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
        )
    start, end = byte_range
    headers.update(
        {
            "Content-Length": str(end - start + 1),
            "Content-Range": f"bytes {start}-{end}/{file_size}",
        }
    )
    return StreamingResponse(
        _file_chunks(candidate, start, end - start + 1),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


@router.get(
    "/capture-sessions/{session_code}/timeline", response_model=list[TimelineSpanRead]
)
def get_capture_timeline(session_code: str, service: Service) -> list[dict[str, Any]]:
    return _call(service.get_timeline, session_code)


@router.get(
    "/capture-sessions/{session_code}/interaction-summary",
    response_model=InteractionSummary,
)
def get_interaction_summary(
    session_code: str,
    service: Service,
    bucket_seconds: Annotated[int, Query(ge=30, le=3600)] = 60,
) -> dict[str, Any]:
    return _call(service.get_interaction_summary, session_code, bucket_seconds)


@router.post(
    "/capture-sessions/{session_code}/clips",
    response_model=ClipJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_clip_job(
    session_code: str, payload: ClipJobCreate, service: Service
) -> dict[str, Any]:
    return _call(service.create_clip_job, session_code, payload)


@router.get("/clip-jobs", response_model=list[ClipJobRead])
def list_clip_jobs(
    service: Service,
    session_code: Annotated[str | None, Query(max_length=64)] = None,
    status_filter: Annotated[WorkStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return service.list_clip_jobs(
        session_code=session_code,
        status=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/capture-sessions/{session_code}/analysis-runs",
    response_model=AnalysisRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_run(
    session_code: str, payload: AnalysisRunCreate, service: Service
) -> dict[str, Any]:
    return _call(service.create_analysis_run, session_code, payload)


@router.get("/analysis-runs", response_model=list[AnalysisRunRead])
def list_analysis_runs(
    service: Service,
    session_code: Annotated[str | None, Query(max_length=64)] = None,
    analysis_type: Annotated[str | None, Query(max_length=32)] = None,
    status_filter: Annotated[WorkStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return service.list_analysis_runs(
        session_code=session_code,
        analysis_type=analysis_type,
        status=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )


@router.post("/analysis-runs/{run_code}/retry", response_model=AnalysisRunRead)
def retry_analysis_run_as_operator(
    run_code: str,
    payload: OperatorAnalysisRetryRequest,
    service: Service,
) -> dict[str, Any]:
    return _call(service.retry_analysis_run_as_operator, run_code, payload.reason)


@router.post(
    "/room-templates", response_model=RoomTemplateRead, status_code=status.HTTP_201_CREATED
)
def create_room_template(payload: RoomTemplateCreate, service: Service) -> dict[str, Any]:
    return _call(service.create_room_template, payload)


@router.get("/room-templates", response_model=list[RoomTemplateSummary])
def list_room_templates(
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return service.list_room_templates(limit=limit, offset=offset)


@router.get("/room-templates/{template_code}", response_model=RoomTemplateRead)
def get_room_template(template_code: str, service: Service) -> dict[str, Any]:
    return _call(service.get_room_template, template_code)


@router.post("/room-templates/{template_code}/archive", response_model=RoomTemplateRead)
def archive_room_template(
    template_code: str,
    payload: RoomTemplateArchiveRequest,
    service: Service,
) -> dict[str, Any]:
    return _call(service.archive_room_template, template_code, payload)


@router.post(
    "/room-templates/{template_code}/revisions",
    response_model=RoomTemplateRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_room_template_revision(
    template_code: str, payload: RoomTemplateRevisionCreate, service: Service
) -> dict[str, Any]:
    return _call(service.create_room_template_revision, template_code, payload)


@router.post(
    "/room-templates/{template_code}/revisions/{revision_number}/publish",
    response_model=RoomTemplateProjectionRead,
)
def publish_room_template_revision(
    template_code: str,
    revision_number: int,
    payload: RoomTemplatePublicationRequest,
    service: Service,
) -> dict[str, Any]:
    return _call(
        service.publish_room_template_revision,
        template_code,
        revision_number,
        payload,
    )


@router.get(
    "/room-templates/{template_code}/projection", response_model=RoomTemplateProjectionRead
)
def get_room_template_projection(template_code: str, service: Service) -> dict[str, Any]:
    return _call(service.get_room_template_projection, template_code)


# Worker-only mutation surface. Raw event contents are deliberately absent: only
# 0600 gzip batch metadata crosses this API boundary.
@router.post("/worker/watch-target-claims", response_model=SchedulerClaimRead | None)
def claim_watch_target(
    payload: SchedulerClaimRequest, service: Service, authenticated_worker_id: WorkerIdentity
) -> dict[str, Any] | None:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return service.claim_watch_target(payload)


@router.post(
    "/worker/watch-targets/{target_code}/heartbeat", response_model=SchedulerClaimRead
)
def heartbeat_watch_target(
    target_code: str,
    payload: SchedulerHeartbeatRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.heartbeat_watch_target, target_code, payload)


@router.post(
    "/worker/watch-targets/{target_code}/release", response_model=WatchTargetRead
)
def release_watch_target(
    target_code: str,
    payload: SchedulerReleaseRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.release_watch_target, target_code, payload)


@router.post(
    "/worker/capture-sessions",
    response_model=CaptureSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def worker_create_capture_session(
    payload: CaptureSessionCreate,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _add_session_media_urls(_call(service.create_capture_session, payload))


@router.post(
    "/worker/capture-sessions/{session_code}/channels",
    response_model=CaptureChannelRead,
    status_code=status.HTTP_201_CREATED,
)
def worker_add_capture_channel(
    session_code: str,
    payload: CaptureChannelCreate,
    service: Service,
    _authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    return _call(service.add_channel, session_code, payload)


@router.post(
    "/worker/capture-sessions/{session_code}/chunks",
    response_model=CaptureChunkRead,
    status_code=status.HTTP_201_CREATED,
)
def worker_finalize_capture_chunk(
    session_code: str,
    payload: CaptureChunkFinalize,
    service: Service,
    _authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    return _call(service.finalize_chunk, session_code, payload)


@router.post(
    "/worker/capture-sessions/{session_code}/raw-event-batches",
    response_model=RawEventBatchRead,
    status_code=status.HTTP_201_CREATED,
)
def worker_register_raw_event_batch(
    session_code: str,
    payload: RawEventBatchRegistration,
    service: Service,
    _authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    return _call(service.register_event_batch, session_code, payload)


@router.post(
    "/worker/capture-sessions/{session_code}/timeline-spans",
    response_model=TimelineSpanRead,
    status_code=status.HTTP_201_CREATED,
)
def worker_append_timeline(
    session_code: str,
    payload: TimelineSpanCreate,
    service: Service,
    _authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    return _call(service.append_timeline, session_code, payload)


@router.post(
    "/worker/capture-sessions/{session_code}/finish", response_model=CaptureSessionRead
)
def worker_finish_capture_session(
    session_code: str,
    payload: CaptureSessionFinish,
    service: Service,
    _authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    return _add_session_media_urls(_call(service.finish_capture_session, session_code, payload))


@router.post("/worker/clip-job-claims", response_model=ClaimedClipJob | None)
def worker_claim_clip_job(
    payload: WorkClaimRequest, service: Service, authenticated_worker_id: WorkerIdentity
) -> dict[str, Any] | None:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return service.claim_clip_job(payload)


@router.post("/worker/clip-jobs/{job_code}/complete", response_model=ClipJobRead)
def worker_complete_clip_job(
    job_code: str,
    payload: ClipJobCompletion,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.complete_clip_job, job_code, payload)


@router.post("/worker/clip-jobs/{job_code}/heartbeat", response_model=ClipJobRead)
def worker_heartbeat_clip_job(
    job_code: str,
    payload: WorkHeartbeatRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.heartbeat_clip_job, job_code, payload)


@router.post("/worker/clip-jobs/{job_code}/fail", response_model=ClipJobRead)
def worker_fail_clip_job(
    job_code: str,
    payload: WorkFailure,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.fail_clip_job, job_code, payload)


@router.post(
    "/worker/provider-strategy-authorizations",
    response_model=ProviderStrategyAuthorizationRead,
)
def worker_authorize_provider_strategy(
    payload: ProviderStrategyAuthorizationRequest,
    authenticated_worker_id: WorkerIdentity,
    connection: Annotated[Connection, Depends(get_db)],
) -> dict[str, str]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    binding = _LIVE_EXTERNAL_STRATEGIES.get(payload.strategy_revision)
    if binding is None or binding[0] != payload.analysis_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis type is not registered for the requested strategy revision",
        )
    _analysis_type, _capability, processor_code, processing_region = binding
    if not processing_region:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External processor region is not configured for this strategy",
        )
    try:
        authorized = ExternalProcessorService(
            PrivacyGovernanceRepository(connection)
        ).prepare_payload(
            processor_code=processor_code,
            purpose="model_inference",
            region=processing_region,
            data_classification=DataClassification.CONFIDENTIAL,
            payload={
                "strategy_revision": payload.strategy_revision,
                "analysis_type": payload.analysis_type,
                "input_fingerprint": payload.input_fingerprint,
            },
            principal_id=payload.worker_id,
        )
    except (DomainAuthorizationError, DomainUnavailableError, DomainValidationError) as exc:
        raise _provider_http_error(exc) from exc
    return {
        "strategy_revision": payload.strategy_revision,
        "processor_call_audit_code": authorized.audit_code,
    }


@router.post(
    "/worker/provider-invocation-evidence",
    response_model=ProviderEvidenceArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
def worker_persist_provider_invocation_evidence(
    payload: ProviderInvocationEvidenceRecord,
    authenticated_worker_id: WorkerIdentity,
    connection: Annotated[Connection, Depends(get_db)],
    sink: Annotated[ArtifactProviderEvidenceSink, Depends(get_provider_evidence_sink)],
) -> dict[str, str]:
    binding = _LIVE_EXTERNAL_STRATEGIES.get(payload.strategy_revision)
    if binding is None or payload.capability is not binding[1]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provider evidence does not match a registered live-analysis strategy",
        )
    if not payload.processor_call_audit_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="External provider evidence requires a processor authorization audit",
        )
    audit = PrivacyGovernanceRepository(connection).get_external_processor_call(
        payload.processor_call_audit_code
    )
    if (
        audit is None
        or audit["decision"] != "allow"
        or audit["processor_code"] != binding[2]
        or audit["principal_id"] != authenticated_worker_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Provider evidence is not bound to an allowed worker processor call",
        )
    try:
        artifact_code = sink.persist_provider_invocation(payload.model_dump(mode="json"))
    except Exception as exc:
        raise _provider_http_error(exc) from exc
    return {"artifact_code": artifact_code}


@router.post("/worker/analysis-run-claims", response_model=ClaimedAnalysisRun | None)
def worker_claim_analysis_run(
    payload: WorkClaimRequest, service: Service, authenticated_worker_id: WorkerIdentity
) -> dict[str, Any] | None:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return service.claim_analysis_run(payload)


@router.post("/worker/analysis-runs/{run_code}/complete", response_model=AnalysisRunRead)
def worker_complete_analysis_run(
    run_code: str,
    payload: AnalysisRunCompletion,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.complete_analysis_run, run_code, payload)


@router.post(
    "/worker/analysis-runs/{run_code}/heartbeat", response_model=AnalysisRunRead
)
def worker_heartbeat_analysis_run(
    run_code: str,
    payload: WorkHeartbeatRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.heartbeat_analysis_run, run_code, payload)


@router.post("/worker/analysis-runs/{run_code}/fail", response_model=AnalysisRunRead)
def worker_fail_analysis_run(
    run_code: str,
    payload: WorkFailure,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.fail_analysis_run, run_code, payload)


@router.post("/worker/analysis-runs/{run_code}/retry", response_model=AnalysisRunRead)
def worker_retry_analysis_run(
    run_code: str,
    payload: AnalysisRetryRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> dict[str, Any]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return _call(service.retry_analysis_run, run_code, payload)


@router.post(
    "/worker/retention/claims", response_model=list[RetentionCandidate]
)
def worker_claim_retention(
    payload: RetentionClaimRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> list[dict[str, Any]]:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    return service.claim_retention_candidates(payload)


@router.post("/worker/retention/complete", status_code=status.HTTP_204_NO_CONTENT)
def worker_complete_retention(
    payload: RetentionCompleteRequest,
    service: Service,
    authenticated_worker_id: WorkerIdentity,
) -> Response:
    _require_worker_match(authenticated_worker_id, payload.worker_id)
    _call(service.complete_retention, payload.model_dump(mode="json"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _call(function: Any, *args: Any) -> Any:
    try:
        return function(*args)
    except LiveObservationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (LiveObservationConflictError, IntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _require_worker_match(authenticated_worker_id: str, payload_worker_id: str) -> None:
    if authenticated_worker_id != payload_worker_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated worker identity does not match request payload",
        )


def _add_session_media_urls(session: dict[str, Any]) -> dict[str, Any]:
    result = dict(session)
    def project(item: dict[str, Any], model: Any) -> dict[str, Any]:
        return {field_name: item[field_name] for field_name in model.model_fields if field_name in item}

    result["channels"] = [
        project(dict(item), CaptureChannelRead) for item in session.get("channels") or []
    ]
    result["chunks"] = []
    for chunk in session.get("chunks") or []:
        item = project(dict(chunk), CaptureChunkRead)
        if item.get("status") in {"finalized", "delete_candidate"}:
            item["media_url"] = (
                f"{settings.api_prefix}/live-research/capture-sessions/{session['session_code']}"
                f"/chunks/{item['chunk_code']}/media"
            )
        else:
            item["media_url"] = None
        result["chunks"].append(item)
    result["playback_url"] = next(
        (item["media_url"] for item in result["chunks"] if item.get("media_url")),
        None,
    )
    result["raw_event_batches"] = [
        project(dict(item), RawEventBatchRead)
        for item in session.get("raw_event_batches") or []
    ]
    result["timeline"] = [
        project(dict(item), TimelineSpanRead) for item in session.get("timeline") or []
    ]
    return result


def _parse_range(value: str, file_size: int) -> tuple[int, int] | None:
    match = _RANGE_PATTERN.fullmatch(value.strip())
    if match is None or file_size <= 0:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        suffix = int(end_text)
        if suffix <= 0:
            return None
        return max(file_size - suffix, 0), file_size - 1
    start = int(start_text)
    if start >= file_size:
        return None
    end = int(end_text) if end_text else file_size - 1
    if end < start:
        return None
    return start, min(end, file_size - 1)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_STREAM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_chunks(path: Path, start: int, content_length: int) -> Iterator[bytes]:
    remaining = content_length
    with path.open("rb") as file:
        file.seek(start)
        while remaining > 0:
            chunk = file.read(min(remaining, _STREAM_CHUNK_SIZE))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    ProviderEvidenceArtifactRead,
    ProviderStrategyAuthorizationRead,
    ProviderStrategyAuthorizationRequest,
