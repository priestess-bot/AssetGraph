from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, status
from psycopg import Connection

from app.core.database import get_db
from app.domain.errors import (
    DomainConflictError,
    DomainUnavailableError,
    DomainValidationError,
)
from app.schemas.content_workflow import (
    GuidedContentProjectCreate,
    GuidedGenerationJobRead,
    GuidedMaterialPoolUpdate,
    GuidedMaterialWaiver,
    GuidedOutlineSectionRegenerate,
    GuidedOutlineRevisionUpdate,
    GuidedProjectSetupUpdate,
    GuidedRecommendationRequest,
    GuidedRevisionAction,
    GuidedScriptRestore,
    GuidedScriptRevisionUpdate,
    GuidedStoryboardConfirm,
    GuidedStoryboardGenerate,
    GuidedStoryboardUpdate,
    GuidedThemeOptimizeRequest,
    GuidedWorkflowRead,
)
from app.services.content_workflow import GuidedContentWorkflowService


router = APIRouter(prefix="/content-projects", tags=["guided-content-workflow"])
ACTOR_ID = "functional-operator"


def get_service(
    connection: Annotated[Connection, Depends(get_db)],
) -> GuidedContentWorkflowService:
    return GuidedContentWorkflowService(connection)


def _call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guided content object not found") from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc
    except DomainUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.as_dict()) from exc


@router.post("/guided", response_model=GuidedWorkflowRead, status_code=status.HTTP_201_CREATED)
def create_guided_project(
    payload: GuidedContentProjectCreate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    return _call(
        lambda: service.create_project(
            title=payload.title,
            target_live_room_id=payload.target_live_room_id,
            actor_id=ACTOR_ID,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/{project_code}/guided-workflow", response_model=GuidedWorkflowRead)
def get_guided_workflow(
    project_code: str,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(lambda: service.get_workflow(project_code))


@router.patch("/{project_code}/guided-workflow/setup", response_model=GuidedWorkflowRead)
def update_guided_setup(
    project_code: str,
    payload: GuidedProjectSetupUpdate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.update_setup(
            project_code,
            expected_project_revision=payload.expected_project_revision,
            expected_material_pool_revision=payload.expected_material_pool_revision,
            theme=payload.theme,
            selected_asset_codes=payload.selected_asset_codes,
            actor_id=ACTOR_ID,
            selected_knowledge_refs=[item.model_dump(mode="json") for item in payload.selected_knowledge_refs],
        )
    )


@router.post(
    "/{project_code}/guided-workflow/setup/theme-optimize",
    response_model=GuidedGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def optimize_guided_theme(
    project_code: str,
    payload: GuidedThemeOptimizeRequest,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.enqueue_theme_optimization(
            project_code, theme=payload.theme, actor_id=ACTOR_ID
        )
    )


@router.post(
    "/{project_code}/guided-workflow/setup/recommendations",
    response_model=GuidedGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def recommend_guided_setup(
    project_code: str,
    payload: GuidedRecommendationRequest,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.enqueue_recommendations(
            project_code,
            kind=payload.kind,
            theme=payload.theme,
            actor_id=ACTOR_ID,
        )
    )


@router.get("/{project_code}/guided-workflow/maitu-room-configuration")
def get_guided_maitu_room_configuration(
    project_code: str,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(lambda: service.maitu_room_configuration(project_code))


@router.put("/{project_code}/guided-workflow/material-pool", response_model=GuidedWorkflowRead)
def update_guided_material_pool(
    project_code: str,
    payload: GuidedMaterialPoolUpdate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.update_script_material_pool(
            project_code,
            expected_revision=payload.expected_revision,
            selected_asset_codes=payload.selected_asset_codes,
            actor_id=ACTOR_ID,
        )
    )


@router.post(
    "/{project_code}/guided-workflow/outline/generate",
    response_model=GuidedGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_guided_outline(
    project_code: str,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(lambda: service.enqueue_outline(project_code, actor_id=ACTOR_ID))


@router.post(
    "/{project_code}/guided-workflow/outline/sections/{section_key}/regenerate",
    response_model=GuidedGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_guided_outline_section(
    project_code: str,
    section_key: str,
    payload: GuidedOutlineSectionRegenerate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.enqueue_outline_section_regeneration(
            project_code,
            section_key,
            expected_revision=payload.expected_revision,
            guidance=payload.guidance,
            actor_id=ACTOR_ID,
        )
    )


@router.put("/{project_code}/guided-workflow/outline", response_model=GuidedWorkflowRead)
def revise_guided_outline(
    project_code: str,
    payload: GuidedOutlineRevisionUpdate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.revise_outline(
            project_code,
            expected_revision=payload.expected_revision,
            sections=[section.model_dump(mode="json") for section in payload.sections],
            actor_id=ACTOR_ID,
        )
    )


@router.post("/{project_code}/guided-workflow/outline/confirm", response_model=GuidedWorkflowRead)
def confirm_guided_outline(
    project_code: str,
    payload: GuidedRevisionAction,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.confirm_outline(
            project_code, expected_revision=payload.expected_revision, actor_id=ACTOR_ID
        )
    )


@router.post("/{project_code}/guided-workflow/outline/reopen", response_model=GuidedWorkflowRead)
def reopen_guided_outline(
    project_code: str,
    payload: GuidedRevisionAction,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.reopen_outline(
            project_code, expected_revision=payload.expected_revision, actor_id=ACTOR_ID
        )
    )


@router.post(
    "/{project_code}/guided-workflow/script/generate",
    response_model=GuidedGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_guided_script(
    project_code: str,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(lambda: service.enqueue_script(project_code, actor_id=ACTOR_ID))


@router.put("/{project_code}/guided-workflow/script", response_model=GuidedWorkflowRead)
def revise_guided_script(
    project_code: str,
    payload: GuidedScriptRevisionUpdate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.revise_script(
            project_code,
            expected_revision=payload.expected_revision,
            blocks=[block.model_dump(mode="json") for block in payload.blocks],
            actor_id=ACTOR_ID,
        )
    )


@router.post(
    "/{project_code}/guided-workflow/script/requirements/{requirement_code}/waive",
    response_model=GuidedWorkflowRead,
)
def waive_guided_material_requirement(
    project_code: str,
    requirement_code: str,
    payload: GuidedMaterialWaiver,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.waive_material_requirement(
            project_code,
            requirement_code,
            expected_script_revision=payload.expected_script_revision,
            actor_id=ACTOR_ID,
        )
    )


@router.post("/{project_code}/guided-workflow/script/confirm", response_model=GuidedWorkflowRead)
def confirm_guided_script(
    project_code: str,
    payload: GuidedRevisionAction,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.confirm_script(
            project_code, expected_revision=payload.expected_revision, actor_id=ACTOR_ID
        )
    )


@router.post("/{project_code}/guided-workflow/script/reopen", response_model=GuidedWorkflowRead)
def reopen_guided_script(
    project_code: str,
    payload: GuidedRevisionAction,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.reopen_script(
            project_code, expected_revision=payload.expected_revision, actor_id=ACTOR_ID
        )
    )


@router.get("/{project_code}/guided-workflow/revisions")
def list_guided_revisions(
    project_code: str,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: {
            "script": service.script_archives(project_code),
            "script_archives": service.script_archives(project_code),
        }
    )


@router.post("/{project_code}/guided-workflow/script/revisions/{revision_number}/restore", response_model=GuidedWorkflowRead)
def restore_guided_script(
    project_code: str,
    revision_number: int,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
    payload: GuidedScriptRestore | None = None,
) -> dict[str, Any]:
    return _call(
        lambda: service.restore_script(
            project_code,
            revision_number,
            expected_current_revision=(payload.expected_current_revision if payload else None),
            actor_id=ACTOR_ID,
        )
    )


@router.post(
    "/{project_code}/guided-workflow/storyboard/generate",
    response_model=GuidedGenerationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_guided_storyboard(
    project_code: str,
    payload: GuidedStoryboardGenerate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.enqueue_storyboard(
            project_code,
            template_code=payload.template_code,
            revision=payload.revision,
            projection_fingerprint=payload.projection_fingerprint,
            actor_id=ACTOR_ID,
        )
    )


@router.put("/{project_code}/guided-workflow/storyboard", response_model=GuidedWorkflowRead)
def revise_guided_storyboard(
    project_code: str,
    payload: GuidedStoryboardUpdate,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.revise_storyboard(
            project_code,
            expected_plan_code=payload.expected_plan_code,
            scenes=[scene.model_dump(mode="json") for scene in payload.scenes],
            actor_id=ACTOR_ID,
        )
    )


@router.post("/{project_code}/guided-workflow/storyboard/confirm", response_model=GuidedWorkflowRead)
def confirm_guided_storyboard(
    project_code: str,
    payload: GuidedStoryboardConfirm,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(
        lambda: service.confirm_storyboard(
            project_code, expected_plan_code=payload.expected_plan_code, actor_id=ACTOR_ID
        )
    )


@router.post("/{project_code}/guided-workflow/jobs/{job_code}/retry", response_model=GuidedWorkflowRead)
def retry_guided_generation_job(
    project_code: str,
    job_code: str,
    service: Annotated[GuidedContentWorkflowService, Depends(get_service)],
) -> dict[str, Any]:
    return _call(lambda: service.retry_job(project_code, job_code))
