from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.contracts import DataClassification, EventEnvelope, EvidenceLevel


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MetricRevisionDefinition(StrictModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    grain: str = Field(..., min_length=1, max_length=128)
    unit: str = Field(..., min_length=1, max_length=64)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    value_type: Literal["integer", "decimal", "duration_ms", "currency", "ratio"]
    aggregation: Literal["sum", "count", "min", "max", "average", "ratio", "last"]
    numerator_expression: str | None = None
    denominator_expression: str | None = None
    event_time_field: str = Field(..., min_length=1, max_length=255)
    timezone: str = Field(..., min_length=1, max_length=64)
    business_day_boundary: str = Field(default="00:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    dimensions: list[str] = Field(default_factory=list)
    deduplication_keys: list[str] = Field(..., min_length=1)
    refund_window_days: int | None = Field(default=None, ge=0)
    null_rule: dict[str, Any]
    outlier_rule: dict[str, Any]
    event_contract_refs: list[dict[str, Any]] = Field(..., min_length=1)
    schema_compatibility: dict[str, Any]
    quality_slo: dict[str, Any]
    effective_at: datetime | None = None

    @model_validator(mode="after")
    def validate_ratio_and_currency(self) -> "MetricRevisionDefinition":
        if self.aggregation == "ratio" and (not self.numerator_expression or not self.denominator_expression):
            raise ValueError("ratio metrics require numerator_expression and denominator_expression")
        if self.value_type == "currency" and self.currency is None:
            raise ValueError("currency metrics require an ISO currency code")
        return self


class DataContractDefinition(StrictModel):
    source_system: str = Field(..., min_length=1, max_length=64)
    schema_version: str = Field(..., pattern=r"^[a-z0-9.-]+\.v[1-9][0-9]*$")
    json_schema: dict[str, Any]
    event_id_path: str = Field(..., min_length=1, max_length=255)
    event_time_path: str | None = Field(default=None, max_length=255)
    operation_path: str | None = Field(default=None, max_length=255)
    primary_key_paths: list[str] = Field(..., min_length=1)
    upsert_delete_semantics: dict[str, Any]
    lateness_policy: dict[str, Any]
    compatibility_window: dict[str, Any]
    enum_mappings: dict[str, Any] = Field(default_factory=dict)
    field_classifications: dict[str, DataClassification] = Field(default_factory=dict)
    expected_volume: dict[str, Any]
    quality_slo: dict[str, Any]


class StandardEventIngest(StrictModel):
    contract_code: str = Field(..., min_length=1, max_length=80)
    contract_revision: int = Field(..., ge=1)
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field(..., min_length=1, max_length=255)
    envelope: EventEnvelope


class EvidenceAssignment(StrictModel):
    declared_level: EvidenceLevel
    method: str = Field(..., min_length=1, max_length=64)
    allocation_evidence: dict[str, Any] = Field(default_factory=dict)
    human_override: bool = False


class MetricRevisionWrite(StrictModel):
    owner_principal: str = Field(..., min_length=1, max_length=128)
    expected_revision: int = Field(..., ge=0)
    definition: MetricRevisionDefinition
    activate: bool = True


class DataContractRevisionWrite(StrictModel):
    owner_principal: str = Field(..., min_length=1, max_length=128)
    definition: DataContractDefinition
    activate: bool = True


class MetricRevisionRead(StrictModel):
    metric_code: str
    revision_number: int
    status: str
    owner_principal: str
    metric_status: str
    name: str
    description: str
    grain: str | None = None
    unit: str
    currency: str | None = None
    value_type: str
    aggregation: str
    numerator_expression: str | None = None
    denominator_expression: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    event_contract_refs: list[dict[str, Any]] = Field(default_factory=list)
    event_time_field: str | None = None
    timezone: str | None = None
    business_day_boundary: str | None = None
    deduplication_keys: list[str] = Field(default_factory=list)
    refund_window_days: int | None = None
    null_rule: dict[str, Any] = Field(default_factory=dict)
    outlier_rule: dict[str, Any] = Field(default_factory=dict)
    schema_compatibility: dict[str, Any] = Field(default_factory=dict)
    quality_slo: dict[str, Any] = Field(default_factory=dict)
    fingerprint_sha256: str
    effective_at: datetime | None = None
    created_at: datetime | None = None


class DataContractRead(StrictModel):
    contract_code: str
    revision_number: int
    status: str
    owner_principal: str
    source_system: str
    schema_version: str
    json_schema: dict[str, Any]
    event_id_path: str
    event_time_path: str | None = None
    operation_path: str | None = None
    primary_key_paths: list[str] = Field(default_factory=list)
    upsert_delete_semantics: dict[str, Any] = Field(default_factory=dict)
    lateness_policy: dict[str, Any] = Field(default_factory=dict)
    compatibility_window: dict[str, Any] = Field(default_factory=dict)
    enum_mappings: dict[str, Any] = Field(default_factory=dict)
    field_classifications: dict[str, DataClassification] = Field(default_factory=dict)
    expected_volume: dict[str, Any] = Field(default_factory=dict)
    quality_slo: dict[str, Any] = Field(default_factory=dict)
    fingerprint_sha256: str
    created_at: datetime | None = None


class DataContractConsumerRead(StrictModel):
    metric_code: str
    revision_number: int
    status: str
    owner_principal: str
    name: str
    event_contract_refs: list[dict[str, Any]] = Field(default_factory=list)
