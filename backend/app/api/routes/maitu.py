from typing import Annotated, Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection

from app.core.config import settings
from app.core.database import get_db
from app.repositories.maitu import MaituMaterialSlotRepository
from app.services.asset_candidates import AssetCandidate, AssetRetrievalIndex
from app.services.qwen3_client import Qwen3Client, Qwen3ClientError
from app.services.script_asset_need_planner import ScriptAssetNeedPlanner
from app.services.script_scene_planner import ScriptScenePlanner
from app.services.script_scene_template_matcher import ScriptSceneTemplateMatcher
from app.schemas.maitu import (
    MaituBrowserUseOperationPlanResponse,
    MaituCandidateAssetsResponse,
    MaituLiveRoomBlueprintImportCreate,
    MaituLiveRoomBlueprintRead,
    MaituLiveRoomBuildPlanCreate,
    MaituLiveRoomBuildPlanExecutionResultCreate,
    MaituLiveRoomBuildPlanExecutionResultRead,
    MaituLiveRoomBuildPlanOperationPlanResponse,
    MaituLiveRoomBuildPlanRead,
    MaituLiveRoomComponentSearchResultRead,
    MaituLiveRoomSceneBuildPlanCreate,
    MaituJdLiveMetricSampleCreate,
    MaituJdLiveMetricSampleRead,
    MaituJdLiveMetricSessionCreate,
    MaituJdLiveMetricSessionRead,
    MaituJdLiveMetricSessionUpdate,
    MaituLiveRoomTemplateComponentRead,
    MaituLiveRoomTemplateSceneRead,
    MaituLayoutAdjustmentCreate,
    MaituLayoutAdjustmentRead,
    MaituMaterialSlotCreate,
    MaituMaterialSlotRead,
    MaituMaterialSlotUpdate,
    MaituScriptAssetNeedCreate,
    MaituScriptAssetNeedPlanRead,
    MaituScriptScenePlanCreate,
    MaituScriptScenePlanRead,
    MaituReplacementPlanCreate,
    MaituReplacementPlanExecutionResultCreate,
    MaituReplacementPlanExecutionResultRead,
    MaituReplacementPlanRead,
    MaituRetryBrowserUseOperationPlanResponse,
    MaituRetryQueueClaimNextCreate,
    MaituRetryQueueItemRead,
    MaituRetryQueueReclaimExpiredResponse,
    MaituRetryTaskExecutionResultCreate,
    MaituRetryTaskRead,
    MaituRetryTaskReleaseCreate,
    MaituRetryTaskUpdate,
    MaituRetryWorkerNextResponse,
    MaituScriptSceneTemplateMatchCreate,
    MaituScriptSceneTemplateMatchRead,
)

router = APIRouter(prefix="/maitu", tags=["maitu"])


def get_maitu_slot_repository(connection: Annotated[Connection, Depends(get_db)]) -> MaituMaterialSlotRepository:
    return MaituMaterialSlotRepository(connection)


def get_slot_asset_retrieval_index_factory() -> Callable[[], AssetRetrievalIndex]:
    def load_index() -> AssetRetrievalIndex:
        return AssetRetrievalIndex.from_jsonl_paths(
            settings.asset_retrieval_documents_path,
            settings.asset_retrieval_embeddings_path,
        )

    return load_index


def get_slot_candidate_qwen3_client_factory() -> Callable[[], Qwen3Client]:
    def build_client() -> Qwen3Client:
        return Qwen3Client(
            base_url=settings.qwen3_base_url,
            api_key=settings.qwen3_api_key,
            embedding_model=settings.qwen3_embedding_model,
            rerank_model=settings.qwen3_rerank_model,
            default_dimensions=settings.qwen3_embedding_dimensions,
            timeout_seconds=settings.qwen3_timeout_seconds,
        )

    return build_client


@router.post("/script-scene-plans", response_model=MaituScriptScenePlanRead, status_code=status.HTTP_201_CREATED)
def create_script_scene_plan(payload: MaituScriptScenePlanCreate) -> dict:
    return ScriptScenePlanner().plan(
        payload.script_text,
        target_scene_count=payload.target_scene_count,
        default_scene_duration_seconds=payload.default_scene_duration_seconds,
    )


@router.post("/script-asset-needs", response_model=MaituScriptAssetNeedPlanRead, status_code=status.HTTP_201_CREATED)
def create_script_asset_needs(payload: MaituScriptAssetNeedCreate) -> dict:
    return ScriptAssetNeedPlanner().plan(
        [scene.model_dump() for scene in payload.scenes],
        include_default_host=payload.include_default_host,
        include_script_text_need=payload.include_script_text_need,
    )


@router.post(
    "/script-scene-template-matches",
    response_model=MaituScriptSceneTemplateMatchRead,
    status_code=status.HTTP_201_CREATED,
)
def create_script_scene_template_matches(
    payload: MaituScriptSceneTemplateMatchCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    result = ScriptSceneTemplateMatcher(repository).match(
        [scene.model_dump() for scene in payload.scenes],
        blueprint_code=payload.blueprint_code,
        reference_room_id=payload.reference_room_id,
        template_library_code=payload.template_library_code,
        status=payload.status,
        auto_select_assets=payload.auto_select_assets,
        min_confidence_for_auto_match=payload.min_confidence_for_auto_match,
        candidate_scene_limit=payload.candidate_scene_limit,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room template scenes not found")
    return result


def build_slot_semantic_query(slot: dict, query: str | None = None) -> str:
    parts = [
        query,
        slot.get("slot_name"),
        slot.get("required_category"),
        " ".join(slot.get("accepted_asset_types") or []),
        slot.get("scene_name"),
        slot.get("layer_name"),
        slot.get("description"),
    ]
    return "；".join(str(part).strip() for part in parts if part)


def semantic_candidate_to_response(candidate: AssetCandidate, slot: dict) -> dict:
    document = candidate.document
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    relative_path = str(metadata.get("local_relative_path") or "")
    asset_type = str(metadata.get("asset_type") or "")
    maitu_category = str(metadata.get("maitu_category") or "")
    reasons = []
    if maitu_category == slot.get("required_category"):
        reasons.append(f"maitu_category matches required_category: {slot['required_category']}")
    if asset_type in (slot.get("accepted_asset_types") or []):
        reasons.append(f"asset_type accepted: {asset_type}")
    reasons.append("semantic retrieval matched slot context")
    return {
        "asset_code": candidate.asset_code,
        "asset_type": asset_type,
        "title": document.get("title"),
        "original_filename": Path(relative_path).name if relative_path else document.get("title"),
        "display_code": document.get("display_code"),
        "local_file_code": document.get("local_file_code"),
        "maitu_category": maitu_category,
        "maitu_project_code": metadata.get("maitu_project_code"),
        "maitu_scene_name": metadata.get("maitu_scene_name"),
        "maitu_layer_name": metadata.get("maitu_layer_name"),
        "maitu_slot_name": metadata.get("maitu_slot_name"),
        "maitu_slot_code": metadata.get("maitu_slot_code"),
        "layer_width": metadata.get("layer_width"),
        "layer_height": metadata.get("layer_height"),
        "replacement_policy": slot.get("replacement_policy"),
        "match_score": round(candidate.score, 6),
        "retrieval_score": round(candidate.score, 6),
        "content_excerpt": str(document.get("content") or "")[:500],
        "match_reasons": reasons,
    }


def semantic_candidate_assets_for_slot(
    slot: dict,
    *,
    index_factory: Callable[[], AssetRetrievalIndex],
    client_factory: Callable[[], Qwen3Client],
    limit: int,
    offset: int = 0,
    q: str | None = None,
    candidate_pool_size: int = 30,
) -> dict:
    try:
        index = index_factory()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Asset retrieval index unavailable: {exc}",
        ) from exc
    if not index.entries:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Asset retrieval index is empty")

    client = client_factory()
    semantic_query = build_slot_semantic_query(slot, q)
    try:
        vectors = client.embed_texts([semantic_query], is_query=True)
    except Qwen3ClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if not vectors:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Qwen3 returned no query embedding")

    accepted_asset_types = slot.get("accepted_asset_types") or []
    base_filters = {"maitu_category": slot.get("required_category")}
    pool_size = max(limit + offset, candidate_pool_size)
    candidates: list[AssetCandidate] = []
    if accepted_asset_types:
        for asset_type in accepted_asset_types:
            candidates.extend(
                index.search(vectors[0], top_k=pool_size, filters={**base_filters, "asset_type": asset_type})
            )
    else:
        candidates = index.search(vectors[0], top_k=pool_size, filters=base_filters)

    deduped: dict[str, AssetCandidate] = {}
    for candidate in candidates:
        previous = deduped.get(candidate.asset_code)
        if previous is None or candidate.score > previous.score:
            deduped[candidate.asset_code] = candidate
    ranked = sorted(deduped.values(), key=lambda candidate: candidate.score, reverse=True)
    assets = [semantic_candidate_to_response(candidate, slot) for candidate in ranked[offset : offset + limit]]
    return {
        "slot_code": slot["slot_code"],
        "required_category": slot["required_category"],
        "accepted_asset_types": accepted_asset_types,
        "source": "semantic_retrieval",
        "semantic_query": semantic_query,
        "embedding_model": client.embedding_model,
        "rerank_model": None,
        "assets": assets,
    }


@router.post(
    "/live-room-blueprints/import-reference",
    response_model=MaituLiveRoomBlueprintRead,
    status_code=status.HTTP_201_CREATED,
)
def import_reference_live_room_blueprint(
    payload: MaituLiveRoomBlueprintImportCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.import_reference_blueprint(payload.model_dump())


@router.get("/live-room-blueprints", response_model=list[MaituLiveRoomBlueprintRead])
def list_live_room_blueprints(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    reference_room_id: str | None = None,
    status: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_live_room_blueprints(
        reference_room_id=reference_room_id,
        status=status,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/live-room-template-scenes", response_model=list[MaituLiveRoomTemplateSceneRead])
def list_live_room_template_scenes(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    blueprint_code: str | None = None,
    reference_room_id: str | None = None,
    template_library_code: str | None = None,
    status: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_live_room_template_scenes(
        blueprint_code=blueprint_code,
        reference_room_id=reference_room_id,
        template_library_code=template_library_code,
        status=status,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/live-room-template-scenes/{scene_template_code}/components",
    response_model=list[MaituLiveRoomTemplateComponentRead],
)
def list_live_room_template_scene_components(
    scene_template_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> list[dict]:
    rows = repository.list_live_room_template_scene_components(scene_template_code)
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room template scene not found")
    return rows


@router.get(
    "/live-room-blueprints/scene-components/by-script",
    response_model=list[MaituLiveRoomComponentSearchResultRead],
)
def search_live_room_scene_components_by_script(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    q: str = Query(..., min_length=1),
    reference_room_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.search_live_room_scene_components_by_script(
        q=q,
        reference_room_id=reference_room_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/live-room-blueprints/{blueprint_code}", response_model=MaituLiveRoomBlueprintRead)
def get_live_room_blueprint(
    blueprint_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_live_room_blueprint_by_code(blueprint_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room blueprint not found")
    return row


@router.post("/live-room-build-plans", response_model=MaituLiveRoomBuildPlanRead, status_code=status.HTTP_201_CREATED)
def create_live_room_build_plan(
    payload: MaituLiveRoomBuildPlanCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_live_room_build_plan(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room blueprint not found")
    return row


@router.post("/live-room-scene-build-plans", response_model=MaituLiveRoomBuildPlanRead, status_code=status.HTTP_201_CREATED)
def create_live_room_scene_build_plan(
    payload: MaituLiveRoomSceneBuildPlanCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_live_room_scene_build_plan(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room template scene not found")
    return row


@router.get("/live-room-build-plans/{build_plan_code}", response_model=MaituLiveRoomBuildPlanRead)
def get_live_room_build_plan(
    build_plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_live_room_build_plan_by_code(build_plan_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room build plan not found")
    return row


@router.get(
    "/live-room-build-plans/{build_plan_code}/browser-use-operations",
    response_model=MaituLiveRoomBuildPlanOperationPlanResponse,
)
def get_live_room_build_plan_browser_use_operations(
    build_plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_live_room_build_plan_operations(build_plan_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room build plan not found")
    return row


@router.post(
    "/live-room-build-plans/{build_plan_code}/execution-results",
    response_model=MaituLiveRoomBuildPlanExecutionResultRead,
    status_code=status.HTTP_201_CREATED,
)
def create_live_room_build_plan_execution_result(
    build_plan_code: str,
    payload: MaituLiveRoomBuildPlanExecutionResultCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_live_room_build_plan_execution_result(build_plan_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room build plan not found")
    return row


@router.get(
    "/live-room-build-plans/{build_plan_code}/execution-results",
    response_model=list[MaituLiveRoomBuildPlanExecutionResultRead],
)
def list_live_room_build_plan_execution_results(
    build_plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    executor: str | None = None,
    execution_status: str | None = None,
    mode: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    rows = repository.list_live_room_build_plan_execution_results(
        build_plan_code,
        executor=executor,
        execution_status=execution_status,
        mode=mode,
        limit=limit,
        offset=offset,
    )
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room build plan not found")
    return rows


@router.get(
    "/live-room-build-plans/{build_plan_code}/execution-results/{execution_code}",
    response_model=MaituLiveRoomBuildPlanExecutionResultRead,
)
def get_live_room_build_plan_execution_result(
    build_plan_code: str,
    execution_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_live_room_build_plan_execution_result_by_code(build_plan_code, execution_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room build execution result not found")
    return row


@router.post("/jd-live-metric-sessions", response_model=MaituJdLiveMetricSessionRead, status_code=status.HTTP_201_CREATED)
def create_jd_live_metric_session(
    payload: MaituJdLiveMetricSessionCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_jd_live_metric_session(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu live-room build plan not found")
    return row


@router.get("/jd-live-metric-sessions", response_model=list[MaituJdLiveMetricSessionRead])
def list_jd_live_metric_sessions(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    build_plan_code: str | None = None,
    frontend_execution_code: str | None = None,
    live_room_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_jd_live_metric_sessions(
        build_plan_code=build_plan_code,
        frontend_execution_code=frontend_execution_code,
        live_room_id=live_room_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/jd-live-metric-sessions/{capture_session_code}", response_model=MaituJdLiveMetricSessionRead)
def get_jd_live_metric_session(
    capture_session_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_jd_live_metric_session_by_code(capture_session_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="JD live metric session not found")
    return row


@router.patch("/jd-live-metric-sessions/{capture_session_code}", response_model=MaituJdLiveMetricSessionRead)
def update_jd_live_metric_session(
    capture_session_code: str,
    payload: MaituJdLiveMetricSessionUpdate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.update_jd_live_metric_session(capture_session_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="JD live metric session not found")
    return row


@router.post(
    "/jd-live-metric-sessions/{capture_session_code}/samples",
    response_model=MaituJdLiveMetricSampleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_jd_live_metric_sample(
    capture_session_code: str,
    payload: MaituJdLiveMetricSampleCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_jd_live_metric_sample(capture_session_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="JD live metric session not found")
    return row


@router.get("/jd-live-metric-sessions/{capture_session_code}/samples", response_model=list[MaituJdLiveMetricSampleRead])
def list_jd_live_metric_samples(
    capture_session_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    scene_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    rows = repository.list_jd_live_metric_samples(
        capture_session_code,
        scene_name=scene_name,
        limit=limit,
        offset=offset,
    )
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="JD live metric session not found")
    return rows


@router.post("/layout-adjustments", response_model=MaituLayoutAdjustmentRead, status_code=status.HTTP_201_CREATED)
def create_layout_adjustment(
    payload: MaituLayoutAdjustmentCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.create_layout_adjustment(payload.model_dump(exclude_none=True))


@router.get("/layout-adjustments/{adjustment_code}", response_model=MaituLayoutAdjustmentRead)
def get_layout_adjustment(
    adjustment_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_layout_adjustment_by_code(adjustment_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu layout adjustment not found")
    return row


@router.post("/slots", response_model=MaituMaterialSlotRead, status_code=status.HTTP_201_CREATED)
def create_maitu_slot(
    payload: MaituMaterialSlotCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("/slots", response_model=list[MaituMaterialSlotRead])
def list_maitu_slots(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    maitu_project_code: str | None = None,
    scene_name: str | None = None,
    required_category: str | None = None,
    slot_name: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(
        maitu_project_code=maitu_project_code,
        scene_name=scene_name,
        required_category=required_category,
        slot_name=slot_name,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/slots/{slot_code}", response_model=MaituMaterialSlotRead)
def get_maitu_slot(
    slot_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_by_code(slot_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
    return row


@router.get("/slots/{slot_code}/candidate-assets", response_model=MaituCandidateAssetsResponse)
def list_candidate_assets_for_slot(
    slot_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    index_factory: Annotated[Callable[[], AssetRetrievalIndex], Depends(get_slot_asset_retrieval_index_factory)],
    client_factory: Annotated[Callable[[], Qwen3Client], Depends(get_slot_candidate_qwen3_client_factory)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    semantic: bool = False,
    q: str | None = None,
    candidate_pool_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict:
    if not semantic:
        row = repository.list_candidate_assets(slot_code, limit=limit, offset=offset)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
        return row

    slot = repository.get_by_code(slot_code)
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
    return semantic_candidate_assets_for_slot(
        slot,
        index_factory=index_factory,
        client_factory=client_factory,
        limit=limit,
        offset=offset,
        q=q,
        candidate_pool_size=candidate_pool_size,
    )


@router.patch("/slots/{slot_code}", response_model=MaituMaterialSlotRead)
def update_maitu_slot(
    slot_code: str,
    payload: MaituMaterialSlotUpdate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.update(slot_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")
    return row


@router.delete("/slots/{slot_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_maitu_slot(
    slot_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> None:
    deleted = repository.soft_delete(slot_code)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu material slot not found")


@router.post("/replacement-plans", response_model=MaituReplacementPlanRead, status_code=status.HTTP_201_CREATED)
def create_replacement_plan(
    payload: MaituReplacementPlanCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    index_factory: Annotated[Callable[[], AssetRetrievalIndex], Depends(get_slot_asset_retrieval_index_factory)],
    client_factory: Annotated[Callable[[], Qwen3Client], Depends(get_slot_candidate_qwen3_client_factory)],
) -> dict:
    data = payload.model_dump(exclude_none=True)
    if data.get("strategy") != "semantic_best_match":
        return repository.create_replacement_plan(data)

    slots = repository.resolve_plan_slots(data)
    slot_candidates = []
    for slot in slots:
        candidate_response = semantic_candidate_assets_for_slot(
            slot,
            index_factory=index_factory,
            client_factory=client_factory,
            limit=1,
            q=data.get("description"),
        )
        candidate = candidate_response["assets"][0] if candidate_response["assets"] else None
        slot_candidates.append((slot, candidate))
    return repository.create_replacement_plan(data, slot_candidates=slot_candidates)


@router.get("/replacement-plans", response_model=list[MaituReplacementPlanRead])
def list_replacement_plans(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    maitu_project_code: str | None = None,
    scene_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_replacement_plans(
        maitu_project_code=maitu_project_code,
        scene_name=scene_name,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/replacement-plans/{plan_code}", response_model=MaituReplacementPlanRead)
def get_replacement_plan(
    plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_replacement_plan_by_code(plan_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return row


@router.get("/replacement-plans/{plan_code}/browser-use-operations", response_model=MaituBrowserUseOperationPlanResponse)
def get_browser_use_operations(
    plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_browser_use_operation_plan(plan_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return row


@router.post(
    "/replacement-plans/{plan_code}/execution-results",
    response_model=MaituReplacementPlanExecutionResultRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution_result(
    plan_code: str,
    payload: MaituReplacementPlanExecutionResultCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_execution_result(plan_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return row


@router.get("/replacement-plans/{plan_code}/execution-results", response_model=list[MaituReplacementPlanExecutionResultRead])
def list_execution_results(
    plan_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    executor: str | None = None,
    execution_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    rows = repository.list_execution_results(
        plan_code,
        executor=executor,
        execution_status=execution_status,
        limit=limit,
        offset=offset,
    )
    if rows is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu replacement plan not found")
    return rows


@router.get(
    "/replacement-plans/{plan_code}/execution-results/{execution_code}",
    response_model=MaituReplacementPlanExecutionResultRead,
)
def get_execution_result(
    plan_code: str,
    execution_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_execution_result_by_code(plan_code, execution_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu execution result not found")
    return row


@router.get("/retry-tasks", response_model=list[MaituRetryTaskRead])
def list_retry_tasks(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    plan_code: str | None = None,
    execution_code: str | None = None,
    status: str | None = None,
    failure_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_retry_tasks(
        plan_code=plan_code,
        execution_code=execution_code,
        status=status,
        failure_type=failure_type,
        limit=limit,
        offset=offset,
    )


@router.get("/retry-queue", response_model=list[MaituRetryQueueItemRead])
def list_retry_queue(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
    status: str | None = "pending",
    failure_type: str | None = None,
    maitu_project_code: str | None = None,
    scene_name: str | None = None,
    max_attempts: int = 3,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list_retry_queue(
        status=status,
        failure_type=failure_type,
        maitu_project_code=maitu_project_code,
        scene_name=scene_name,
        max_attempts=max_attempts,
        limit=limit,
        offset=offset,
    )


@router.post("/retry-queue/claim-next", response_model=MaituRetryQueueItemRead)
def claim_next_retry_task(
    payload: MaituRetryQueueClaimNextCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.claim_next_retry_task(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No claimable Maitu retry task found")
    return row


@router.post("/retry-queue/reclaim-expired", response_model=MaituRetryQueueReclaimExpiredResponse)
def reclaim_expired_retry_tasks(
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    return repository.reclaim_expired_retry_tasks()


@router.post("/retry-worker/next", response_model=MaituRetryWorkerNextResponse)
def get_retry_worker_next(
    payload: MaituRetryQueueClaimNextCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_retry_worker_next(payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No claimable Maitu retry task found")
    return row


@router.get("/retry-tasks/{retry_task_code}", response_model=MaituRetryTaskRead)
def get_retry_task(
    retry_task_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_retry_task_by_code(retry_task_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.get(
    "/retry-tasks/{retry_task_code}/browser-use-operations",
    response_model=MaituRetryBrowserUseOperationPlanResponse,
)
def get_retry_task_browser_use_operations(
    retry_task_code: str,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.get_retry_task_browser_use_operation_plan(retry_task_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.post("/retry-tasks/{retry_task_code}/execution-results", response_model=MaituRetryTaskRead)
def create_retry_task_execution_result(
    retry_task_code: str,
    payload: MaituRetryTaskExecutionResultCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.create_retry_task_execution_result(retry_task_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.post("/retry-tasks/{retry_task_code}/release", response_model=MaituRetryTaskRead)
def release_retry_task(
    retry_task_code: str,
    payload: MaituRetryTaskReleaseCreate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.release_retry_task(retry_task_code, payload.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row


@router.patch("/retry-tasks/{retry_task_code}", response_model=MaituRetryTaskRead)
def update_retry_task(
    retry_task_code: str,
    payload: MaituRetryTaskUpdate,
    repository: Annotated[MaituMaterialSlotRepository, Depends(get_maitu_slot_repository)],
) -> dict:
    row = repository.update_retry_task(retry_task_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maitu retry task not found")
    return row
