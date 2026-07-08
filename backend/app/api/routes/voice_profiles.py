from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.reference_data import ReferenceDataRepository, VOICE_PROFILE_TABLE
from app.schemas.reference_data import VoiceProfileCreate, VoiceProfileRead, VoiceProfileUpdate

router = APIRouter(prefix="/voice-profiles", tags=["voice-profiles"])


def get_voice_profile_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ReferenceDataRepository:
    return ReferenceDataRepository(connection, VOICE_PROFILE_TABLE)


@router.post("", response_model=VoiceProfileRead, status_code=status.HTTP_201_CREATED)
def create_voice_profile(
    payload: VoiceProfileCreate,
    repository: Annotated[ReferenceDataRepository, Depends(get_voice_profile_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[VoiceProfileRead])
def list_voice_profiles(
    repository: Annotated[ReferenceDataRepository, Depends(get_voice_profile_repository)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(limit=limit, offset=offset)


@router.get("/{voice_code}", response_model=VoiceProfileRead)
def get_voice_profile(
    voice_code: str,
    repository: Annotated[ReferenceDataRepository, Depends(get_voice_profile_repository)],
) -> dict:
    row = repository.get_by_code(voice_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found")
    return row


@router.patch("/{voice_code}", response_model=VoiceProfileRead)
def update_voice_profile(
    voice_code: str,
    payload: VoiceProfileUpdate,
    repository: Annotated[ReferenceDataRepository, Depends(get_voice_profile_repository)],
) -> dict:
    row = repository.update(voice_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found")
    return row


@router.delete("/{voice_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice_profile(
    voice_code: str,
    repository: Annotated[ReferenceDataRepository, Depends(get_voice_profile_repository)],
) -> Response:
    deleted = repository.soft_delete(voice_code)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
