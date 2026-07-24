from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.domain.contracts import DataClassification
from app.domain.errors import DomainAuthorizationError, DomainValidationError
from app.services.artifacts import ContentAddressedArtifactService, require_artifact_access
from app.services.lineage import TraceContext, openlineage_run_event
from app.services.object_storage import ObjectMetadata
from app.services.providers import ArtifactProviderEvidenceSink


class FakeArtifactRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def register_artifact(self, **kwargs: Any) -> dict[str, Any]:
        for row in self.rows:
            if (
                row["checksum_sha256"],
                row["byte_size"],
                row["media_type"],
            ) == (
                kwargs["checksum_sha256"],
                kwargs["byte_size"],
                kwargs["media_type"],
            ):
                return row
        row = {"artifact_code": f"ART-{len(self.rows) + 1:06d}", **kwargs}
        self.rows.append(row)
        return row

    def get_artifact(self, artifact_code: str) -> dict[str, Any] | None:
        return next((row for row in self.rows if row["artifact_code"] == artifact_code), None)


class FailingArtifactRepository(FakeArtifactRepository):
    def __init__(self) -> None:
        super().__init__()
        self.rollback_calls = 0

    def register_artifact(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise RuntimeError("artifact registry unavailable")

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakeVersionedStorage:
    def __init__(self) -> None:
        self.versioned_buckets: set[str] = set()
        self.objects: dict[tuple[str, str], ObjectMetadata] = {}
        self.uploads = 0
        self.uploaded_content: list[bytes] = []

    def ensure_versioned_bucket(self, bucket_name: str) -> None:
        self.versioned_buckets.add(bucket_name)

    def stat_object(self, *, bucket_name: str, object_key: str) -> ObjectMetadata | None:
        return self.objects.get((bucket_name, object_key))

    def upload_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        path: Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        del content_type
        self.uploads += 1
        self.uploaded_content.append(path.read_bytes())
        self.objects[(bucket_name, object_key)] = ObjectMetadata(
            object_key=object_key,
            byte_size=path.stat().st_size,
            checksum_sha256=(metadata or {}).get("sha256"),
            version_id=f"version-{self.uploads}",
        )


def _service() -> tuple[ContentAddressedArtifactService, FakeArtifactRepository, FakeVersionedStorage]:
    repository = FakeArtifactRepository()
    storage = FakeVersionedStorage()
    return ContentAddressedArtifactService(repository, storage, bucket_name="evidence"), repository, storage


def _put(service: ContentAddressedArtifactService, path: Path, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "artifact_kind": "generation_result",
        "schema_version": "artifact.v1",
        "producer_type": "workflow_run",
        "producer_code": "RUN-001",
        "producer_revision": 1,
        "sensitivity": DataClassification.INTERNAL,
        "retention_policy_code": "production-default",
    }
    values.update(overrides)
    return service.put_file(path, **values)


def test_content_addressed_artifact_is_uploaded_once_and_storage_is_verifiable(tmp_path: Path) -> None:
    service, repository, storage = _service()
    source = tmp_path / "result.json"
    source.write_text('{"result":"ok"}', encoding="utf-8")

    first = _put(service, source)
    second = _put(service, source)

    assert first["artifact_code"] == second["artifact_code"]
    assert len(repository.rows) == 1
    assert storage.uploads == 1
    assert storage.versioned_buckets == {"evidence"}
    assert service.verify_storage(first["artifact_code"]) == {
        "artifact_code": first["artifact_code"],
        "valid": True,
        "expected_checksum": hashlib.sha256(source.read_bytes()).hexdigest(),
        "stored_checksum": hashlib.sha256(source.read_bytes()).hexdigest(),
        "expected_size": source.stat().st_size,
        "stored_size": source.stat().st_size,
        "version_id": "version-1",
    }


def test_content_address_collision_and_missing_encryption_are_rejected(tmp_path: Path) -> None:
    service, _repository, storage = _service()
    source = tmp_path / "private.bin"
    source.write_bytes(b"private")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    object_key = f"artifacts/sha256/{checksum[:2]}/{checksum}"
    storage.objects[("evidence", object_key)] = ObjectMetadata(
        object_key=object_key,
        byte_size=999,
        checksum_sha256=checksum,
        version_id="wrong",
    )

    with pytest.raises(DomainValidationError, match="content-addressed object") as collision:
        _put(service, source)
    assert collision.value.code == "ARTIFACT_CONTENT_ADDRESS_COLLISION"

    with pytest.raises(DomainValidationError, match="encryption key") as encryption:
        _put(service, source, sensitivity=DataClassification.RESTRICTED_PERSONAL)
    assert encryption.value.code == "ARTIFACT_ENCRYPTION_REQUIRED"


def test_artifact_registration_failure_rolls_back_repository_transaction(tmp_path: Path) -> None:
    repository = FailingArtifactRepository()
    storage = FakeVersionedStorage()
    service = ContentAddressedArtifactService(repository, storage, bucket_name="evidence")
    source = tmp_path / "evidence.json"
    source.write_text('{"result":"ok"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="registry unavailable"):
        _put(service, source)

    assert repository.rollback_calls == 1
    assert storage.uploads == 1


def test_artifact_access_combines_role_purpose_and_classification() -> None:
    require_artifact_access(
        {"sensitivity": DataClassification.CONFIDENTIAL.value},
        roles={"operator"},
        purpose="production",
    )
    with pytest.raises(DomainAuthorizationError) as denied:
        require_artifact_access(
            {"sensitivity": DataClassification.RESTRICTED_PERSONAL.value},
            roles={"operator"},
            purpose="analysis",
        )
    assert denied.value.code == "ARTIFACT_ACCESS_DENIED"


def test_trace_context_and_openlineage_projection_validate_contracts() -> None:
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert TraceContext.parse(traceparent).as_traceparent() == traceparent
    with pytest.raises(DomainValidationError) as invalid_trace:
        TraceContext.parse("00-00000000000000000000000000000000-00f067aa0ba902b7-01")
    assert invalid_trace.value.code == "TRACEPARENT_INVALID"

    event = openlineage_run_event(
        {
            "run_code": "RUN-001",
            "source_namespace": "assetgraph.content",
            "source_name": "script",
            "source_version": "3",
            "target_namespace": "assetgraph.production",
            "target_name": "build-plan",
            "target_version": "2",
            "relation_type": "derived_from",
        }
    )
    assert event["run"]["runId"] == "RUN-001"
    assert event["inputs"][0]["facets"]["version"]["version"] == "3"
    assert event["outputs"][0]["facets"]["version"]["version"] == "2"
    with pytest.raises(DomainValidationError) as incomplete:
        openlineage_run_event({"run_code": "RUN-001"})
    assert incomplete.value.code == "LINEAGE_EDGE_INCOMPLETE"


def test_provider_evidence_sink_keeps_supplier_details_only_in_classified_artifact() -> None:
    service, repository, storage = _service()
    sink = ArtifactProviderEvidenceSink(service, producer_code="test-strategy-producer")

    artifact_code = sink.persist_provider_invocation(
        {
            "schema_version": "provider-invocation-evidence.v1",
            "provider_adapter": "supplier-adapter.v1",
            "requested_model": "supplier-model-requested",
            "actual_model": "supplier-model-actual",
            "provider_response_id": "supplier-response-1",
            "capability": "structured_generation",
            "strategy_revision": "content-writer.v2",
            "input_fingerprint": "a" * 64,
            "output_fingerprint": "b" * 64,
            "usage": {"input_tokens": 10},
            "latency_ms": 25,
            "traceparent": None,
            "redaction_policy_ref": "baseline-sensitive-field-redaction@1",
            "input_redaction_count": 0,
            "output_redaction_count": 0,
            "processor_call_audit_code": "PROCESSOR-001",
        }
    )

    assert artifact_code == "ART-000001"
    row = repository.rows[0]
    assert row["sensitivity"] == "confidential"
    assert row["retention_policy_code"] == "critical-audit-evidence"
    assert row["metadata"] == {
        "capability": "structured_generation",
        "strategy_revision": "content-writer.v2",
        "input_fingerprint": "a" * 64,
        "output_fingerprint": "b" * 64,
    }
    assert "supplier" not in str(row["metadata"])
    artifact_payload = json.loads(storage.uploaded_content[0])
    assert artifact_payload["actual_model"] == "supplier-model-actual"
    assert artifact_payload["provider_response_id"] == "supplier-response-1"
