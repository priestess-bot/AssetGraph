from __future__ import annotations

import os
from typing import Any, Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import require_maitu_script_layout_worker
from app.api.routes import live_observations
from app.core.database import get_db
from app.domain.contracts import DataClassification
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.processor_credentials import ExternalProcessorService
from app.services.providers import ModelCapability


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="ASSETGRAPH_TEST_DATABASE_URL is not configured",
)


class MemoryEvidenceSink:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def persist_provider_invocation(self, evidence: dict[str, Any]) -> str:
        self.items.append(evidence)
        return "ART-LIVE-EVIDENCE-001"


def test_worker_provider_authorization_is_bound_to_durable_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    processor_code = f"live-provider-{suffix}"
    strategy_revision = f"live.test-asr.{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        ExternalProcessorService(PrivacyGovernanceRepository(connection)).register(
            processor_code=processor_code,
            revision_number=1,
            activate=True,
            purposes=["model_inference"],
            data_classes=[DataClassification.CONFIDENTIAL],
            region="jp-test",
            retention_terms="test processor retains no payload",
            credential_owner="test-security",
            rotation_policy="test credential rotates before use",
            minimum_fields={
                "model_inference": {
                    "required": [
                        "strategy_revision",
                        "analysis_type",
                        "input_fingerprint",
                    ],
                    "allowed": [
                        "strategy_revision",
                        "analysis_type",
                        "input_fingerprint",
                    ],
                }
            },
            exit_plan="remove the test strategy binding",
            approved_by="test-privacy-approver",
        )

    monkeypatch.setitem(
        live_observations._LIVE_EXTERNAL_STRATEGIES,
        strategy_revision,
        (
            "asr",
            ModelCapability.SPEECH_TO_TEXT,
            processor_code,
            "jp-test",
        ),
    )
    sink = MemoryEvidenceSink()
    app = FastAPI()
    app.include_router(live_observations.router, prefix="/api")

    def database() -> Iterator[psycopg.Connection]:
        with psycopg.connect(DATABASE_URL) as connection:
            yield connection

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[require_maitu_script_layout_worker] = lambda: "worker-1"
    app.dependency_overrides[live_observations.get_provider_evidence_sink] = lambda: sink

    with TestClient(app) as client:
        authorization = client.post(
            "/api/live-research/worker/provider-strategy-authorizations",
            json={
                "worker_id": "worker-1",
                "strategy_revision": strategy_revision,
                "analysis_type": "asr",
                "input_fingerprint": "a" * 64,
            },
        )
        assert authorization.status_code == 200
        audit_code = authorization.json()["processor_call_audit_code"]

        evidence = {
            "schema_version": "provider-invocation-evidence.v1",
            "provider_adapter": "supplier-asr-adapter.v1",
            "requested_model": "supplier-asr-requested",
            "actual_model": "supplier-asr-actual",
            "provider_response_id": "supplier-response-1",
            "capability": "speech_to_text",
            "strategy_revision": strategy_revision,
            "input_fingerprint": "b" * 64,
            "output_fingerprint": "c" * 64,
            "usage": {},
            "latency_ms": 25,
            "traceparent": None,
            "redaction_policy_ref": "baseline-sensitive-field-redaction@1",
            "input_redaction_count": 0,
            "output_redaction_count": 0,
            "processor_call_audit_code": audit_code,
        }
        persisted = client.post(
            "/api/live-research/worker/provider-invocation-evidence",
            json=evidence,
        )
        assert persisted.status_code == 201
        assert persisted.json() == {"artifact_code": "ART-LIVE-EVIDENCE-001"}
        assert sink.items[0]["actual_model"] == "supplier-asr-actual"

        denied = client.post(
            "/api/live-research/worker/provider-invocation-evidence",
            json={**evidence, "processor_call_audit_code": "PROCESSOR-UNKNOWN"},
        )
        assert denied.status_code == 403
        assert len(sink.items) == 1
