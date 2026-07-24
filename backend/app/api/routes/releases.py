from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.core.database import get_db
from app.repositories.releases import ReleaseRepository


router = APIRouter(prefix="/releases", tags=["releases"])


def repository(connection: Annotated[Connection, Depends(get_db)]) -> ReleaseRepository:
    return ReleaseRepository(connection)


@router.get("")
def list_releases(instance: Annotated[ReleaseRepository, Depends(repository)]) -> list[dict]:
    return instance.list_releases()


@router.get("/{release_code}")
def get_release(release_code: str, instance: Annotated[ReleaseRepository, Depends(repository)]) -> dict:
    release = instance.get_release(release_code)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return release
