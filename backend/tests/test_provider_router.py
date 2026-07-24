from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.contracts import DataClassification
from app.domain.errors import DomainUnavailableError, DomainValidationError
from app.services.lineage import TraceContext
from app.services.providers import (
    ModelCapability,
    ProviderBinding,
    ProviderInvocationOutput,
    ProviderRouter,
    StrategyRequest,
)


class FakeAdapter:
    adapter_code = "supplier-adapter-internal"
    capabilities = frozenset({ModelCapability.STRUCTURED_GENERATION})

    def __init__(self, content: dict[str, Any] | None = None) -> None:
        self.content = content or {"title": "Generated title"}
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> ProviderInvocationOutput:
        self.calls.append(kwargs)
        return ProviderInvocationOutput(
            content=self.content,
            provider_response_id="provider-response-secret",
            actual_model="supplier-model-actual",
            usage={"input_tokens": 10},
            latency_ms=25,
        )


class MemoryEvidenceSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.items: list[dict[str, Any]] = []

    def persist_provider_invocation(self, evidence: dict[str, Any]) -> str:
        self.items.append(evidence)
        return "" if self.fail else "ART-EVIDENCE-001"


def _request(**overrides: Any) -> StrategyRequest:
    values: dict[str, Any] = {
        "capability": ModelCapability.STRUCTURED_GENERATION,
        "strategy_revision": "content-writer.v1",
        "input_schema_version": "writer-input.v1",
        "output_schema_version": "writer-output.v1",
        "inputs": {"goal": "Introduce the product"},
        "output_json_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        "trace_context": TraceContext(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        ),
        "random_seed": 42,
    }
    values.update(overrides)
    return StrategyRequest(**values)


def _router(
    *,
    adapter: FakeAdapter | None = None,
    sink: MemoryEvidenceSink | None = None,
    allowed: frozenset[DataClassification] | None = None,
) -> tuple[ProviderRouter, FakeAdapter, MemoryEvidenceSink]:
    actual_adapter = adapter or FakeAdapter()
    actual_sink = sink or MemoryEvidenceSink()
    binding = ProviderBinding(
        strategy_revision="content-writer.v1",
        capability=ModelCapability.STRUCTURED_GENERATION,
        adapter=actual_adapter,
        provider_model="supplier-model-requested",
        allowed_classifications=allowed
        or frozenset({DataClassification.PUBLIC, DataClassification.INTERNAL}),
    )
    return ProviderRouter([binding], actual_sink), actual_adapter, actual_sink


def test_domain_result_is_provider_neutral_while_evidence_retains_supplier_details() -> None:
    router, adapter, sink = _router()
    result = router.execute(_request())

    domain_payload = asdict(result)
    assert domain_payload["strategy_revision"] == "content-writer.v1"
    assert domain_payload["invocation_evidence_ref"] == "ART-EVIDENCE-001"
    assert not ({"provider", "model", "requested_model", "actual_model"} & domain_payload.keys())
    assert adapter.calls[0]["model"] == "supplier-model-requested"
    assert sink.items[0]["provider_adapter"] == "supplier-adapter-internal"
    assert sink.items[0]["actual_model"] == "supplier-model-actual"
    assert sink.items[0]["traceparent"].startswith("00-4bf92f")


def test_missing_strategy_classification_and_invalid_output_fail_closed() -> None:
    router, _adapter, sink = _router()
    with pytest.raises(DomainUnavailableError) as missing:
        router.execute(_request(strategy_revision="missing.v1"))
    assert missing.value.code == "MODEL_STRATEGY_UNAVAILABLE"

    with pytest.raises(DomainValidationError) as classification:
        router.execute(_request(data_classification=DataClassification.CREDENTIAL))
    assert classification.value.code == "MODEL_STRATEGY_DATA_CLASSIFICATION_DENIED"

    invalid_router, _invalid_adapter, invalid_sink = _router(adapter=FakeAdapter({"unexpected": True}))
    with pytest.raises(DomainValidationError) as invalid:
        invalid_router.execute(_request())
    assert invalid.value.code == "MODEL_PROVIDER_OUTPUT_SCHEMA_INVALID"
    assert invalid_sink.items == []
    assert sink.items == []


def test_result_is_not_released_when_invocation_evidence_cannot_be_persisted() -> None:
    router, _adapter, sink = _router(sink=MemoryEvidenceSink(fail=True))
    with pytest.raises(DomainUnavailableError) as evidence:
        router.execute(_request())
    assert evidence.value.code == "MODEL_INVOCATION_EVIDENCE_NOT_PERSISTED"
    assert len(sink.items) == 1


def test_evidence_sink_exception_is_normalized_and_result_is_not_released() -> None:
    class UnavailableSink:
        def persist_provider_invocation(self, evidence: dict[str, Any]) -> str:
            del evidence
            raise OSError("object storage is unavailable")

    adapter = FakeAdapter()
    binding = ProviderBinding(
        strategy_revision="content-writer.v1",
        capability=ModelCapability.STRUCTURED_GENERATION,
        adapter=adapter,
        provider_model="supplier-model-requested",
    )

    with pytest.raises(DomainUnavailableError) as captured:
        ProviderRouter([binding], UnavailableSink()).execute(_request())

    assert captured.value.code == "MODEL_INVOCATION_EVIDENCE_NOT_PERSISTED"
    assert len(adapter.calls) == 1


def test_provider_boundary_redacts_prompt_and_model_response_before_fingerprinting() -> None:
    router, adapter, sink = _router(
        adapter=FakeAdapter({"title": "Contact person@example.test using sk-abcdefghijklmnopqrstuv"})
    )

    result = router.execute(
        _request(inputs={"goal": "Introduce", "cookie": "session=private", "user_id": "user-1"})
    )

    sent = str(adapter.calls[0]["inputs"])
    assert "session=private" not in sent
    assert "user-1" not in sent
    assert "person@example.test" not in result.content["title"]
    assert "sk-abcdefghijklmnopqrstuv" not in result.content["title"]
    assert sink.items[0]["redaction_policy_ref"] == "baseline-sensitive-field-redaction@1"
    assert sink.items[0]["input_redaction_count"] == 2
    assert sink.items[0]["output_redaction_count"] == 1


def test_external_provider_binding_requires_guard_and_uses_minimized_payload() -> None:
    adapter = FakeAdapter()
    sink = MemoryEvidenceSink()
    binding = ProviderBinding(
        strategy_revision="content-writer.v1",
        capability=ModelCapability.STRUCTURED_GENERATION,
        adapter=adapter,
        provider_model="supplier-model-requested",
        processor_code="supplier-processor",
        processing_region="jp-east",
        processing_purpose="model_inference",
    )
    with pytest.raises(DomainUnavailableError) as missing_guard:
        ProviderRouter([binding], sink).execute(_request())
    assert missing_guard.value.code == "EXTERNAL_PROCESSOR_GUARD_REQUIRED"
    assert adapter.calls == []

    class Guard:
        def prepare_payload(self, **kwargs: Any) -> SimpleNamespace:
            assert kwargs["processor_code"] == "supplier-processor"
            return SimpleNamespace(
                payload={"goal": kwargs["payload"]["goal"]},
                audit_code="PROCESSOR-001",
            )

    result = ProviderRouter([binding], sink, Guard()).execute(
        _request(inputs={"goal": "Introduce", "debug": "must not leave"})
    )
    assert adapter.calls[0]["inputs"] == {"goal": "Introduce"}
    assert sink.items[-1]["processor_call_audit_code"] == "PROCESSOR-001"
    assert result.content["title"] == "Generated title"


def test_runtime_inputs_are_sent_to_the_adapter_but_excluded_from_identity_and_evidence() -> None:
    router, adapter, sink = _router()
    stable_inputs = {"goal": "Analyze representative frames", "frame_manifest": {"frames": [{"sha256": "a" * 64}]}}

    first = router.execute(
        _request(
            inputs=stable_inputs,
            runtime_inputs={"image_paths": ["/worker-a/cache/FRAME-001.png"]},
        )
    )
    second = router.execute(
        _request(
            inputs=stable_inputs,
            runtime_inputs={"image_paths": ["/worker-b/cache/FRAME-001.png"]},
        )
    )

    assert first.input_fingerprint == second.input_fingerprint
    assert adapter.calls[0]["inputs"]["image_paths"] == ["/worker-a/cache/FRAME-001.png"]
    assert adapter.calls[1]["inputs"]["image_paths"] == ["/worker-b/cache/FRAME-001.png"]
    assert "image_paths" not in sink.items[0]
    assert "/worker-a/cache/FRAME-001.png" not in str(sink.items[0])


def test_runtime_inputs_cannot_replace_fingerprinted_inputs() -> None:
    router, _adapter, _sink = _router()

    with pytest.raises(DomainValidationError) as conflict:
        router.execute(_request(runtime_inputs={"goal": "different runtime goal"}))

    assert conflict.value.code == "MODEL_STRATEGY_RUNTIME_INPUT_CONFLICT"
