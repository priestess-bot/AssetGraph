from typing import Annotated

import hashlib
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from psycopg import Connection

from app.core.config import settings
from app.core.database import get_db
from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetCreate, AssetFileRead, AssetRead
from app.services.object_storage import MinioObjectStorage, ObjectStorage, build_asset_object_key, content_type_for_path

router = APIRouter(prefix="/assets", tags=["assets"])


def get_asset_repository(connection: Annotated[Connection, Depends(get_db)]) -> AssetRepository:
    return AssetRepository(connection)


def get_object_storage() -> ObjectStorage:
    return MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


@router.get("/stats")
def asset_stats(
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> dict:
    return repository.stats()


@router.get("/{asset_code}", response_model=AssetRead)
def get_asset(
    asset_code: str,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> dict:
    row = repository.get_by_code(asset_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return row


@router.post("/{asset_code}/files", response_model=AssetFileRead, status_code=status.HTTP_201_CREATED)
def upload_asset_file(
    asset_code: str,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    file: UploadFile = File(...),
    file_role: str = Form("original"),
    local_file_code: str | None = Form(default=None),
    source_relative_path: str | None = Form(default=None),
    checksum_sha256: str | None = Form(default=None),
) -> dict:
    asset = repository.get_by_code(asset_code)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    suffix = Path(file.filename or "upload.bin").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        shutil.copyfileobj(file.file, temp_file)
    try:
        actual_checksum = sha256_file(temp_path)
        if checksum_sha256 and actual_checksum != checksum_sha256:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="checksum_sha256 mismatch")
        filename = file.filename or f"{asset_code}{suffix or '.bin'}"
        object_key = build_asset_object_key(asset_code=asset_code, filename=filename, file_role=file_role)
        content_type = file.content_type or content_type_for_path(temp_path)
        storage.upload_file(
            bucket_name=settings.minio_bucket,
            object_key=object_key,
            path=temp_path,
            content_type=content_type,
        )
        row = repository.create_file_record(
            asset_code,
            {
                "file_role": file_role,
                "bucket_name": settings.minio_bucket,
                "object_key": object_key,
                "mime_type": content_type,
                "file_size": temp_path.stat().st_size,
                "checksum_sha256": actual_checksum,
                "source_relative_path": source_relative_path,
                "local_file_code": local_file_code,
                "storage_status": "stored",
            },
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        repository.update_status(asset_code, "stored")
        return row
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/{asset_code}/files", response_model=list[AssetFileRead])
def list_asset_files(
    asset_code: str,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> list[dict]:
    if repository.get_by_code(asset_code) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return repository.list_file_records(asset_code)
