from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from psycopg import Connection

from app.core.database import get_db
from app.repositories.releases import ReleaseRepository
from app.services.releases import ReleaseService


router = APIRouter(prefix="/releases", tags=["releases"])


class ReleaseActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    actor: str = Field(default="functional-operator", min_length=1, max_length=128)


class ReleaseRevokeRequest(ReleaseActionRequest):
    reason: str = Field(..., min_length=3, max_length=2000)


class ReleaseDeliveryPackageRequest(ReleaseActionRequest):
    target_name: str = Field(..., min_length=2, max_length=255)
    idempotency_key: str = Field(..., min_length=8, max_length=128)


def repository(connection: Annotated[Connection, Depends(get_db)]) -> ReleaseRepository:
    return ReleaseRepository(connection)


@router.get("")
def list_releases(
    instance: Annotated[ReleaseRepository, Depends(repository)],
    project_code: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> list[dict]:
    return instance.list_releases(project_code=project_code)


@router.get("/{release_code}")
def get_release(release_code: str, instance: Annotated[ReleaseRepository, Depends(repository)]) -> dict:
    release = instance.get_release(release_code)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return release


@router.post("/{release_code}/validate")
def validate_release(
    release_code: str,
    payload: ReleaseActionRequest,
    instance: Annotated[ReleaseRepository, Depends(repository)],
) -> dict:
    service = ReleaseService(instance, signing_key=b"validation-only", signing_key_id="validation-only")
    try:
        service.validate_candidate(release_code, actor_id=payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Release not found") from exc
    release = instance.get_release(release_code)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return release


@router.post("/{release_code}/delivery-packages")
def prepare_delivery_package(
    release_code: str,
    payload: ReleaseDeliveryPackageRequest,
    instance: Annotated[ReleaseRepository, Depends(repository)],
) -> dict:
    try:
        instance.create_delivery_attempt(
            release_code,
            target_type="manual_handoff",
            target_id=payload.target_name,
            adapter_type="download_package",
            idempotency_key=payload.idempotency_key,
            authorization_id=None,
            request_summary={"requested_by": payload.actor, "target_name": payload.target_name},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Release not found") from exc
    release = instance.get_release(release_code)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return release


@router.get("/{release_code}/delivery-package")
def download_delivery_package(
    release_code: str,
    instance: Annotated[ReleaseRepository, Depends(repository)],
) -> JSONResponse:
    release = instance.get_release(release_code)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return JSONResponse(
        content=jsonable_encoder(release),
        headers={"Content-Disposition": f'attachment; filename="{release_code}-delivery-package.json"'},
    )


@router.post("/{release_code}/revoke")
def revoke_release(
    release_code: str,
    payload: ReleaseRevokeRequest,
    instance: Annotated[ReleaseRepository, Depends(repository)],
) -> dict:
    release = instance.get_release(release_code)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release["status"] == "revoked":
        return release
    instance.transition_release(
        release_code,
        expected_status=str(release["status"]),
        target_status="revoked",
        actor_id=payload.actor,
        reason_code="OPERATOR_REVOKED",
        evidence={"summary": payload.reason},
    )
    updated = instance.get_release(release_code)
    if updated is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return updated
