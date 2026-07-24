from __future__ import annotations

import hmac
from typing import Annotated, Any, Iterable

from fastapi import Header, HTTPException, status

from app.core.config import settings
from app.core.secret_hygiene import contains_durable_secret, contains_forbidden_value


def maitu_forbidden_values() -> tuple[str, ...]:
    values: list[str] = []
    for configured in (
        settings.maitu_script_layout_worker_token,
        settings.maitu_reconciliation_operator_token,
        settings.maitu_readback_attestation_key,
        settings.maitu_authority_token,
        settings.control_plane_worker_token,
        settings.control_plane_operator_token,
        settings.manifest_signing_key,
    ):
        if configured is not None and configured.get_secret_value():
            values.append(configured.get_secret_value())
    return tuple(values)


def reject_maitu_durable_secret(
    payload: Any,
    *,
    protocol_fields: Iterable[str] = (),
) -> None:
    durable = payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
    forbidden_values = maitu_forbidden_values()
    # Public protocol UUIDs and SHA-256 identities are structurally valid, but
    # they must never equal or contain any configured credential. Check the
    # complete payload before excluding those identity fields from the generic
    # UUID/token heuristic below.
    if contains_forbidden_value(durable, forbidden_values=forbidden_values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Durable fields must not contain credentials or claim tokens",
        )
    excluded = set(protocol_fields)

    def remove_public_protocol_fields(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: remove_public_protocol_fields(item)
                for key, item in value.items()
                if key not in excluded
            }
        if isinstance(value, list):
            return [remove_public_protocol_fields(item) for item in value]
        if isinstance(value, tuple):
            return tuple(remove_public_protocol_fields(item) for item in value)
        return value

    durable = remove_public_protocol_fields(durable)
    if contains_durable_secret(durable, forbidden_values=forbidden_values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Durable fields must not contain credentials or claim tokens",
        )


def _bearer_value(authorization: str | None, *, principal: str) -> str:
    scheme, separator, supplied = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{principal} authentication required",
        )
    return supplied


def require_maitu_reconciliation_operator(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    configured = settings.maitu_reconciliation_operator_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Maitu reconciliation operator authentication is not configured",
        )
    supplied = _bearer_value(authorization, principal="Operator")
    operator_secret = configured.get_secret_value()
    if not hmac.compare_digest(supplied, operator_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator authentication failed")
    operator_id = settings.maitu_reconciliation_operator_id.strip()
    if (
        not operator_id
        or contains_durable_secret(operator_id, forbidden_values=(operator_secret,))
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Maitu reconciliation operator identity is not configured safely",
        )
    return operator_id


def require_maitu_script_layout_worker(
    authorization: Annotated[str | None, Header()] = None,
    worker_id: Annotated[str | None, Header(alias="X-AssetGraph-Worker-ID")] = None,
) -> str:
    configured = settings.maitu_script_layout_worker_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Script-layout worker authentication is not configured",
        )
    supplied = _bearer_value(authorization, principal="Worker")
    worker_secret = configured.get_secret_value()
    if not hmac.compare_digest(supplied, worker_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker authentication failed")
    identity = str(worker_id or "").strip()
    if (
        not identity
        or len(identity) > 128
        or contains_durable_secret(identity, forbidden_values=(worker_secret,))
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid worker identity")
    return identity


def require_control_plane_worker(
    authorization: Annotated[str | None, Header()] = None,
    worker_id: Annotated[str | None, Header(alias="X-AssetGraph-Worker-ID")] = None,
) -> str:
    configured = settings.control_plane_worker_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control-plane worker authentication is not configured",
        )
    supplied = _bearer_value(authorization, principal="Control-plane worker")
    worker_secret = configured.get_secret_value()
    if not hmac.compare_digest(supplied, worker_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker authentication failed")
    identity = str(worker_id or "").strip()
    if (
        not identity
        or len(identity) > 128
        or contains_durable_secret(identity, forbidden_values=(worker_secret,))
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid worker identity")
    return identity


def require_control_plane_operator(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    configured = settings.control_plane_operator_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control-plane operator authentication is not configured",
        )
    supplied = _bearer_value(authorization, principal="Control-plane operator")
    operator_secret = configured.get_secret_value()
    if not hmac.compare_digest(supplied, operator_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator authentication failed")
    identity = settings.control_plane_operator_id.strip()
    if (
        not identity
        or len(identity) > 128
        or contains_durable_secret(identity, forbidden_values=(operator_secret,))
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Control-plane operator identity is not configured safely",
        )
    return identity
