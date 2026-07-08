from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.reference_data import DIGITAL_HUMAN_TABLE, ReferenceDataRepository
from app.schemas.reference_data import DigitalHumanCreate, DigitalHumanRead, DigitalHumanUpdate

router = APIRouter(prefix="/digital-humans", tags=["digital-humans"])


def get_digital_human_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ReferenceDataRepository:
    return ReferenceDataRepository(connection, DIGITAL_HUMAN_TABLE)


@router.post("", response_model=DigitalHumanRead, status_code=status.HTTP_201_CREATED)
def create_digital_human(
    payload: DigitalHumanCreate,
    repository: Annotated[ReferenceDataRepository, Depends(get_digital_human_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[DigitalHumanRead])
def list_digital_humans(
    repository: Annotated[ReferenceDataRepository, Depends(get_digital_human_repository)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(limit=limit, offset=offset)


@router.get("/{digital_human_code}", response_model=DigitalHumanRead)
def get_digital_human(
    digital_human_code: str,
    repository: Annotated[ReferenceDataRepository, Depends(get_digital_human_repository)],
) -> dict:
    row = repository.get_by_code(digital_human_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Digital human not found")
    return row


@router.patch("/{digital_human_code}", response_model=DigitalHumanRead)
def update_digital_human(
    digital_human_code: str,
    payload: DigitalHumanUpdate,
    repository: Annotated[ReferenceDataRepository, Depends(get_digital_human_repository)],
) -> dict:
    row = repository.update(digital_human_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Digital human not found")
    return row


@router.delete("/{digital_human_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_digital_human(
    digital_human_code: str,
    repository: Annotated[ReferenceDataRepository, Depends(get_digital_human_repository)],
) -> Response:
    deleted = repository.soft_delete(digital_human_code)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Digital human not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
