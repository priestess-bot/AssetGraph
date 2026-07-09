from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.qwen3_client import Qwen3Client, Qwen3ClientError

router = APIRouter(prefix="/rag", tags=["rag"])


class EmbeddingPayload(BaseModel):
    texts: list[str] = Field(..., min_length=1)
    is_query: bool = False
    instruction: str | None = None
    dimensions: int | None = Field(default=None, ge=32, le=2560)


class EmbeddingResponse(BaseModel):
    model: str
    dimension: int
    vectors: list[list[float]]


class RerankPayload(BaseModel):
    query: str = Field(..., min_length=1)
    documents: list[str] = Field(..., min_length=1)
    top_n: int | None = Field(default=None, ge=1)
    instruction: str | None = None
    max_length: int | None = Field(default=None, ge=128, le=32768)
    return_documents: bool = True


class RerankResponse(BaseModel):
    model: str
    results: list[dict[str, Any]]


def get_qwen3_client() -> Qwen3Client:
    return Qwen3Client(
        base_url=settings.qwen3_base_url,
        api_key=settings.qwen3_api_key,
        embedding_model=settings.qwen3_embedding_model,
        rerank_model=settings.qwen3_rerank_model,
        default_dimensions=settings.qwen3_embedding_dimensions,
        timeout_seconds=settings.qwen3_timeout_seconds,
    )


@router.get("/qwen3/health")
def qwen3_health(client: Annotated[Qwen3Client, Depends(get_qwen3_client)]) -> dict[str, Any]:
    try:
        return client.health()
    except Qwen3ClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/embeddings", response_model=EmbeddingResponse)
def create_embeddings(
    payload: EmbeddingPayload,
    client: Annotated[Qwen3Client, Depends(get_qwen3_client)],
) -> EmbeddingResponse:
    try:
        vectors = client.embed_texts(
            payload.texts,
            is_query=payload.is_query,
            instruction=payload.instruction,
            dimensions=payload.dimensions,
        )
    except Qwen3ClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    dimension = len(vectors[0]) if vectors else 0
    return EmbeddingResponse(model=client.embedding_model, dimension=dimension, vectors=vectors)


@router.post("/rerank", response_model=RerankResponse)
def rerank_documents(
    payload: RerankPayload,
    client: Annotated[Qwen3Client, Depends(get_qwen3_client)],
) -> RerankResponse:
    try:
        results = client.rerank(
            payload.query,
            payload.documents,
            top_n=payload.top_n,
            instruction=payload.instruction,
            max_length=payload.max_length,
            return_documents=payload.return_documents,
        )
    except Qwen3ClientError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return RerankResponse(model=client.rerank_model, results=results)
