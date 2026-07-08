from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.scripts import ScriptRepository
from app.schemas.scripts import ScriptCreate, ScriptRead

router = APIRouter(prefix="/scripts", tags=["scripts"])


def get_script_repository(connection: Annotated[Connection, Depends(get_db)]) -> ScriptRepository:
    return ScriptRepository(connection)


@router.post("", response_model=ScriptRead, status_code=status.HTTP_201_CREATED)
def create_script(
    payload: ScriptCreate,
    repository: Annotated[ScriptRepository, Depends(get_script_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[ScriptRead])
def list_scripts(
    repository: Annotated[ScriptRepository, Depends(get_script_repository)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(limit=limit, offset=offset)


@router.get("/{script_code}", response_model=ScriptRead)
def get_script(
    script_code: str,
    repository: Annotated[ScriptRepository, Depends(get_script_repository)],
) -> dict:
    row = repository.get_by_code(script_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    return row
