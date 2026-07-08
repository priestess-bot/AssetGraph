from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.lives import LiveSessionRepository
from app.schemas.lives import LiveAssetLinkCreate, LiveAssetSummary, LiveAssetsResponse, LiveSessionCreate, LiveSessionRead

router = APIRouter(prefix="/lives", tags=["lives"])


def get_live_session_repository(connection: Annotated[Connection, Depends(get_db)]) -> LiveSessionRepository:
    return LiveSessionRepository(connection)


@router.post("", response_model=LiveSessionRead, status_code=status.HTTP_201_CREATED)
def create_live_session(
    payload: LiveSessionCreate,
    repository: Annotated[LiveSessionRepository, Depends(get_live_session_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[LiveSessionRead])
def list_live_sessions(
    repository: Annotated[LiveSessionRepository, Depends(get_live_session_repository)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(limit=limit, offset=offset)


@router.get("/{live_code}", response_model=LiveSessionRead)
def get_live_session(
    live_code: str,
    repository: Annotated[LiveSessionRepository, Depends(get_live_session_repository)],
) -> dict:
    row = repository.get_by_code(live_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live session not found")
    return row


@router.post("/{live_code}/assets", response_model=LiveAssetSummary, status_code=status.HTTP_201_CREATED)
def link_live_asset(
    live_code: str,
    payload: LiveAssetLinkCreate,
    repository: Annotated[LiveSessionRepository, Depends(get_live_session_repository)],
) -> dict:
    row = repository.link_asset(live_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live session or asset not found")
    return row


@router.get("/{live_code}/assets", response_model=LiveAssetsResponse)
def list_live_assets(
    live_code: str,
    repository: Annotated[LiveSessionRepository, Depends(get_live_session_repository)],
) -> LiveAssetsResponse:
    return LiveAssetsResponse(live_code=live_code, assets=repository.list_assets(live_code))
