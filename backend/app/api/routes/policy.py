from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection

from app.api.auth import require_control_plane_operator
from app.core.database import get_db
from app.domain.errors import DomainAuthorizationError, DomainConflictError, DomainError
from app.repositories.policy import PolicyRepository
from app.schemas.policy import ProtectedResourceRead, ProtectedResourceRegister, ProtectedResourceRevoke


router = APIRouter(prefix="/policy", tags=["policy"])


def get_policy_repository(connection: Annotated[Connection, Depends(get_db)]) -> PolicyRepository:
    return PolicyRepository(connection)


@contextmanager
def _domain_errors() -> Iterator[None]:
    try:
        yield
    except DomainAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.as_dict()) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc


@router.get("/protected-resources", response_model=list[ProtectedResourceRead])
def list_protected_resources(
    _operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[PolicyRepository, Depends(get_policy_repository)],
    resource_type: str | None = Query(default=None, min_length=1, max_length=64),
    include_revoked: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return repository.list_protected_resources(
        resource_type=resource_type,
        include_revoked=include_revoked,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/protected-resources",
    response_model=ProtectedResourceRead,
    status_code=status.HTTP_201_CREATED,
)
def register_protected_resource(
    payload: ProtectedResourceRegister,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[PolicyRepository, Depends(get_policy_repository)],
) -> dict:
    with _domain_errors():
        return repository.register_protected_resource(
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            protection_mode=payload.protection_mode,
            allowed_capabilities=[value.value for value in payload.allowed_capabilities],
            reason_code=payload.reason_code,
            evidence=payload.evidence,
            effective_at=payload.effective_at,
            expires_at=payload.expires_at,
            actor_id=operator_id,
            expected_revision=payload.expected_revision,
        )


@router.post(
    "/protected-resources/{resource_type}/{resource_id}/revoke",
    response_model=ProtectedResourceRead,
)
def revoke_protected_resource(
    resource_type: str,
    resource_id: str,
    payload: ProtectedResourceRevoke,
    operator_id: Annotated[str, Depends(require_control_plane_operator)],
    repository: Annotated[PolicyRepository, Depends(get_policy_repository)],
) -> dict:
    with _domain_errors():
        return repository.revoke_protected_resource(
            resource_type=resource_type,
            resource_id=resource_id,
            expected_revision=payload.expected_revision,
            reason_code=payload.reason_code,
            actor_id=operator_id,
        )
