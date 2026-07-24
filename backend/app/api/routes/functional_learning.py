from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from app.core.database import get_db
from app.domain.errors import DomainValidationError
from app.schemas.functional_learning import (
    DecisionCreate,
    DecisionRead,
    EffectEstimateApprove,
    EffectEstimateCreate,
    EffectEstimateRead,
    EffectReproductionCreate,
    EffectReproductionRead,
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
    "/effects", response_model=EffectEstimateRead, status_code=status.HTTP_201_CREATED
)
def create_effect_estimate(
    p: EffectEstimateCreate, s: Annotated[FunctionalLearningService, Depends(service)]
) -> dict:
    try:
        return s.create_effect_estimate(p.model_dump())
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=e.message) from e


@router.get("/effects", response_model=list[EffectEstimateRead])
def list_effect_estimates(
    s: Annotated[FunctionalLearningService, Depends(service)]
) -> list[dict]:
    return s.list_effect_estimates()


@router.post("/effects/{effect_code}/approve", response_model=EffectEstimateRead)
def approve_effect_estimate(
    effect_code: str,
    p: EffectEstimateApprove,
    s: Annotated[FunctionalLearningService, Depends(service)],
) -> dict:
    try:
        result = s.approve_effect_estimate(effect_code, p.actor)
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=e.message) from e
    if result is None:
        raise HTTPException(status_code=404, detail="Effect estimate not found")
    return result


@router.post(
    "/effects/{effect_code}/reproduce", response_model=EffectReproductionRead, status_code=status.HTTP_201_CREATED
)
def reproduce_effect(
    effect_code: str,
    p: EffectReproductionCreate,
    s: Annotated[FunctionalLearningService, Depends(service)],
) -> dict:
    try:
        result = s.reproduce_effect(effect_code, p.model_dump(exclude_none=True))
    except DomainValidationError as e:
        raise HTTPException(status_code=422, detail=e.message) from e
    if result is None:
        raise HTTPException(status_code=404, detail="Effect estimate not found")
    return result


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
