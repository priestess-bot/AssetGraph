from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.contracts import DataClassification, canonical_json_bytes
from app.services.artifacts import ContentAddressedArtifactService
from app.services.providers.contracts import ModelCapability


class ProviderInvocationEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = Field(pattern=r"^provider-invocation-evidence\.v[1-9][0-9]*$")
    provider_adapter: str = Field(min_length=1, max_length=128)
    requested_model: str = Field(min_length=1, max_length=128)
    actual_model: str = Field(min_length=1, max_length=128)
    provider_response_id: str | None = Field(default=None, max_length=255)
    capability: ModelCapability
    strategy_revision: str = Field(min_length=1, max_length=128)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = Field(ge=0)
    traceparent: str | None = Field(default=None, max_length=128)
    redaction_policy_ref: str = Field(min_length=1, max_length=128)
    input_redaction_count: int = Field(ge=0)
    output_redaction_count: int = Field(ge=0)
    processor_call_audit_code: str | None = Field(default=None, max_length=80)


class ArtifactProviderEvidenceSink:
    """Persist classified provider details before a domain result can escape."""

    def __init__(
        self,
        artifact_service: ContentAddressedArtifactService,
        *,
        producer_code: str = "provider-router",
    ) -> None:
        self.artifact_service = artifact_service
        self.producer_code = producer_code

    def persist_provider_invocation(self, evidence: dict[str, Any]) -> str:
        record = ProviderInvocationEvidenceRecord.model_validate(evidence)
        content = canonical_json_bytes(record.model_dump(mode="json"))
        with tempfile.TemporaryDirectory(prefix="assetgraph-provider-evidence-") as directory:
            path = Path(directory) / "provider-invocation-evidence.json"
            path.write_bytes(content)
            artifact = self.artifact_service.put_file(
                path,
                artifact_kind="provider_invocation_evidence",
                schema_version=record.schema_version,
                producer_type="provider_strategy",
                producer_code=self.producer_code,
                producer_revision=None,
                sensitivity=DataClassification.CONFIDENTIAL,
                retention_policy_code="critical-audit-evidence",
                metadata={
                    "capability": record.capability.value,
                    "strategy_revision": record.strategy_revision,
                    "input_fingerprint": record.input_fingerprint,
                    "output_fingerprint": record.output_fingerprint,
                },
            )
        return str(artifact["artifact_code"])
