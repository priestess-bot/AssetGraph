from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from app.core.database import get_db
from app.schemas.functional_knowledge import (
    ContentRuleApprove,
    ContentRuleCreate,
    ContentRuleRead,
    ContentRuleReject,
    ContentRuleRevoke,
    FactClaimApprove,
    FactClaimCreate,
    FactClaimLineageRead,
    FactClaimReject,
    FactClaimRead,
    FactClaimRevoke,
    FactCreate,
    FactRead,
    SourceEvidenceApprove,
    SourceEvidenceCreate,
    SourceExtractionRunRead,
    SourceEvidenceReject,
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


@router.get(
    "/source-evidences/{evidence_code}/extraction-runs",
    response_model=list[SourceExtractionRunRead],
)
def list_source_extraction_runs(
    evidence_code: str,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> list[dict]:
    result = service.list_source_extraction_runs(evidence_code)
    if result is None:
        raise HTTPException(status_code=404, detail="Source evidence not found")
    return result


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


@router.post("/source-evidences/{evidence_code}/reject", response_model=SourceEvidenceRead)
def reject_source_evidence(
    evidence_code: str,
    payload: SourceEvidenceReject,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.reject_source_evidence(
            evidence_code, payload.actor, payload.reason
        )
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


@router.post("/content-rules", response_model=ContentRuleRead, status_code=201)
def create_content_rule(
    payload: ContentRuleCreate,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        return service.create_content_rule(payload.model_dump())
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/content-rules", response_model=list[ContentRuleRead])
def list_content_rules(
    service: Annotated[FunctionalKnowledgeService, Depends(svc)], q: str | None = None
) -> list[dict]:
    return service.list_content_rules(q)


@router.post("/content-rules/{rule_code}/approve", response_model=ContentRuleRead)
def approve_content_rule(
    rule_code: str,
    payload: ContentRuleApprove,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.approve_content_rule(rule_code, payload.approved_by)
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Content rule not found")
    return result


@router.post("/content-rules/{rule_code}/reject", response_model=ContentRuleRead)
def reject_content_rule(
    rule_code: str,
    payload: ContentRuleReject,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.reject_content_rule(rule_code, payload.actor, payload.reason)
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Content rule not found")
    return result


@router.post("/content-rules/{rule_code}/revoke", response_model=ContentRuleRead)
def revoke_content_rule(
    rule_code: str,
    payload: ContentRuleRevoke,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.revoke_content_rule(rule_code, payload.actor, payload.reason)
    except FunctionalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Content rule not found")
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


@router.get("/fact-claims/{claim_code}/lineage", response_model=FactClaimLineageRead)
def get_fact_claim_lineage(
    claim_code: str,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    result = service.get_fact_claim_lineage(claim_code)
    if result is None:
        raise HTTPException(status_code=404, detail="Fact claim not found")
    return result


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


@router.post("/fact-claims/{claim_code}/reject", response_model=FactClaimRead)
def reject_fact_claim(
    claim_code: str,
    payload: FactClaimReject,
    service: Annotated[FunctionalKnowledgeService, Depends(svc)],
) -> dict:
    try:
        result = service.reject_fact_claim(claim_code, payload.actor, payload.reason)
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
