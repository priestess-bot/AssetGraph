import hashlib
import mimetypes
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from psycopg import Connection

from app.core.config import settings
from app.api.auth import reject_maitu_durable_secret, require_maitu_script_layout_worker
from app.core.database import get_db
from app.repositories.assets import (
    AssetBindingLeaseConflictError,
    AssetBindingReceiptReplayError,
    AssetRepository,
)
from app.repositories.material_library import (
    MaterialLibraryConflictError,
    MaterialLibraryNotFoundError,
    MaterialLibraryRepository,
    MaterialLibraryValidationError,
)
from app.schemas.assets import AssetCreate, AssetFileRead, AssetMaituMaterialBindingUpdate, AssetRead
from app.schemas.material_library import (
    AssetConstraintProfileRead,
    AssetConstraintProfilePromoteRoomOverride,
    AssetConstraintProfileRevisionRead,
    AssetConstraintProfileWrite,
    AssetClassificationBatchUpdate,
    AssetClassificationUpdate,
    AssetGapCreate,
    AssetGapRead,
    AssetGapUpdate,
    MaterialSelectionPreviewRequest,
    AssetGroupCreate,
    AssetGroupMembersReplace,
    AssetGroupRead,
    ExecutionCapability,
    MaterialPackCreate,
    MaterialPackRead,
    MaterialPackRevisionCreate,
    MaterialPackRevisionRead,
    MaterialRole,
    MediaKind,
)
from app.services.asset_candidates import AssetRetrievalIndex
from app.services.maitu_authority import (
    MaituAuthorityConfigurationError,
    MaituAuthorityError,
    MaituAuthorityUpstreamError,
    MaituAuthorityVerifier,
    get_maitu_authority_verifier,
)
from app.services.object_storage import MinioObjectStorage, ObjectStorage, build_asset_object_key, content_type_for_path
from app.services.qwen3_client import Qwen3Client, Qwen3ClientError

router = APIRouter(prefix="/assets", tags=["assets"])
_PREVIEWABLE_MEDIA_KINDS = frozenset({"audio", "image", "video"})


def get_asset_repository(connection: Annotated[Connection, Depends(get_db)]) -> AssetRepository:
    return AssetRepository(connection)


def get_material_library_repository(connection: Annotated[Connection, Depends(get_db)]) -> MaterialLibraryRepository:
    return MaterialLibraryRepository(connection)


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


def _local_preview_path(asset: dict, *, root: Path) -> Path:
    if (
        str(asset.get("execution_capability") or "") != ExecutionCapability.LOCAL_ONLY.value
        or str(asset.get("media_kind") or "") not in _PREVIEWABLE_MEDIA_KINDS
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset preview not found")

    relative_path = PurePosixPath(str(asset.get("local_relative_path") or "").replace("\\", "/"))
    if not relative_path.parts or relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset preview not found")

    candidate = (root / Path(*relative_path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset preview not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset preview not found")

    expected_checksum = str(asset.get("checksum_sha256") or "").strip().lower()
    if len(expected_checksum) != 64 or sha256_file(candidate) != expected_checksum:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset preview file changed")
    return candidate


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
    media_kind: MediaKind | None = None,
    material_role: MaterialRole | None = None,
    execution_capability: ExecutionCapability | None = None,
) -> list[dict]:
    rows = repository.list(
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
    return [
        row
        for row in rows
        if (media_kind is None or row.get("media_kind") == media_kind)
        and (material_role is None or material_role in (row.get("material_roles") or []))
        and (execution_capability is None or row.get("execution_capability") == execution_capability)
    ]


@router.get("/stats")
def asset_stats(
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> dict:
    return repository.stats()


@router.patch("/{asset_code}/classification", response_model=AssetRead)
def update_asset_classification(
    asset_code: str,
    payload: AssetClassificationUpdate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    row = repository.update_asset_classification(
        asset_code,
        media_kind=payload.media_kind,
        material_roles=list(payload.material_roles),
        execution_capability=payload.execution_capability,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return row


@router.patch("/batch-classification", response_model=list[AssetRead])
def update_asset_classifications(
    payload: AssetClassificationBatchUpdate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> list[dict]:
    try:
        return repository.update_asset_classifications(
            list(payload.asset_codes),
            media_kind=payload.media_kind,
            material_roles=list(payload.material_roles),
            execution_capability=payload.execution_capability,
        )
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/groups", response_model=AssetGroupRead, status_code=status.HTTP_201_CREATED)
def create_asset_group(
    payload: AssetGroupCreate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        return repository.create_group(payload.model_dump())
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/groups", response_model=list[AssetGroupRead])
def list_asset_groups(
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> list[dict]:
    return repository.list_groups()


@router.put("/groups/{group_code}/members", response_model=AssetGroupRead)
def replace_asset_group_members(
    group_code: str,
    payload: AssetGroupMembersReplace,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        row = repository.replace_group_members(group_code, payload.asset_codes)
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset group not found")
    return row


@router.post("/{asset_code}/constraint-profile", response_model=AssetConstraintProfileRead)
def write_asset_constraint_profile(
    asset_code: str,
    payload: AssetConstraintProfileWrite,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    row = repository.write_constraint_profile(asset_code, [rule.model_dump(mode="json") for rule in payload.constraints])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return row


@router.get("/{asset_code}/constraint-profile", response_model=AssetConstraintProfileRead)
def get_asset_constraint_profile(
    asset_code: str,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    row = repository.get_constraint_profile(asset_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset constraint profile not found")
    return row


@router.get(
    "/{asset_code}/constraint-profile/revisions",
    response_model=list[AssetConstraintProfileRevisionRead],
)
def list_asset_constraint_profile_revisions(
    asset_code: str,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> list[dict]:
    rows = repository.list_constraint_profile_revisions(asset_code)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset constraint profile not found",
        )
    return rows


@router.post(
    "/{asset_code}/constraint-profile/promote-room-override",
    response_model=AssetConstraintProfileRevisionRead,
)
def promote_room_constraint_override(
    asset_code: str,
    payload: AssetConstraintProfilePromoteRoomOverride,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        row = repository.promote_room_constraint_override(
            asset_code,
            plan_code=payload.plan_code.strip(),
            expected_revision=payload.expected_revision,
            actor=payload.actor.strip(),
            reason=payload.reason.strip(),
        )
    except MaterialLibraryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MaterialLibraryConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return row


@router.post("/material-packs", response_model=MaterialPackRead, status_code=status.HTTP_201_CREATED)
def create_material_pack(
    payload: MaterialPackCreate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        return repository.create_pack(payload.model_dump(mode="json"))
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/material-packs", response_model=list[MaterialPackRead])
def list_material_packs(
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> list[dict]:
    return repository.list_packs()


@router.post("/material-packs/{pack_code}/publish", response_model=MaterialPackRead)
def publish_material_pack(
    pack_code: str,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        row = repository.publish_pack(pack_code)
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material pack not found")
    return row


@router.get("/material-packs/{pack_code}/revisions", response_model=list[MaterialPackRevisionRead])
def list_material_pack_revisions(
    pack_code: str,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> list[dict]:
    rows = repository.list_pack_revisions(pack_code)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material pack not found")
    return rows


@router.post("/material-packs/{pack_code}/revisions", response_model=MaterialPackRead, status_code=status.HTTP_201_CREATED)
def create_material_pack_revision(
    pack_code: str,
    payload: MaterialPackRevisionCreate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        row = repository.create_pack_revision(
            pack_code,
            expected_revision=payload.expected_revision,
            entries=[entry.model_dump(mode="json") for entry in payload.entries],
        )
    except MaterialLibraryValidationError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if str(exc).startswith("MATERIAL_PACK_REVISION_CONFLICT")
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material pack not found")
    return row


@router.post("/gaps", response_model=AssetGapRead, status_code=status.HTTP_201_CREATED)
def create_asset_gap(
    payload: AssetGapCreate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    return repository.create_gap(payload.model_dump(mode="json"))


@router.get("/gaps", response_model=list[AssetGapRead])
def list_asset_gaps(
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> list[dict]:
    return repository.list_gaps()


@router.post("/selection-preview")
def preview_material_selection(
    payload: MaterialSelectionPreviewRequest,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    return repository.preview_selection(role=payload.role.value, carrier_kind=payload.carrier_kind)


@router.patch("/gaps/{gap_code}", response_model=AssetGapRead)
def update_asset_gap(
    gap_code: str,
    payload: AssetGapUpdate,
    repository: Annotated[MaterialLibraryRepository, Depends(get_material_library_repository)],
) -> dict:
    try:
        row = repository.update_gap(gap_code, payload.model_dump(mode="json"))
    except MaterialLibraryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset gap not found")
    return row


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


@router.get("/{asset_code}/preview")
def get_asset_preview(
    asset_code: str,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
) -> FileResponse:
    asset = repository.get_by_code(asset_code)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset preview not found")

    root = settings.asset_materials_root.expanduser().resolve()
    candidate = _local_preview_path(asset, root=root)
    media_type = (
        str(asset.get("mime_type") or "").strip()
        or mimetypes.guess_type(candidate.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(
        candidate,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
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


@router.patch("/{asset_code}/maitu-material-binding", response_model=AssetRead)
def update_asset_maitu_material_binding(
    asset_code: str,
    payload: AssetMaituMaterialBindingUpdate,
    repository: Annotated[AssetRepository, Depends(get_asset_repository)],
    _worker_id: Annotated[str, Depends(require_maitu_script_layout_worker)],
    authority: Annotated[MaituAuthorityVerifier, Depends(get_maitu_authority_verifier)],
) -> dict:
    binding = payload.model_dump(mode="json")
    reject_maitu_durable_secret(
        binding,
        protocol_fields=("source_material_url", "source_cover_url"),
    )
    try:
        attested_binding = authority.attest_binding(asset_code, binding)
    except MaituAuthorityError as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if isinstance(exc, (MaituAuthorityConfigurationError, MaituAuthorityUpstreamError))
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=status_code, detail="Backend Maitu inventory verification failed") from exc
    durable_payload = {
        **{
            field_name: attested_binding[field_name]
            for field_name in (
                "maitu_material_id",
                "source_material_type",
                "source_material_url",
                "source_cover_url",
                "speaker_id",
                "digital_human_image_id",
            )
        },
        "maitu_binding_verification_source": "backend_maitu_inventory_readback",
        "maitu_binding_verified_at": datetime.now(UTC),
        "maitu_binding_scope": "assetgraph_script_layout_material_binding_v2",
        "maitu_binding_inventory_fingerprint": attested_binding["inventory_snapshot_sha256"],
        "maitu_binding_readback_nonce": attested_binding["readback_nonce"],
        "maitu_binding_attestation": attested_binding["readback_attestation"],
    }
    try:
        row = repository.update_maitu_material_binding(asset_code, durable_payload)
    except AssetBindingReceiptReplayError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maitu material binding readback receipt was already consumed",
        ) from exc
    except AssetBindingLeaseConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset Maitu material binding cannot change during an active retry worker lease",
        ) from exc
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
