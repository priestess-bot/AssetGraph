from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends
from psycopg import Connection
from app.core.database import get_db
from app.schemas.functional_knowledge import FactCreate, FactRead
from app.services.functional_knowledge import FunctionalKnowledgeService

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
