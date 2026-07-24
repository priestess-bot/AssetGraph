from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from app.domain.contracts import DataClassification
from app.services.lineage import TraceContext


class ModelCapability(StrEnum):
    STRUCTURED_GENERATION = "structured_generation"
    SPEECH_TO_TEXT = "speech_to_text"
    OPTICAL_CHARACTER_RECOGNITION = "optical_character_recognition"
    IMAGE_UNDERSTANDING = "image_understanding"
    VIDEO_UNDERSTANDING = "video_understanding"
    EMBEDDING = "embedding"
    RERANKING = "reranking"


@dataclass(frozen=True, slots=True)
class StrategyRequest:
    capability: ModelCapability
    strategy_revision: str
    input_schema_version: str
    output_schema_version: str
    inputs: dict[str, Any]
    output_json_schema: dict[str, Any]
    # Local adapter inputs are needed to execute a strategy but are not part of
    # its reproducible identity or durable provider evidence.
    runtime_inputs: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    data_classification: DataClassification = DataClassification.INTERNAL
    trace_context: TraceContext | None = None
    random_seed: int | None = None
    principal_id: str = "system-provider-router"


@dataclass(frozen=True, slots=True)
class ProviderInvocationOutput:
    content: dict[str, Any]
    provider_response_id: str | None
    actual_model: str
    usage: dict[str, Any]
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ProviderInvocationEvidence:
    provider_adapter: str
    requested_model: str
    actual_model: str
    provider_response_id: str | None
    capability: ModelCapability
    strategy_revision: str
    input_fingerprint: str
    output_fingerprint: str
    usage: dict[str, Any]
    latency_ms: int
    traceparent: str | None
    redaction_policy_ref: str
    input_redaction_count: int
    output_redaction_count: int
    processor_call_audit_code: str | None = None
    schema_version: str = "provider-invocation-evidence.v1"


@dataclass(frozen=True, slots=True)
class StrategyResult:
    capability: ModelCapability
    strategy_revision: str
    output_schema_version: str
    content: dict[str, Any]
    input_fingerprint: str
    output_fingerprint: str
    invocation_evidence_ref: str


class ProviderAdapter(Protocol):
    adapter_code: str
    capabilities: frozenset[ModelCapability]

    def invoke(
        self,
        *,
        capability: ModelCapability,
        model: str,
        inputs: dict[str, Any],
        output_json_schema: dict[str, Any],
        trace_context: TraceContext | None,
        random_seed: int | None,
    ) -> ProviderInvocationOutput: ...


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    strategy_revision: str
    capability: ModelCapability
    adapter: ProviderAdapter
    provider_model: str
    allowed_classifications: frozenset[DataClassification] = field(
        default_factory=lambda: frozenset({DataClassification.PUBLIC, DataClassification.INTERNAL})
    )
    max_canonical_input_bytes: int = 1_000_000
    processor_code: str | None = None
    processing_region: str | None = None
    processing_purpose: str = "model_inference"
