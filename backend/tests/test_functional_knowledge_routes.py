from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import functional_knowledge


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _source(**overrides: Any) -> dict[str, Any]:
    return {
        "evidence_code": "EVIDENCE-001",
        "source_type": "document",
        "title": "Approved product sheet",
        "source_url": "https://example.test/product-sheet",
        "excerpt": "The product has a verified 12-month warranty.",
        "content_sha256": "a" * 64,
        "captured_at": NOW,
        "access_scope": "internal",
        "status": "draft",
        "created_by": "author",
        "approved_by": None,
        "approved_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }


def _claim(**overrides: Any) -> dict[str, Any]:
    return {
        "claim_code": "CLAIM-001",
        "fact_code": "FACT-001",
        "fact_title": "Warranty",
        "source_evidence_code": "EVIDENCE-001",
        "source_title": "Approved product sheet",
        "source_status": "approved",
        "field_path": "warranty",
        "claim": "The product has a 12-month warranty.",
        "citation_excerpt": "The product has a verified 12-month warranty.",
        "valid_from": None,
        "valid_until": None,
        "status": "draft",
        "created_by": "author",
        "approved_by": None,
        "approved_at": None,
        "fingerprint_sha256": "b" * 64,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }


class FakeFunctionalKnowledgeService:
    def __init__(self) -> None:
        self.source_payload: dict[str, Any] | None = None
        self.claim_payload: dict[str, Any] | None = None
        self.source_revocation: tuple[str, str, str] | None = None
        self.claim_revocation: tuple[str, str, str] | None = None

    def create_source_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.source_payload = payload
        return _source(**payload)

    @staticmethod
    def list_source_evidences() -> list[dict[str, Any]]:
        return [_source(status="approved", approved_by="reviewer", approved_at=NOW)]

    @staticmethod
    def approve_source_evidence(code: str, approved_by: str) -> dict[str, Any] | None:
        return _source(evidence_code=code, status="approved", approved_by=approved_by, approved_at=NOW)

    def revoke_source_evidence(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.source_revocation = (code, actor, reason)
        return _source(
            evidence_code=code,
            status="revoked",
            revoked_by=actor,
            revoked_at=NOW,
            revoked_reason=reason,
        )

    def create_fact_claim(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.claim_payload = payload
        return _claim(**payload)

    @staticmethod
    def list_fact_claims(q: str | None = None) -> list[dict[str, Any]]:
        return [_claim()] if q != "none" else []

    @staticmethod
    def approve_fact_claim(code: str, approved_by: str) -> dict[str, Any] | None:
        return _claim(claim_code=code, status="approved", approved_by=approved_by, approved_at=NOW)

    def revoke_fact_claim(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.claim_revocation = (code, actor, reason)
        return _claim(
            claim_code=code,
            status="revoked",
            revoked_by=actor,
            revoked_at=NOW,
            revoked_reason=reason,
        )


@pytest.fixture
def client() -> tuple[TestClient, FakeFunctionalKnowledgeService]:
    service = FakeFunctionalKnowledgeService()
    app = FastAPI()
    app.include_router(functional_knowledge.router, prefix="/api")
    app.dependency_overrides[functional_knowledge.svc] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service


def test_source_evidence_and_fact_claim_routes_keep_citation_explicit(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client
    source = test_client.post(
        "/api/functional-knowledge/source-evidences",
        json={
            "source_type": "document",
            "title": "Approved product sheet",
            "source_url": "https://example.test/product-sheet",
            "excerpt": "The product has a verified 12-month warranty.",
            "access_scope": "internal",
            "created_by": "author",
        },
    )
    approved = test_client.post(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/approve",
        json={"approved_by": "reviewer"},
    )
    claim = test_client.post(
        "/api/functional-knowledge/fact-claims",
        json={
            "fact_title": "Warranty",
            "claim": "The product has a 12-month warranty.",
            "source_evidence_code": "EVIDENCE-001",
            "citation_excerpt": "The product has a verified 12-month warranty.",
            "field_path": "warranty",
            "created_by": "author",
        },
    )
    claim_approved = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/approve",
        json={"approved_by": "reviewer"},
    )

    assert source.status_code == 201
    assert service.source_payload is not None
    assert approved.json()["status"] == "approved"
    assert claim.status_code == 201
    assert service.claim_payload is not None
    assert service.claim_payload["citation_excerpt"] == "The product has a verified 12-month warranty."
    assert claim_approved.json()["approved_by"] == "reviewer"


def test_fact_claim_route_rejects_naive_datetimes(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, _service = client
    result = test_client.post(
        "/api/functional-knowledge/fact-claims",
        json={
            "fact_title": "Warranty",
            "claim": "The product has a 12-month warranty.",
            "source_evidence_code": "EVIDENCE-001",
            "citation_excerpt": "The product has a verified 12-month warranty.",
            "valid_from": "2026-07-25T12:00:00",
        },
    )
    assert result.status_code == 422


def test_evidence_and_claim_revocation_require_attributed_reasons(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client

    source = test_client.post(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/revoke",
        json={"actor": "reviewer", "reason": "Source specification was corrected."},
    )
    claim = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/revoke",
        json={"actor": "reviewer", "reason": "The warranty claim is no longer valid."},
    )
    blank_reason = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/revoke",
        json={"actor": "reviewer", "reason": "   "},
    )
    missing = test_client.post(
        "/api/functional-knowledge/source-evidences/missing/revoke",
        json={"actor": "reviewer", "reason": "Missing source."},
    )

    assert source.status_code == 200
    assert source.json()["revoked_reason"] == "Source specification was corrected."
    assert claim.status_code == 200
    assert claim.json()["revoked_by"] == "reviewer"
    assert service.source_revocation == (
        "EVIDENCE-001",
        "reviewer",
        "Source specification was corrected.",
    )
    assert service.claim_revocation == (
        "CLAIM-001",
        "reviewer",
        "The warranty claim is no longer valid.",
    )
    assert blank_reason.status_code == 422
    assert missing.status_code == 404
