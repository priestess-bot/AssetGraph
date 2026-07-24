from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from fractions import Fraction
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED_PERSONAL = "restricted_personal"
    CREDENTIAL = "credential"


class EvidenceLevel(StrEnum):
    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    QUASI_EXPERIMENTAL = "quasi_experimental"
    RANDOMIZED = "randomized"


class Capability(StrEnum):
    EDIT_PRODUCTION = "edit_production"
    PUBLISH_FACT = "publish_fact"
    PUBLISH_TEMPLATE = "publish_template"
    APPROVE_EFFECT = "approve_effect"
    WRITE_DRAFT = "write_draft"
    UPLOAD_ASSET = "upload_asset"
    DELIVER_RELEASE = "deliver_release"
    REBUILD_PROJECTION = "rebuild_projection"
    GO_LIVE = "go_live"


class GateStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class RevisionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    object_type: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    code: str = Field(..., min_length=1, max_length=128)
    revision: int = Field(..., ge=1)
    fingerprint_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RationalTime(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value_numerator: int
    value_denominator: int = Field(default=1, ge=1)
    rate_numerator: int = Field(default=25, ge=1)
    rate_denominator: int = Field(default=1, ge=1)

    @property
    def seconds(self) -> Fraction:
        value = Fraction(self.value_numerator, self.value_denominator)
        rate = Fraction(self.rate_numerator, self.rate_denominator)
        return value / rate


class SessionTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=1)

    @model_validator(mode="after")
    def validate_half_open_range(self) -> "SessionTimeRange":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms for [start_ms,end_ms)")
        return self


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    event_id: UUID
    source_system: str = Field(..., min_length=1, max_length=64)
    source_event_id: str = Field(..., min_length=1, max_length=255)
    schema_version: str = Field(..., pattern=r"^[a-z0-9.-]+\.v[1-9][0-9]*$")
    operation: str = Field(..., pattern=r"^(insert|upsert|delete)$")
    event_time: datetime
    processing_time: datetime
    payload: dict[str, Any]
    tombstone: bool = False

    @model_validator(mode="after")
    def validate_times_and_delete(self) -> "EventEnvelope":
        if self.event_time.tzinfo is None or self.processing_time.tzinfo is None:
            raise ValueError("event_time and processing_time must be timezone-aware")
        if self.operation == "delete" and not self.tombstone:
            raise ValueError("delete events must be tombstones")
        return self


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_canonical_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Fraction):
        return {"numerator": value.numerator, "denominator": value.denominator}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "byte_size": len(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("canonical JSON does not allow non-finite numbers")
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

