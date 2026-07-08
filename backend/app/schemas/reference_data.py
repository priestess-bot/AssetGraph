from pydantic import BaseModel, ConfigDict, Field


class DigitalHumanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    persona: str | None = None
    gender: str | None = None
    style: str | None = None
    version: str | None = None
    provider: str | None = None
    description: str | None = None


class DigitalHumanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    persona: str | None = None
    gender: str | None = None
    style: str | None = None
    version: str | None = None
    provider: str | None = None
    description: str | None = None


class DigitalHumanRead(DigitalHumanCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    digital_human_code: str


class VoiceProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    provider: str | None = None
    gender: str | None = None
    style: str | None = None
    speed: str | None = None
    emotion: str | None = None
    description: str | None = None


class VoiceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider: str | None = None
    gender: str | None = None
    style: str | None = None
    speed: str | None = None
    emotion: str | None = None
    description: str | None = None


class VoiceProfileRead(VoiceProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    voice_code: str


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    brand: str | None = None
    category: str | None = None
    selling_points: str | None = None
    pain_points: str | None = None
    description: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    brand: str | None = None
    category: str | None = None
    selling_points: str | None = None
    pain_points: str | None = None
    description: str | None = None


class ProductRead(ProductCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_code: str
