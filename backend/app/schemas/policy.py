from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.contracts import Capability


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProtectedResourceRegister(StrictModel):
    resource_type: Literal[
        "maitu_room",
        "live_room",
        "platform_account",
        "production_object",
        "external_resource",
    ]
    resource_id: str = Field(..., min_length=1, max_length=255)
    protection_mode: Literal["read_only", "deny_write", "allowlisted_write"]
    allowed_capabilities: list[Capability] = Field(default_factory=list, max_length=9)
    reason_code: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    evidence: dict[str, Any] = Field(default_factory=dict)
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_window_and_allowlist(self) -> "ProtectedResourceRegister":
        if self.expires_at is not None and self.effective_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be later than effective_at")
        if self.protection_mode != "allowlisted_write" and self.allowed_capabilities:
            raise ValueError("allowed_capabilities requires allowlisted_write")
        return self


class ProtectedResourceRevoke(StrictModel):
    expected_revision: int = Field(..., ge=1)
    reason_code: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")


class ProtectedResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_type: str
    resource_id: str
    protection_mode: str
    allowed_capabilities: list[str]
    reason_code: str
    evidence: dict[str, Any]
    effective_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by: str
    created_at: datetime
    revision: int
