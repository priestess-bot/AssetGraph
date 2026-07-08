from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ScriptBlockCreate(BaseModel):
    block_type: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1)
    sort_order: int = 0
    estimated_duration_seconds: Decimal | None = None


class ScriptBlockRead(ScriptBlockCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    script_id: str


class ScriptCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    product_id: str | None = None
    script_type: str = "livestream"
    version: str | None = None
    description: str | None = None
    blocks: list[ScriptBlockCreate] = Field(default_factory=list)


class ScriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    script_code: str
    title: str
    product_id: str | None = None
    script_type: str
    version: str | None = None
    description: str | None = None
    blocks: list[ScriptBlockRead] = Field(default_factory=list)
