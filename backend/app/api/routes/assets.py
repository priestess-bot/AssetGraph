from typing import Annotated

import hashlib
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from psycopg import Connection

from app.core.config import settings
from app.core.database import get_db
from app.repositories.assets import AssetRepository
from app.schemas.assets import AssetCreate, AssetFileRead, AssetRead
from app.services.asset_candidates import AssetRetrievalIndex
from app.services.object_storage import MinioObjectStorage, ObjectStorage, build_asset_object_key, content_type_for_path
from app.services.qwen3_client import Qwen3Client, Qwen3ClientError

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


def get_asset_retrieval_index() -> AssetRetrievalIndex:
    try:
        return AssetRetrievalIndex.from_jsonl_paths(
            settings.asset_retrieval_documents_path,
            settings.asset_retrieval_embeddings_path,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Asset retrieval index unavailable: {exc}",
        ) from exc


def get_candidate_qwen3_client() -> Qwen3Client:
    return Qwen3Client(
        base_url=settings.qwen3_base_url,
        api_key=settings.qwen3_api_key,
        embedding_model=settings.qwen3_embedding_model,
        rerank_model=settings.qwen3_rerank_model,
        default_dimensions=settings.qwen3_embedding_dimensions,
        timeout_seconds=settings.qwen3_timeout_seconds,
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


@router.get("/candidates")
def asset_candidates(
    q: Annotated[str, Query(min_length=1)],
    index: Annotated[AssetRetrievalIndex, Depends(get_asset_retrieval_index)],
    client: Annotated[Qwen3Client, Depends(get_candidate_qwen3_client)],
    top_k: Annotated[int, Query(ge=1, le=50)] = 10,
    candidate_pool_size: Annotated[int, Query(ge=1, le=100)] = 30,
    asset_type: str | None = None,
    maitu_category: str | None = None,
    usage: str | None = None,
    subject: str | None = None,
    rerank: bool = False,
) -> dict:
    if not index.entries:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Asset retrieval index is empty")
    try:
        vectors = client.embed_texts([q], is_query=True)
    except Qwen3ClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if not vectors:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Qwen3 returned no query embedding")

    filters = {
        "asset_type": asset_type,
        "maitu_category": maitu_category,
        "usage": usage,
        "subject": subject,
    }
    pool_size = max(top_k, candidate_pool_size) if rerank else top_k
    candidates = index.search(vectors[0], top_k=pool_size, filters=filters)
    response_candidates = [candidate.to_response() for candidate in candidates[:top_k]]

    if rerank and candidates:
        try:
            rerank_rows = client.rerank(
                q,
                [str(candidate.document.get("content") or "") for candidate in candidates],
                top_n=min(top_k, len(candidates)),
                return_documents=False,
            )
        except Qwen3ClientError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        reranked: list[dict] = []
        used_indices: set[int] = set()
        for row in rerank_rows:
            try:
                index_value = int(row.get("index"))
            except (TypeError, ValueError):
                continue
            if index_value < 0 or index_value >= len(candidates):
                continue
            used_indices.add(index_value)
            score = row.get("relevance_score")
            reranked.append(candidates[index_value].to_response(rerank_score=float(score) if score is not None else None))
        for index_value, candidate in enumerate(candidates):
            if len(reranked) >= top_k:
                break
            if index_value not in used_indices:
                reranked.append(candidate.to_response())
        response_candidates = reranked[:top_k]

    return {
        "query": q,
        "count": len(response_candidates),
        "embedding_model": client.embedding_model,
        "rerank_model": client.rerank_model if rerank else None,
        "filters": {key: value for key, value in filters.items() if value not in (None, "")},
        "candidates": response_candidates,
    }


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
