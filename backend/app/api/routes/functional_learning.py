from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.schemas.functional_learning import (
    DecisionCreate,
    DecisionRead,
    ExperimentCreate,
    ExperimentRead,
    OutcomeCreate,
)
from app.services.functional_learning import FunctionalLearningService

router = APIRouter(prefix="/functional-learning", tags=["functional-learning"])


def service(c: Annotated[Connection, Depends(get_db)]) -> FunctionalLearningService:
    return FunctionalLearningService(c)


@router.post(
    "/decisions", response_model=DecisionRead, status_code=status.HTTP_201_CREATED
)
def create_decision(
    p: DecisionCreate, s: Annotated[FunctionalLearningService, Depends(service)]
) -> dict:
    try:
        return s.create_decision(p.model_dump())
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=e.message) from e


@router.get("/decisions", response_model=list[DecisionRead])
def list_decisions(
    s: Annotated[FunctionalLearningService, Depends(service)],
) -> list[dict]:
    return s.list_decisions()


@router.post(
    "/experiments", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED
)
def create_experiment(
    p: ExperimentCreate, s: Annotated[FunctionalLearningService, Depends(service)]
) -> dict:
    try:
        return s.create_experiment(p.model_dump())
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=e.message) from e


@router.get("/experiments", response_model=list[ExperimentRead])
def list_experiments(
    s: Annotated[FunctionalLearningService, Depends(service)],
) -> list[dict]:
    return s.list_experiments()


@router.post("/experiments/{code}/outcomes", response_model=ExperimentRead)
def outcome(
    code: str,
    p: OutcomeCreate,
    s: Annotated[FunctionalLearningService, Depends(service)],
) -> dict:
    result = s.record_outcome(code, p.model_dump())
    if not result:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return result
