from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.video_segments import VideoSegmentRepository
from app.schemas.video_segments import VideoSegmentCreate, VideoSegmentRead

router = APIRouter(prefix="/video-segments", tags=["video-segments"])


def get_video_segment_repository(connection: Annotated[Connection, Depends(get_db)]) -> VideoSegmentRepository:
    return VideoSegmentRepository(connection)


@router.post("", response_model=VideoSegmentRead, status_code=status.HTTP_201_CREATED)
def create_video_segment(
    payload: VideoSegmentCreate,
    repository: Annotated[VideoSegmentRepository, Depends(get_video_segment_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[VideoSegmentRead])
def list_video_segments(
    repository: Annotated[VideoSegmentRepository, Depends(get_video_segment_repository)],
    live_code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(live_code=live_code, limit=limit, offset=offset)


@router.get("/{segment_code}", response_model=VideoSegmentRead)
def get_video_segment(
    segment_code: str,
    repository: Annotated[VideoSegmentRepository, Depends(get_video_segment_repository)],
) -> dict:
    row = repository.get_by_code(segment_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video segment not found")
    return row
