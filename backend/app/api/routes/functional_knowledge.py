from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from app.core.database import get_db
from app.schemas.functional_knowledge import (
    FactClaimApprove,
    FactClaimCreate,
    FactClaimRead,
    FactClaimRevoke,
    FactCreate,
    FactRead,
    SourceEvidenceApprove,
    SourceEvidenceCreate,
    SourceEvidenceRead,
    SourceEvidenceRevoke,
)
from app.services.functional_knowledge import FunctionalKnowledgeConflictError, FunctionalKnowledgeService

router = APIRouter(prefix="/functional-knowledge", tags=["functional-knowledge"])


def svc(c: Annotated[Connection, Depends(get_db)]) -> FunctionalKnowledgeService:
    return FunctionalKnowledgeService(c)


@router.post("/facts", response_model=FactRead)
def create(
    p: FactCreate, s: Annotated[FunctionalKnowledgeService, Depends(svc)]
) -> dict:
    return s.create(p.model_dump())


@router.get("/facts", response_model=list[FactRead])
def list_facts(
    s: Annotated[FunctionalKnowledgeService, Depends(svc)], q: str | None = None
) -> list[dict]:
    return s.list(q)


@router.get("/facts/{code}/impact", response_model=list[FactRead])
def impact(
    code: str, s: Annotated[FunctionalKnowledgeService, Depends(svc)]
) -> list[dict]:
    return s.impact(code)


@router.post("/source-evidences", response_model=SourceEvidenceRead, status_code=201)
def create_source_evidence(
    payload: SourceEvidenceCreate,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    return service.create_source_evidence(payload.model_dump())


@router.get("/source-evidences", response_model=list[SourceEvidenceRead])
def list_source_evidences(
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> list[dict]:
    return service.list_source_evidences()


@router.post("/source-evidences/{evidence_code}/approve", response_model=SourceEvidenceRead)
def approve_source_evidence(
    evidence_code: str,
    payload: SourceEvidenceApprove,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.approve_source_evidence(evidence_code, payload.approved_by)
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Source evidence not found")
    return result


@router.post("/source-evidences/{evidence_code}/revoke", response_model=SourceEvidenceRead)
def revoke_source_evidence(
    evidence_code: str,
    payload: SourceEvidenceRevoke,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.revoke_source_evidence(
            evidence_code, payload.actor, payload.reason
        )
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Source evidence not found")
    return result


@router.post("/fact-claims", response_model=FactClaimRead, status_code=201)
def create_fact_claim(
    payload: FactClaimCreate,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.create_fact_claim(payload.model_dump())
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Source evidence not found")
    return result


@router.get("/fact-claims", response_model=list[FactClaimRead])
def list_fact_claims(
    service: Annotated[FunctionalKnowledgeService, Depends(svc)], q: str | None = None
) -> list[dict]:
    return service.list_fact_claims(q)


@router.post("/fact-claims/{claim_code}/approve", response_model=FactClaimRead)
def approve_fact_claim(
    claim_code: str,
    payload: FactClaimApprove,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.approve_fact_claim(claim_code, payload.approved_by)
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fact claim not found")
    return result


@router.post("/fact-claims/{claim_code}/revoke", response_model=FactClaimRead)
def revoke_fact_claim(
    claim_code: str,
    payload: FactClaimRevoke,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.revoke_fact_claim(claim_code, payload.actor, payload.reason)
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fact claim not found")
    return result
