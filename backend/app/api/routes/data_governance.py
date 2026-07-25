from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from psycopg import Connection

from app.core.database import get_db
from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.data_governance import DataGovernanceRepository
from app.schemas.data_governance import (
    DataContractConsumerRead,
    DataContractRead,
    DataContractRevisionWrite,
    DataQualityBatchRead,
    DataQualityViolationRead,
    MetricRevisionRead,
    MetricRevisionWrite,
    StandardEventBatchIngest,
)
from app.services.data_governance import DataGovernanceService


router = APIRouter(prefix="/data-governance", tags=["data-governance"])


def get_service(connection: Annotated[Connection, Depends(get_db)]) -> DataGovernanceService:
    return DataGovernanceService(DataGovernanceRepository(connection))


def require_items(items: list[dict], *, kind: str, code: str) -> list[dict]:
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found: {code}")
    return items


def write(callable_, *args, **kwargs) -> dict:
    try:
        return callable_(*args, **kwargs)
    except DomainConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.as_dict()) from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.as_dict()) from exc


@router.get("/metrics", response_model=list[MetricRevisionRead])
def list_metrics(instance: Annotated[DataGovernanceService, Depends(get_service)]) -> list[dict]:
    return instance.list_metrics()


@router.get("/metrics/{metric_code}/revisions", response_model=list[MetricRevisionRead])
def list_metric_revisions(
    metric_code: str,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> list[dict]:
    return require_items(instance.list_metric_revisions(metric_code), kind="Metric", code=metric_code)


@router.post(
    "/metrics/{metric_code}/revisions",
    response_model=MetricRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_metric_revision(
    metric_code: str,
    payload: MetricRevisionWrite,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> dict:
    return write(
        instance.put_metric_revision,
        metric_code=metric_code,
        expected_revision=payload.expected_revision,
        owner_principal=payload.owner_principal,
        definition=payload.definition,
        activate=payload.activate,
    )


@router.get("/contracts", response_model=list[DataContractRead])
def list_contracts(instance: Annotated[DataGovernanceService, Depends(get_service)]) -> list[dict]:
    return instance.list_contracts()


@router.get("/contracts/{contract_code}/revisions", response_model=list[DataContractRead])
def list_contract_revisions(
    contract_code: str,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> list[dict]:
    return require_items(instance.list_contract_revisions(contract_code), kind="Data contract", code=contract_code)


@router.get("/contracts/{contract_code}/consumers", response_model=list[DataContractConsumerRead])
def list_contract_consumers(
    contract_code: str,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> list[dict]:
    return instance.list_contract_consumers(contract_code)


@router.post(
    "/contracts/{contract_code}/revisions/{revision_number}",
    response_model=DataContractRead,
    status_code=status.HTTP_201_CREATED,
)
def create_contract_revision(
    contract_code: str,
    revision_number: Annotated[int, Path(ge=1)],
    payload: DataContractRevisionWrite,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> dict:
    return write(
        instance.put_contract,
        contract_code=contract_code,
        revision_number=revision_number,
        owner_principal=payload.owner_principal,
        definition=payload.definition,
        activate=payload.activate,
    )


@router.get("/batches", response_model=list[DataQualityBatchRead])
def list_quality_batches(
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> list[dict]:
    return instance.list_quality_batches()


@router.get(
    "/batches/{batch_code}/violations", response_model=list[DataQualityViolationRead]
)
def list_quality_violations(
    batch_code: str,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> list[dict]:
    return instance.list_quality_violations(batch_code)


@router.post(
    "/batches",
    response_model=DataQualityBatchRead,
    status_code=status.HTTP_201_CREATED,
)
def ingest_event_batch(
    payload: StandardEventBatchIngest,
    instance: Annotated[DataGovernanceService, Depends(get_service)],
) -> dict:
    return write(instance.ingest_event_batch, payload)
