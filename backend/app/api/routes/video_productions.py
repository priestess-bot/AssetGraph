from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from psycopg import Connection

from app.core.config import settings
from app.core.database import get_db
from app.repositories.video_productions import (
    VideoProductionRepository,
    VideoProductionRetryConflictError,
)
from app.schemas.video_productions import (
    VIDEO_PRODUCTION_ARTIFACT_KEYS,
    VideoProductionCreate,
    VideoProductionJobRead,
    VideoProductionJobStatus,
    VideoProductionJobSummary,
)

router = APIRouter(prefix="/video-productions", tags=["video-productions"])
_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
_STREAM_CHUNK_SIZE = 1024 * 1024


def get_video_production_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> VideoProductionRepository:
    return VideoProductionRepository(connection)


@router.post("", response_model=VideoProductionJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_video_production(
    payload: VideoProductionCreate,
    repository: Annotated[VideoProductionRepository, Depends(get_video_production_repository)],
) -> dict[str, Any]:
    return _add_artifact_urls(repository.create(payload.model_dump()))


@router.get("", response_model=list[VideoProductionJobSummary])
def list_video_productions(
    repository: Annotated[VideoProductionRepository, Depends(get_video_production_repository)],
    status_filter: Annotated[VideoProductionJobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return repository.list(status=status_filter, limit=limit, offset=offset)


@router.get("/{job_code}", response_model=VideoProductionJobRead)
def get_video_production(
    job_code: str,
    repository: Annotated[VideoProductionRepository, Depends(get_video_production_repository)],
) -> dict[str, Any]:
    row = repository.get_by_code(job_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production job not found")
    return _add_artifact_urls(row)


@router.post("/{job_code}/retry", response_model=VideoProductionJobRead, status_code=status.HTTP_202_ACCEPTED)
def retry_video_production(
    job_code: str,
    repository: Annotated[VideoProductionRepository, Depends(get_video_production_repository)],
) -> dict[str, Any]:
    try:
        row = repository.retry(job_code)
    except VideoProductionRetryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production job not found")
    return _add_artifact_urls(row)


@router.get("/{job_code}/artifacts/{artifact_key}")
def get_video_production_artifact(
    job_code: str,
    artifact_key: str,
    repository: Annotated[VideoProductionRepository, Depends(get_video_production_repository)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    if artifact_key not in VIDEO_PRODUCTION_ARTIFACT_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production artifact not found")
    artifact = repository.get_artifact(job_code, artifact_key)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production artifact not found")

    root = settings.video_production_root.expanduser().resolve()
    relative_path = PurePosixPath(str(artifact["relative_path"]).replace("\\", "/"))
    if (
        len(relative_path.parts) < 3
        or relative_path.parts[0] != job_code
        or not _is_attempt_component(relative_path.parts[1])
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production artifact not found")
    job_root = (root / job_code).resolve()
    candidate = (root / Path(*relative_path.parts)).resolve()
    if not job_root.is_relative_to(root) or not candidate.is_relative_to(job_root):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production artifact not found")
    if not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video production artifact file not found")

    file_size = candidate.stat().st_size
    recorded_size = artifact.get("file_size")
    if recorded_size is not None and recorded_size != file_size:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Video production artifact file changed")
    recorded_checksum = str(artifact.get("checksum_sha256") or "").strip()
    if recorded_checksum and _sha256_file(candidate) != recorded_checksum:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Video production artifact file changed")
    media_type = artifact.get("mime_type") or mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store"}
    if range_header is None:
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            _file_chunks(candidate, 0, file_size),
            media_type=media_type,
            headers=headers,
        )

    byte_range = _parse_range(range_header, file_size)
    if byte_range is None:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
        )
    start, end = byte_range
    content_length = end - start + 1
    headers.update(
        {
            "Content-Length": str(content_length),
            "Content-Range": f"bytes {start}-{end}/{file_size}",
        }
    )
    return StreamingResponse(
        _file_chunks(candidate, start, content_length),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


def _add_artifact_urls(job: dict[str, Any]) -> dict[str, Any]:
    response = dict(job)
    response["artifacts"] = []
    for artifact in job.get("artifacts") or []:
        item = dict(artifact)
        item["download_url"] = (
            f"{settings.api_prefix}/video-productions/{job['job_code']}"
            f"/artifacts/{artifact['artifact_key']}"
        )
        response["artifacts"].append(item)
    return response


def _parse_range(value: str, file_size: int) -> tuple[int, int] | None:
    match = _RANGE_PATTERN.fullmatch(value.strip())
    if match is None or file_size <= 0:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return None
        start = max(file_size - suffix_length, 0)
        return start, file_size - 1
    start = int(start_text)
    if start >= file_size:
        return None
    end = int(end_text) if end_text else file_size - 1
    if end < start:
        return None
    return start, min(end, file_size - 1)


def _is_attempt_component(value: str) -> bool:
    attempt_number = value.removeprefix("attempt-")
    return value != attempt_number and attempt_number.isdigit() and int(attempt_number) >= 1


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
            chunk = file.read(min(_STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
