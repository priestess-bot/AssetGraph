from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetCreate, AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])


def get_asset_repository(connection: Annotated[Connection, Depends(get_db)]) -> AssetRepository:
    return AssetRepository(connection)


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: AssetCreate,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[AssetRead])
def list_assets(
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
    asset_type: str | None = None,
    maitu_category: str | None = None,
    local_file_code: str | None = None,
    entity_code: str | None = None,
    maitu_type: str | None = None,
    usage: str | None = None,
    subject: str | None = None,
    maitu_project_code: str | None = None,
    maitu_scene_name: str | None = None,
    maitu_slot_name: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(
        asset_type=asset_type,
        maitu_category=maitu_category,
        local_file_code=local_file_code,
        entity_code=entity_code,
        maitu_type=maitu_type,
        usage=usage,
        subject=subject,
        maitu_project_code=maitu_project_code,
        maitu_scene_name=maitu_scene_name,
        maitu_slot_name=maitu_slot_name,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/{asset_code}", response_model=AssetRead)
def get_asset(
    asset_code: str,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> dict:
    row = repository.get_by_code(asset_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return row
