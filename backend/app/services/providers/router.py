from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainUnavailableError, DomainValidationError
from app.services.providers.contracts import (
    ProviderBinding,
    ProviderInvocationEvidence,
    StrategyRequest,
    StrategyResult,
)
from app.services.redaction import redact_sensitive_fields


class EvidenceSink(Protocol):
    def persist_provider_invocation(self, evidence: dict[str, Any]) -> str: ...


class ProcessorGuard(Protocol):
    def prepare_payload(self, **kwargs: Any) -> Any: ...


class ProviderRouter:
    def __init__(
        self,
        bindings: list[ProviderBinding],
        evidence_sink: EvidenceSink,
        processor_guard: ProcessorGuard | None = None,
    ):
        self.bindings = {binding.strategy_revision: binding for binding in bindings}
        if len(self.bindings) != len(bindings):
            raise DomainValidationError(
                "MODEL_STRATEGY_DUPLICATE",
                "Each model strategy revision must have exactly one binding",
            )
        self.evidence_sink = evidence_sink
        self.processor_guard = processor_guard

    def execute(self, request: StrategyRequest) -> StrategyResult:
        binding = self.bindings.get(request.strategy_revision)
        if binding is None:
            raise DomainUnavailableError(
                "MODEL_STRATEGY_UNAVAILABLE",
                "No provider binding is available for the requested strategy revision",
            )
        if binding.capability is not request.capability or request.capability not in binding.adapter.capabilities:
            raise DomainValidationError(
                "MODEL_STRATEGY_CAPABILITY_MISMATCH",
                "Model strategy is not registered for this capability",
            )
        if request.data_classification not in binding.allowed_classifications:
            raise DomainValidationError(
                "MODEL_STRATEGY_DATA_CLASSIFICATION_DENIED",
                "Model strategy cannot process this data classification",
            )
        redacted_input = redact_sensitive_fields(request.inputs, context="prompt")
        provider_inputs = redacted_input.value
        processor_call_audit_code = None
        if binding.processor_code is not None:
            if self.processor_guard is None or not binding.processing_region:
                raise DomainUnavailableError(
                    "EXTERNAL_PROCESSOR_GUARD_REQUIRED",
                    "External provider binding has no governed processor guard",
                )
            governed = self.processor_guard.prepare_payload(
                processor_code=binding.processor_code,
                purpose=binding.processing_purpose,
                region=binding.processing_region,
                data_classification=request.data_classification,
                payload=provider_inputs,
                principal_id=request.principal_id,
            )
            provider_inputs = governed.payload
            processor_call_audit_code = governed.audit_code
        input_bytes = canonical_json_bytes(
            {
                "capability": request.capability,
                "strategy_revision": request.strategy_revision,
                "input_schema_version": request.input_schema_version,
                "output_schema_version": request.output_schema_version,
                "inputs": provider_inputs,
                "random_seed": request.random_seed,
            }
        )
        if len(input_bytes) > binding.max_canonical_input_bytes:
            raise DomainValidationError(
                "MODEL_STRATEGY_INPUT_TOO_LARGE",
                "Canonical model input exceeds the registered strategy limit",
            )
        runtime_input_names = set(request.runtime_inputs)
        overlapping_runtime_names = sorted(runtime_input_names & set(provider_inputs))
        if overlapping_runtime_names:
            raise DomainValidationError(
                "MODEL_STRATEGY_RUNTIME_INPUT_CONFLICT",
                "Runtime inputs cannot replace fingerprinted strategy inputs",
                details={"fields": overlapping_runtime_names},
            )
        adapter_inputs = {**provider_inputs, **request.runtime_inputs}
        try:
            output = binding.adapter.invoke(
                capability=request.capability,
                model=binding.provider_model,
                inputs=adapter_inputs,
                output_json_schema=request.output_json_schema,
                trace_context=request.trace_context,
                random_seed=request.random_seed,
            )
        except DomainValidationError:
            raise
        except Exception as exc:
            raise DomainUnavailableError(
                "MODEL_PROVIDER_INVOCATION_FAILED",
                "The configured model strategy could not produce a result",
            ) from exc

        redacted_output = redact_sensitive_fields(output.content, context="model_response")
        violations = sorted(
            Draft202012Validator(request.output_json_schema).iter_errors(redacted_output.value),
            key=lambda error: list(error.absolute_path),
        )
        if violations:
            raise DomainValidationError(
                "MODEL_PROVIDER_OUTPUT_SCHEMA_INVALID",
                "Provider output failed the strategy JSON Schema",
                details={
                    "violations": [
                        {"path": "/".join(str(part) for part in error.absolute_path), "message": error.message}
                        for error in violations[:20]
                    ]
                },
            )
        input_fingerprint = hashlib.sha256(input_bytes).hexdigest()
        output_fingerprint = canonical_fingerprint(redacted_output.value)
        evidence = ProviderInvocationEvidence(
            provider_adapter=binding.adapter.adapter_code,
            requested_model=binding.provider_model,
            actual_model=output.actual_model,
            provider_response_id=output.provider_response_id,
            capability=request.capability,
            strategy_revision=request.strategy_revision,
            input_fingerprint=input_fingerprint,
            output_fingerprint=output_fingerprint,
            usage=output.usage,
            latency_ms=output.latency_ms,
            traceparent=request.trace_context.as_traceparent() if request.trace_context else None,
            redaction_policy_ref=redacted_input.policy_ref,
            input_redaction_count=len(redacted_input.redacted_paths),
            output_redaction_count=len(redacted_output.redacted_paths),
            processor_call_audit_code=processor_call_audit_code,
        )
        try:
            evidence_ref = self.evidence_sink.persist_provider_invocation(asdict(evidence))
        except Exception as exc:
            raise DomainUnavailableError(
                "MODEL_INVOCATION_EVIDENCE_NOT_PERSISTED",
                "Model output cannot be returned without durable invocation evidence",
            ) from exc
        if not evidence_ref:
            raise DomainUnavailableError(
                "MODEL_INVOCATION_EVIDENCE_NOT_PERSISTED",
                "Model output cannot be returned without durable invocation evidence",
            )
        return StrategyResult(
            capability=request.capability,
            strategy_revision=request.strategy_revision,
            output_schema_version=request.output_schema_version,
            content=redacted_output.value,
            input_fingerprint=input_fingerprint,
            output_fingerprint=output_fingerprint,
            invocation_evidence_ref=evidence_ref,
        )
