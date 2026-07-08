from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg import Connection

from app.core.database import get_db
from app.repositories.reference_data import PRODUCT_TABLE, ReferenceDataRepository
from app.schemas.reference_data import ProductCreate, ProductRead, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def get_product_repository(
    connection: Annotated[Connection, Depends(get_db)],
) -> ReferenceDataRepository:
    return ReferenceDataRepository(connection, PRODUCT_TABLE)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    repository: Annotated[ReferenceDataRepository, Depends(get_product_repository)],
) -> dict:
    return repository.create(payload.model_dump(exclude_none=True))


@router.get("", response_model=list[ProductRead])
def list_products(
    repository: Annotated[ReferenceDataRepository, Depends(get_product_repository)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    return repository.list(limit=limit, offset=offset)


@router.get("/{product_code}", response_model=ProductRead)
def get_product(
    product_code: str,
    repository: Annotated[ReferenceDataRepository, Depends(get_product_repository)],
) -> dict:
    row = repository.get_by_code(product_code)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return row


@router.patch("/{product_code}", response_model=ProductRead)
def update_product(
    product_code: str,
    payload: ProductUpdate,
    repository: Annotated[ReferenceDataRepository, Depends(get_product_repository)],
) -> dict:
    row = repository.update(product_code, payload.model_dump(exclude_unset=True, exclude_none=True))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return row


@router.delete("/{product_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_code: str,
    repository: Annotated[ReferenceDataRepository, Depends(get_product_repository)],
) -> Response:
    deleted = repository.soft_delete(product_code)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
